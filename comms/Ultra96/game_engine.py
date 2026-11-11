"""Deterministic Ultra96 match rules, independent of WebSocket transport.

Only server-originated classified actions call these methods. Phone messages
provide target observations, never authoritative damage or guard decisions.
"""

from dataclasses import dataclass
import math
import random
import time


BASE_DAMAGE = {
    "JAB": 5.0, "CROSS": 7.0,
    "LEFT_HOOK": 10.0, "RIGHT_HOOK": 10.0,
    "LEFT_UPPERCUT": 15.0, "RIGHT_UPPERCUT": 15.0,
}
STAMINA_COST = {
    "JAB": 8.0, "CROSS": 10.0,
    "LEFT_HOOK": 15.0, "RIGHT_HOOK": 15.0,
    "LEFT_UPPERCUT": 22.0, "RIGHT_UPPERCUT": 22.0,
}
ANIMATION_SECONDS = {
    "JAB": 0.5, "CROSS": 0.5,
    "LEFT_HOOK": 0.7, "RIGHT_HOOK": 0.7,
    "LEFT_UPPERCUT": 1.0, "RIGHT_UPPERCUT": 1.0,
}
STAMINA_REGEN_PER_SECOND = 12.0
GUARD_COST = 8.0
GUARD_SECONDS = 1.0
HELD_GUARD_COST_PER_SECOND = GUARD_COST / GUARD_SECONDS
HELD_GUARD_SENSOR_TIMEOUT = 1.0
BLOCK_DAMAGE_MULTIPLIER = 0.3
# Weave (CG4002-Viz docs/protocol.md "Weave", docs/weave-plan.md): invincible to
# punches for WEAVE_SECONDS at a high stamina cost. No regeneration while
# weaving, so it effectively costs about 35 + 36 = 71 stamina. No punching or
# guarding during it; starting one ends a guard. Another can start only
# WEAVE_COOLDOWN_SECONDS after it ends.
WEAVE_COST = 35.0
WEAVE_SECONDS = 3.0
WEAVE_COOLDOWN_SECONDS = 4.0
WEAVE_MIN_CONFIDENCE = 0.8    # AI confidence needed; a false weave is expensive
ROUND_SECONDS = 90.0
ROUND_END_SECONDS = 2.0
COUNTDOWN_SECONDS = 3.0
TUTORIAL_COMMANDS = frozenset(("START_TUTORIAL", "EXIT_TUTORIAL", "PRACTICE_PUNCH",
                               "PRACTICE_ITEM"))
COMMANDS = frozenset(("READY", "UNREADY", "CALIBRATED", "PAUSE", "RESUME",
                      "RESTART")) | TUTORIAL_COMMANDS
# Tutorial (CG4002-Viz docs/protocol.md "Tutorial mode"): the bag's punch lands
# this long after PRACTICE_PUNCH, and the bag cycles through these punches.
PRACTICE_WINDUP_SECONDS = 1.5
PRACTICE_PUNCHES = ("JAB", "LEFT_HOOK", "LEFT_UPPERCUT")
# PRACTICE_ITEM spawns an attack boost at a fixed spot 1 m away on the player's
# left (negative bearing = left), clear of the bag straight ahead and of the
# visualizer's lesson card, which floats about 30 degrees to the left.
PRACTICE_ITEM_BEARING = -65.0
# Pickups (CG4002-Viz docs/protocol.md "Player-specific item pickups"). One item
# per player at a time, of either type; lifetimes count fight time only.
HEALTH_ITEM_HEAL = 25.0
HEALTH_ITEM_SECONDS = 30.0     # of fight time: frozen while paused
ITEM_MIN_DISTANCE_M = 1.0
# The protocol-v2 contract allows active_items distance_m 0.5..2.0. A phone
# rejects any MatchState outside it (the whole snapshot, not just the item),
# so its owner freezes as "stale" until the item is gone. Keep this <= 2.0.
ITEM_MAX_DISTANCE_M = 2.0
PRACTICE_ITEM_DISTANCE_M = 1.0
HEALTH_ITEM_MAX_BEARING = 65.0
PICKUP_RADIUS_M = 0.5
# Attack boost (CG4002-Viz docs/attack-boost-pickup-plan.md): collecting it
# multiplies the owner's punch damage (before the block factor) for 30 s of
# fight time. Collecting another while boosted refreshes to 30 s; no stacking.
ATTACK_ITEM_MULTIPLIER = 1.5
ATTACK_ITEM_SECONDS = 30.0     # how long the uncollected item stays
ATTACK_BOOST_SECONDS = 30.0    # how long the boost lasts once collected
# Timed spawns prefer health below this, otherwise alternate types per player.
SPAWN_PREFER_HEALTH_BELOW = 50.0
ITEM_TYPES = ("HEALTH", "ATTACK_MULTIPLIER")


@dataclass
class PickupItem:
    item_id: str
    owner: int
    bearing_degrees: float
    expires_at: float          # in fight seconds, so a pause freezes it
    item_type: str = "HEALTH"
    distance_m: float = ITEM_MIN_DISTANCE_M

    @property
    def magnitude(self):
        return ATTACK_ITEM_MULTIPLIER if self.item_type == "ATTACK_MULTIPLIER" else HEALTH_ITEM_HEAL

    @property
    def effect_duration_ms(self):
        return int(ATTACK_BOOST_SECONDS * 1000) if self.item_type == "ATTACK_MULTIPLIER" else 0


HealthItem = PickupItem        # older name, kept for callers and tests


@dataclass
class Player:
    health: float = 100.0
    stamina: float = 100.0
    busy_until: float = 0.0
    guard_until: float = 0.0
    held_guard: bool = False
    sensor_pair_at: float | None = None
    weave_until: float = 0.0            # clock time; invincible to punches before it
    weave_cooldown_until: float = 0.0   # clock time; no new weave before it
    connected: bool = False
    ready: bool = False   # "done with this phase": READY, CALIBRATED, RESUME or RESTART (Play again)
    boost_until: float = 0.0   # fight seconds; attack boost active while above fight_seconds
    next_item_at: float | None = None  # fight seconds, while this player has no item


class GameEngine:
    """A single-round, two-player authority with an injectable monotonic clock.

    Match flow (CG4002-Viz docs/protocol.md, PlayerCommand rules):
    LOBBY -all READY-> CALIBRATING -all CALIBRATED-> COUNTDOWN -timer-> FIGHTING
    FIGHTING -PAUSE or disconnect-> PAUSED -all RESUME-> COUNTDOWN
    FIGHTING -KO or time-> ROUND_END -2 s-> MATCH_END
    MATCH_END -every connected player RESTART ("Play again"), or nobody left-> LOBBY
    PAUSED -any one player RESTART-> LOBBY
    Tutorial (any server, one player at a time), mode TUTORIAL throughout:
    LOBBY -START_TUTORIAL-> CALIBRATING -CALIBRATED-> FIGHTING (no countdown)
    FIGHTING -PAUSE or disconnect-> PAUSED -RESUME-> FIGHTING
    any tutorial phase -EXIT_TUTORIAL or the tutorial player leaves-> LOBBY, mode MATCH
    The round clock stops, nobody is knocked out (health refills to 100) and
    PRACTICE_PUNCH makes the bag (the other slot) punch back after a windup;
    PRACTICE_ITEM spawns an attack boost for the player to collect.
    "All" means at least required_players connected and every connected
    player ready. Ready flags clear on every phase change. Returning to LOBBY
    is reset_match(): a fresh match on the same stream (match_number + 1).
    """

    def __init__(self, clock=time.monotonic, round_seconds=ROUND_SECONDS,
                 countdown_seconds=COUNTDOWN_SECONDS, required_players=2, seed=4002,
                 god_mode=False):
        if round_seconds <= 0:
            raise ValueError("round_seconds must be positive")
        if countdown_seconds <= 0:
            raise ValueError("countdown_seconds must be positive")
        if required_players not in (1, 2):
            raise ValueError("required_players must be 1 or 2")
        self.clock = clock
        # Server launch setting, retained across match resets; no phone command
        # or new wire-protocol mode is needed. Tutorial keeps its refill rules.
        self.god_mode = bool(god_mode)
        self.players = {1: Player(), 2: Player()}
        self.phase = "LOBBY"
        self.round_seconds = float(round_seconds)
        self.round_time = self.round_seconds
        self.match_number = 1     # +1 on every reset_match()
        self.countdown_seconds = float(countdown_seconds)
        self.required_players = required_players
        self.last_tick = clock()
        self.round_end_at = None
        self.countdown_until = None
        self.fight_epoch = 0      # +1 each time FIGHTING (re)starts
        self.fight_seconds = 0.0  # time spent FIGHTING; item lifetimes use it
        self.items = {}           # owner player -> PickupItem (one each at most)
        self.item_serial = 0
        self.rng = random.Random(seed)
        self.transitions = []
        self.mode = "MATCH"            # or "TUTORIAL"
        self.tutorial_player = None    # who started the tutorial; the bag is 3 - this
        self.practice_due = None       # clock time the pending bag punch lands
        self.practice_serial = 0
        self.practice_results = []     # resolved bag punches for the hub to emit

    def _set_phase(self, phase):
        self.phase = phase
        for player in self.players.values():
            player.ready = False   # ready means "for this phase" only
        if phase in ("ROUND_END", "MATCH_END"):
            self.items.clear()     # nothing to collect once the round is over
            for player in self.players.values():
                player.boost_until = 0.0   # boosts end with the round
        if phase == "FIGHTING":
            self.fight_epoch += 1
        if phase == "COUNTDOWN":
            self.countdown_until = self.clock() + self.countdown_seconds

    def start(self):
        """Legacy/auto-start helper: LOBBY straight to FIGHTING."""
        if self.phase != "LOBBY":
            return False
        self.last_tick = self.clock()
        self._set_phase("FIGHTING")
        return True

    @property
    def tutorial(self):
        return self.mode == "TUTORIAL"

    def pause(self):
        """Operator pause, PAUSE command or a disconnect (FIGHTING or COUNTDOWN)."""
        if self.phase not in ("FIGHTING", "COUNTDOWN"):
            return False
        self.advance()
        if self.phase not in ("FIGHTING", "COUNTDOWN"):
            return False
        self._set_phase("PAUSED")
        self.practice_due = None       # a bag punch never lands across a pause
        for player in self.players.values():
            player.guard_until = 0.0
            player.held_guard = False
            player.busy_until = 0.0
            player.weave_until = 0.0
            player.weave_cooldown_until = 0.0
        return True

    def resume(self):
        """Legacy/auto-start helper: PAUSED straight back to FIGHTING."""
        if self.phase != "PAUSED":
            return False
        self.last_tick = self.clock()
        self._set_phase("FIGHTING")
        return True

    def set_connected(self, player_id, connected):
        """A phone joined or left. Leaving mid-fight pauses; joining never resumes."""
        if player_id not in self.players:
            raise ValueError("invalid player")
        player = self.players[player_id]
        player.connected = bool(connected)
        if connected:
            return
        player.ready = False
        if self.tutorial:
            # Only the player doing the tutorial matters: their leaving ends it
            # (back to LOBBY for everyone); the other phone coming or going
            # never pauses it.
            if player_id == self.tutorial_player:
                self.reset_match()
            return
        self.pause()
        if self.phase == "MATCH_END":
            self._reset_if_everyone_is_done()

    def reset_match(self):
        """Start a fresh match in LOBBY on the same stream.

        Health, stamina, guards, the round timer, fight time and items reset;
        who is connected stays. item_serial and the RNG carry on so item IDs
        never repeat (phones remember retired IDs). fight_epoch moves on, so a
        punch still pending from before can't land.
        """
        for player in self.players.values():
            connected = player.connected
            player.__init__()
            player.connected = connected
        self._set_phase("LOBBY")
        self.round_time = self.round_seconds
        self.round_end_at = None
        self.countdown_until = None
        self.fight_seconds = 0.0
        self.items.clear()
        self.fight_epoch += 1
        self.transitions = []
        self.last_tick = self.clock()
        self.match_number += 1
        self.mode = "MATCH"
        self.tutorial_player = None
        self.practice_due = None
        self.practice_results = []

    def _reset_if_everyone_is_done(self):
        connected = [p for p in self.players.values() if p.connected]
        if all(p.ready for p in connected):     # also true when nobody is left
            self.reset_match()

    def command(self, player_id, command):
        """Apply one PlayerCommand. Returns True when it changed anything."""
        if player_id not in self.players or command not in COMMANDS:
            return False
        self.advance()
        player = self.players[player_id]
        if not player.connected or self.phase == "ROUND_END":
            return False
        if command in TUTORIAL_COMMANDS or self.tutorial:
            return self._tutorial_command(player_id, command)
        if command == "RESTART":
            if self.phase == "PAUSED":            # either player, at once
                self.reset_match()
                return True
            if self.phase != "MATCH_END" or player.ready:
                return False                      # never mid-fight; "Play again" once
            player.ready = True
            self._reset_if_everyone_is_done()
            return True
        if self.phase == "MATCH_END":
            return False
        if command == "PAUSE":
            return self.phase == "FIGHTING" and self.pause()
        accepted = {
            "LOBBY": ("READY", "UNREADY"),
            "CALIBRATING": ("CALIBRATED",),
            "PAUSED": ("RESUME",),
        }.get(self.phase, ())
        if command not in accepted:
            return False
        wanted = command != "UNREADY"
        if player.ready == wanted:
            return False
        player.ready = wanted
        self._progress()
        return True

    def _tutorial_command(self, player_id, command):
        """START_TUTORIAL in LOBBY, or any command while the tutorial runs.

        Any server offers it, one player at a time: the other slot plays the
        bag, and the other phone (if connected) waits in the lobby and can
        start its own tutorial once this one ends. Only the tutorial player's
        commands count while it runs.
        """
        if command == "START_TUTORIAL":
            if self.tutorial or self.phase != "LOBBY":
                return False
            for player in self.players.values():
                connected = player.connected
                player.__init__()
                player.connected = connected
            self.mode = "TUTORIAL"
            self.tutorial_player = player_id
            self.round_time = self.round_seconds
            self.items.clear()
            self._set_phase("CALIBRATING")
            return True
        if not self.tutorial or player_id != self.tutorial_player:
            return False
        if command == "EXIT_TUTORIAL":
            self.reset_match()
            return True
        if command == "PRACTICE_PUNCH":
            if self.phase != "FIGHTING" or self.practice_due is not None:
                return False
            self.practice_due = self.clock() + PRACTICE_WINDUP_SECONDS
            return True
        if command == "PRACTICE_ITEM":
            # The usual one-item rule applies: ignored while one is on the floor.
            return self.spawn_item(player_id, "ATTACK_MULTIPLIER",
                                   PRACTICE_ITEM_BEARING) is not None
        if command == "PAUSE":
            return self.phase == "FIGHTING" and self.pause()
        if (self.phase, command) in (("CALIBRATING", "CALIBRATED"), ("PAUSED", "RESUME")):
            self.last_tick = self.clock()
            self._set_phase("FIGHTING")    # no countdown in the tutorial
            return True
        return False                       # READY, UNREADY, RESTART: not here

    def _apply_damage(self, target, raw_damage):
        """Return actual HP lost; God mode leaves both players at least 1 HP."""
        floor = 1.0 if self.god_mode and not self.tutorial else 0.0
        damage = round(min(max(0.0, target.health - floor), raw_damage), 2)
        target.health = round(max(0.0, target.health - damage), 2)
        if target.health == 0.0:
            if self.tutorial:
                target.health = 100.0
            else:
                self._end_round(self.clock())
        return damage

    def _resolve_practice(self, now):
        """The bag's punch lands: DODGE if the player weaves now, BLOCK if they guard, else HIT."""
        self.practice_due = None
        self.practice_serial += 1
        punch = PRACTICE_PUNCHES[(self.practice_serial - 1) % len(PRACTICE_PUNCHES)]
        target_id = self.tutorial_player
        target = self.players[target_id]
        if target.weave_until > now:
            outcome, damage = "DODGE", 0.0
        else:
            blocked = target.guard_until > now
            factor = BLOCK_DAMAGE_MULTIPLIER if blocked else 1.0
            damage = self._apply_damage(target, BASE_DAMAGE[punch] * factor)
            outcome = "BLOCK" if blocked else "HIT"
        self.practice_results.append({
            "attack_id": f"practice-m{self.match_number}-{self.practice_serial:04d}",
            "source_player": 3 - target_id, "target_player": target_id,
            "punch": punch, "outcome": outcome, "damage": damage,
        })

    def pop_practice_results(self):
        results = self.practice_results
        self.practice_results = []
        return results

    def _progress(self):
        connected = [p for p in self.players.values() if p.connected]
        if len(connected) < self.required_players or not all(p.ready for p in connected):
            return
        if self.phase == "LOBBY":
            self._set_phase("CALIBRATING")
        elif self.phase in ("CALIBRATING", "PAUSED"):
            self._set_phase("COUNTDOWN")

    def match_result(self):
        if self.phase != "MATCH_END":
            return "PENDING"
        one, two = self.players[1].health, self.players[2].health
        return "P1_WIN" if one > two else "P2_WIN" if two > one else "DRAW"

    def phase_remaining_ms(self):
        now = self.clock()
        if self.phase == "COUNTDOWN" and self.countdown_until is not None:
            end = self.countdown_until
        elif self.phase == "ROUND_END" and self.round_end_at is not None:
            end = self.round_end_at
        else:
            return 0
        return max(0, min(600000, math.ceil((end - now) * 1000)))

    def advance(self):
        """Apply elapsed time; return any phase transitions for event emission."""
        now = self.clock()
        elapsed = max(0.0, now - self.last_tick)
        self.last_tick = now
        if self.phase == "COUNTDOWN" and now >= self.countdown_until:
            self._set_phase("FIGHTING")
            elapsed = 0.0   # the fight clock starts now
        if self.phase == "FIGHTING":
            active = (elapsed if self.god_mode and not self.tutorial else
                      min(elapsed, self.round_time))
            started = now - elapsed
            for player in self.players.values():
                weaving = max(0.0, min(now, player.weave_until) - started)
                guarding = (max(0.0, min(started + active, player.guard_until) - started)
                            if player.held_guard else 0.0)
                time_to_empty = player.stamina / HELD_GUARD_COST_PER_SECOND
                drain_time = min(guarding, time_to_empty)
                exhausted = player.held_guard and guarding >= time_to_empty
                # A held guard drains instead of regenerating. If it ends
                # mid-step, regeneration resumes for the remainder.
                recovery_time = max(0.0, active - weaving - drain_time)
                player.stamina = round(min(100.0, player.stamina +
                                           recovery_time * STAMINA_REGEN_PER_SECOND -
                                           drain_time * HELD_GUARD_COST_PER_SECOND), 2)
                if now >= player.guard_until or exhausted:
                    player.guard_until = 0.0
                    player.held_guard = False
                if now >= player.weave_until:
                    player.weave_until = 0.0
            self.fight_seconds += active
            for owner, item in list(self.items.items()):
                if item.expires_at <= self.fight_seconds:
                    del self.items[owner]
            for player in self.players.values():
                if player.boost_until <= self.fight_seconds:
                    player.boost_until = 0.0
            if self.tutorial:
                if self.practice_due is not None and now >= self.practice_due:
                    self._resolve_practice(now)
            elif not self.god_mode:
                self.round_time = max(0.0, self.round_time - elapsed)
                if self.round_time == 0.0:
                    self._end_round(now)
        if self.phase == "ROUND_END" and now >= self.round_end_at:
            self._set_phase("MATCH_END")
            self.transitions.append("MATCH_END")

    def spawn_item(self, player_id, item_type="HEALTH", bearing_degrees=None):
        """Place one pickup for this player (FIGHTING only, one item at a time).

        Spawning is an explicit trigger (operator key or --spawn-seconds); the
        phone places it at the chosen distance and bearing on its own floor.
        """
        if player_id not in self.players:
            raise ValueError("invalid player")
        if item_type not in ITEM_TYPES:
            raise ValueError("invalid item type")
        self.advance()
        if self.phase != "FIGHTING" or player_id in self.items or self._sidelined(player_id):
            return None
        self.item_serial += 1
        attack = item_type == "ATTACK_MULTIPLIER"
        item = PickupItem(
            item_id=f"{'attack' if attack else 'health'}-p{player_id}-{self.item_serial:04d}",
            owner=player_id,
            bearing_degrees=round(bearing_degrees if bearing_degrees is not None else
                                  self.rng.uniform(-HEALTH_ITEM_MAX_BEARING,
                                                   HEALTH_ITEM_MAX_BEARING), 1),
            expires_at=self.fight_seconds + (ATTACK_ITEM_SECONDS if attack else HEALTH_ITEM_SECONDS),
            item_type=item_type,
            distance_m=(PRACTICE_ITEM_DISTANCE_M if self.tutorial else
                        round(self.rng.uniform(ITEM_MIN_DISTANCE_M, ITEM_MAX_DISTANCE_M), 2)),
        )
        self.items[player_id] = item
        self.players[player_id].next_item_at = None
        return item

    def spawn_health(self, player_id):
        return self.spawn_item(player_id, "HEALTH")

    def spawn_attack(self, player_id):
        return self.spawn_item(player_id, "ATTACK_MULTIPLIER")

    def next_spawn_type(self, player_id):
        """Prefer health below 50 HP; otherwise draw a type for this spawn."""
        player = self.players[player_id]
        if player.health < SPAWN_PREFER_HEALTH_BELOW:
            return "HEALTH"
        return self.rng.choice(ITEM_TYPES)

    def spawn_due_items(self, player_ids, seconds):
        """Schedule each player's next item on the fight clock, with ±20% jitter."""
        self.advance()
        if self.phase != "FIGHTING" or self.tutorial:
            return []
        spawned = []
        for player_id in player_ids:
            if player_id in self.items:
                continue
            player = self.players[player_id]
            if player.next_item_at is None:
                player.next_item_at = self.fight_seconds + self.rng.uniform(
                    0.8 * seconds, 1.2 * seconds)
            if self.fight_seconds >= player.next_item_at:
                item = self.spawn_item(player_id, self.next_spawn_type(player_id))
                if item is not None:
                    spawned.append(item)
        return spawned

    def _sidelined(self, player_id):
        """The other player during someone's tutorial: their actions do nothing."""
        return self.tutorial and player_id != self.tutorial_player

    def pickup_target(self, player_id):
        """The item a pickup action would try to collect, or None."""
        self.advance()
        return self.items.get(player_id) if self.phase == "FIGHTING" else None

    def collect_item(self, player_id, item_id, observation, distance_m):
        """Judge one phone observation. Returns (reason, item_type, magnitude).

        Only FIGHTING, the player's own live item, AVAILABLE and <= 0.5 m
        succeed; success removes the item and applies it. HEALTH heals (capped
        at 100, even at full health; magnitude is the HP actually gained).
        ATTACK_MULTIPLIER (re)starts a 30 s boost (magnitude is the multiplier).
        The phone's distance is trusted evidence, not verified.
        """
        self.advance()
        item = self.items.get(player_id)
        item_type = item.item_type if item is not None else "HEALTH"
        if self.phase != "FIGHTING":
            return "MATCH_NOT_ACTIVE", item_type, 0.0
        if item is None or item.item_id != item_id:
            return "ITEM_NOT_FOUND", item_type, 0.0
        if observation != "AVAILABLE":
            return observation, item_type, 0.0   # ITEM_UNAVAILABLE / TRACKING_UNAVAILABLE
        if distance_m > PICKUP_RADIUS_M:
            return "OUT_OF_RANGE", item_type, 0.0
        del self.items[player_id]
        player = self.players[player_id]
        if item.item_type == "ATTACK_MULTIPLIER":
            player.boost_until = self.fight_seconds + ATTACK_BOOST_SECONDS
            return "ACCEPTED", item.item_type, ATTACK_ITEM_MULTIPLIER
        before = player.health
        player.health = round(min(100.0, before + HEALTH_ITEM_HEAL), 2)
        return "ACCEPTED", item.item_type, round(player.health - before, 2)

    def collect_health(self, player_id, item_id, observation, distance_m):
        """Older two-value form of collect_item: (reason, health gained)."""
        reason, item_type, magnitude = self.collect_item(player_id, item_id, observation, distance_m)
        return reason, (magnitude if item_type == "HEALTH" else 0.0)

    def attack_multiplier(self, player_id):
        """Current damage multiplier for this player's punches (1.0 when not boosted)."""
        player = self.players[player_id]
        return ATTACK_ITEM_MULTIPLIER if player.boost_until > self.fight_seconds else 1.0

    def boost_remaining_ms(self, player_id):
        player = self.players[player_id]
        if player.boost_until <= self.fight_seconds:
            return 0
        return max(1, min(120000, math.ceil((player.boost_until - self.fight_seconds) * 1000)))

    def _active_items(self):
        return [{
            "id": item.item_id, "item_type": item.item_type, "owner_player": item.owner,
            "distance_m": item.distance_m, "bearing_degrees": item.bearing_degrees,
            "magnitude": item.magnitude, "effect_duration_ms": item.effect_duration_ms,
            "remaining_ms": max(0, min(120000, math.ceil(
                (item.expires_at - self.fight_seconds) * 1000))),
        } for item in self.items.values()]

    def pop_transitions(self):
        transitions = self.transitions
        self.transitions = []
        return transitions

    def _end_round(self, now):
        if self.phase != "FIGHTING":
            return
        self._set_phase("ROUND_END")
        self.round_end_at = now + ROUND_END_SECONDS
        for player in self.players.values():
            player.guard_until = 0.0
            player.held_guard = False
            player.weave_until = 0.0
            player.weave_cooldown_until = 0.0
        self.transitions.append("ROUND_END")

    def try_attack(self, player_id, punch):
        """Charge stamina once on acceptance, before sending PunchAttempt."""
        if player_id not in self.players or punch not in STAMINA_COST:
            raise ValueError("invalid attack")
        self.advance()
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or self._sidelined(player_id) or now < player.busy_until or
                now < player.guard_until or now < player.weave_until or
                player.stamina < STAMINA_COST[punch]):
            return False
        player.stamina = round(player.stamina - STAMINA_COST[punch], 2)
        player.busy_until = now + ANIMATION_SECONDS[punch]
        return True

    def note_sensor_pair(self, player_id):
        """Renew an AI guard only while paired data continues arriving."""
        player = self.players[player_id]
        now = self.clock()
        player.sensor_pair_at = now
        if player.held_guard and player.guard_until > now:
            player.guard_until = now + HELD_GUARD_SENSOR_TIMEOUT

    def release_held_guard(self, player_id):
        """Clear an AI guard when its postprocessor loses the held pose."""
        player = self.players[player_id]
        if not player.held_guard:
            return False
        self.advance()
        player.held_guard = False
        player.guard_until = 0.0
        return True

    def sensor_stream_lost(self, player_id):
        self.players[player_id].sensor_pair_at = None
        self.release_held_guard(player_id)

    def start_guard(self, player_id, *, held=False):
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or self._sidelined(player_id) or now < player.busy_until or
                now < player.guard_until or now < player.weave_until):
            return False
        deadline = now + GUARD_SECONDS
        if held:
            if player.stamina <= 0 or player.sensor_pair_at is None:
                return False
            deadline = player.sensor_pair_at + HELD_GUARD_SENSOR_TIMEOUT
            if deadline <= now:
                return False
        else:
            if player.stamina < GUARD_COST:
                return False
            player.stamina = round(player.stamina - GUARD_COST, 2)
        player.held_guard = held
        player.guard_until = deadline
        return True

    def start_weave(self, player_id):
        """Charge WEAVE_COST once and make the player invincible to punches for 3 s.

        Accepted only while FIGHTING, not mid-punch, not already weaving or in
        the cooldown, and with enough stamina. Ends an active guard.
        """
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or self._sidelined(player_id) or now < player.busy_until or
                now < player.weave_until or now < player.weave_cooldown_until or
                player.stamina < WEAVE_COST):
            return False
        player.stamina = round(player.stamina - WEAVE_COST, 2)
        player.guard_until = 0.0
        player.held_guard = False
        player.weave_until = now + WEAVE_SECONDS
        player.weave_cooldown_until = player.weave_until + WEAVE_COOLDOWN_SECONDS
        return True

    def weave_remaining_ms(self, player_id):
        """Time left in this player's weave (0 when not weaving or not FIGHTING)."""
        player = self.players[player_id]
        now = self.clock()
        if self.phase != "FIGHTING" or player.weave_until <= now:
            return 0
        return max(1, min(10000, math.ceil((player.weave_until - now) * 1000)))

    def weave_cooldown_ms(self, player_id):
        """Time until this player may weave again; 0 while weaving (contract rule)."""
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or player.weave_until > now or
                player.weave_cooldown_until <= now):
            return 0
        return max(1, min(30000, math.ceil((player.weave_cooldown_until - now) * 1000)))

    def end_guard(self, player_id):
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        player = self.players[player_id]
        if self.phase != "FIGHTING" or player.guard_until <= self.clock():
            return False
        player.guard_until = 0.0
        player.held_guard = False
        return True

    def resolve_punch(self, source_player, punch, intensity, tracked):
        """Use current server guard state; the phone cannot set damage."""
        self.advance()
        target = self.players[3 - source_player]
        if self.phase != "FIGHTING" or not tracked:
            return "MISS", 0.0
        if target.weave_until > self.clock():
            return "DODGE", 0.0        # judged at resolution time, like the guard
        blocked = target.guard_until > self.clock()
        factor = BLOCK_DAMAGE_MULTIPLIER if blocked else 1.0
        # protocol.md: boosted = base * attack_multiplier, then the block factor.
        boosted = BASE_DAMAGE[punch] * intensity * self.attack_multiplier(source_player)
        damage = self._apply_damage(target, boosted * factor)
        return ("BLOCK" if blocked else "HIT"), damage

    def snapshot(self):
        now = self.clock()
        def player_state(player_id):
            player = self.players[player_id]
            return {
                "health": player.health, "stamina": player.stamina,
                "is_blocking": self.phase == "FIGHTING" and player.guard_until > now,
                "attack_multiplier": self.attack_multiplier(player_id),
                "attack_multiplier_remaining_ms": self.boost_remaining_ms(player_id),
                "weave_remaining_ms": self.weave_remaining_ms(player_id),
                "weave_cooldown_ms": self.weave_cooldown_ms(player_id),
                "connected": player.connected,
                "ready": player.ready,
            }
        return {
            "player_1": player_state(1),
            "player_2": player_state(2),
            "round_time": round(self.round_time, 2),
            "state": self.phase,
            "active_items": self._active_items(),
            "phase_remaining_ms": self.phase_remaining_ms(),
            "match_result": self.match_result(),
            "mode": self.mode,
            # Whose tutorial it is, so the other phone shows the lobby instead.
            **({"tutorial_player": self.tutorial_player} if self.tutorial else {}),
        }
