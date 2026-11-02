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
BLOCK_DAMAGE_MULTIPLIER = 0.3
ROUND_SECONDS = 90.0
ROUND_END_SECONDS = 2.0
COUNTDOWN_SECONDS = 3.0
TUTORIAL_COMMANDS = frozenset(("START_TUTORIAL", "EXIT_TUTORIAL", "PRACTICE_PUNCH"))
COMMANDS = frozenset(("READY", "UNREADY", "CALIBRATED", "PAUSE", "RESUME",
                      "RESTART")) | TUTORIAL_COMMANDS
# Tutorial (CG4002-Viz docs/protocol.md "Tutorial mode"): the bag's punch lands
# this long after PRACTICE_PUNCH, and the bag cycles through these punches.
PRACTICE_WINDUP_SECONDS = 1.5
PRACTICE_PUNCHES = ("JAB", "LEFT_HOOK", "LEFT_UPPERCUT")
# Health pickups (docs/protocol.md "Player-specific item pickups").
HEALTH_ITEM_HEAL = 25.0
HEALTH_ITEM_SECONDS = 30.0     # of fight time: frozen while paused
HEALTH_ITEM_DISTANCE_M = 1.0
HEALTH_ITEM_MAX_BEARING = 65.0
PICKUP_RADIUS_M = 0.5


@dataclass
class HealthItem:
    item_id: str
    owner: int
    bearing_degrees: float
    expires_at: float          # in fight seconds, so a pause freezes it


@dataclass
class Player:
    health: float = 100.0
    stamina: float = 100.0
    busy_until: float = 0.0
    guard_until: float = 0.0
    connected: bool = False
    ready: bool = False   # "done with this phase": READY, CALIBRATED, RESUME or RESTART (Play again)


class GameEngine:
    """A single-round, two-player authority with an injectable monotonic clock.

    Match flow (CG4002-Viz docs/protocol.md, PlayerCommand rules):
    LOBBY -all READY-> CALIBRATING -all CALIBRATED-> COUNTDOWN -timer-> FIGHTING
    FIGHTING -PAUSE or disconnect-> PAUSED -all RESUME-> COUNTDOWN
    FIGHTING -KO or time-> ROUND_END -2 s-> MATCH_END
    MATCH_END -every connected player RESTART ("Play again"), or nobody left-> LOBBY
    PAUSED -any one player RESTART-> LOBBY
    Tutorial (single-player server only), mode TUTORIAL throughout:
    LOBBY -START_TUTORIAL-> CALIBRATING -CALIBRATED-> FIGHTING (no countdown)
    FIGHTING -PAUSE or disconnect-> PAUSED -RESUME-> FIGHTING
    any tutorial phase -EXIT_TUTORIAL or nobody left-> LOBBY, mode MATCH
    The round clock stops, nobody is knocked out (health refills to 100) and
    PRACTICE_PUNCH makes the bag (the other slot) punch back after a windup.
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
        self.items = {}           # owner player -> HealthItem (one each at most)
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
            player.busy_until = 0.0
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
        self.pause()
        if self.phase == "MATCH_END":
            self._reset_if_everyone_is_done()
        elif self.tutorial and not any(p.connected for p in self.players.values()):
            self.reset_match()         # nobody left to teach

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
        """START_TUTORIAL in LOBBY, or any command while the tutorial runs."""
        if command == "START_TUTORIAL":
            if self.tutorial or self.phase != "LOBBY" or self.required_players != 1:
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
        """The bag's punch lands: BLOCK if the player guards now, else HIT."""
        self.practice_due = None
        self.practice_serial += 1
        punch = PRACTICE_PUNCHES[(self.practice_serial - 1) % len(PRACTICE_PUNCHES)]
        target_id = self.tutorial_player
        target = self.players[target_id]
        blocked = target.guard_until > now
        factor = BLOCK_DAMAGE_MULTIPLIER if blocked else 1.0
        damage = self._apply_damage(target, BASE_DAMAGE[punch] * factor)
        self.practice_results.append({
            "attack_id": f"practice-m{self.match_number}-{self.practice_serial:04d}",
            "source_player": 3 - target_id, "target_player": target_id,
            "punch": punch, "outcome": "BLOCK" if blocked else "HIT", "damage": damage,
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
            for player in self.players.values():
                player.stamina = round(min(100.0, player.stamina +
                                           active * STAMINA_REGEN_PER_SECOND), 2)
                if now >= player.guard_until:
                    player.guard_until = 0.0
            self.fight_seconds += active
            for owner, item in list(self.items.items()):
                if item.expires_at <= self.fight_seconds:
                    del self.items[owner]
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

    def spawn_health(self, player_id):
        """Place one health pack for this player (FIGHTING only, one at a time).

        Spawning is an explicit trigger (operator key or --spawn-seconds); the
        phone places it 1 m away at the given bearing on its own floor.
        """
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        if self.phase != "FIGHTING" or player_id in self.items:
            return None
        self.item_serial += 1
        item = HealthItem(
            item_id=f"health-p{player_id}-{self.item_serial:04d}",
            owner=player_id,
            bearing_degrees=round(self.rng.uniform(-HEALTH_ITEM_MAX_BEARING,
                                                   HEALTH_ITEM_MAX_BEARING), 1),
            expires_at=self.fight_seconds + HEALTH_ITEM_SECONDS,
        )
        self.items[player_id] = item
        return item

    def pickup_target(self, player_id):
        """The item a pickup action would try to collect, or None."""
        self.advance()
        return self.items.get(player_id) if self.phase == "FIGHTING" else None

    def collect_health(self, player_id, item_id, observation, distance_m):
        """Judge one phone observation. Returns (reason, health gained).

        Only FIGHTING, the player's own live item, AVAILABLE and <= 0.5 m
        succeed; success removes the item and heals (capped at 100), even at
        full health. The phone's distance is trusted evidence, not verified.
        """
        self.advance()
        item = self.items.get(player_id)
        if self.phase != "FIGHTING":
            return "MATCH_NOT_ACTIVE", 0.0
        if item is None or item.item_id != item_id:
            return "ITEM_NOT_FOUND", 0.0
        if observation != "AVAILABLE":
            return observation, 0.0      # ITEM_UNAVAILABLE / TRACKING_UNAVAILABLE
        if distance_m > PICKUP_RADIUS_M:
            return "OUT_OF_RANGE", 0.0
        del self.items[player_id]
        player = self.players[player_id]
        before = player.health
        player.health = round(min(100.0, before + HEALTH_ITEM_HEAL), 2)
        return "ACCEPTED", round(player.health - before, 2)

    def _active_items(self):
        return [{
            "id": item.item_id, "item_type": "HEALTH", "owner_player": item.owner,
            "distance_m": HEALTH_ITEM_DISTANCE_M, "bearing_degrees": item.bearing_degrees,
            "magnitude": HEALTH_ITEM_HEAL, "effect_duration_ms": 0,
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
        self.transitions.append("ROUND_END")

    def try_attack(self, player_id, punch):
        """Charge stamina once on acceptance, before sending PunchAttempt."""
        if player_id not in self.players or punch not in STAMINA_COST:
            raise ValueError("invalid attack")
        self.advance()
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or now < player.busy_until or
                now < player.guard_until or player.stamina < STAMINA_COST[punch]):
            return False
        player.stamina = round(player.stamina - STAMINA_COST[punch], 2)
        player.busy_until = now + ANIMATION_SECONDS[punch]
        return True

    def start_guard(self, player_id):
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        player = self.players[player_id]
        now = self.clock()
        if (self.phase != "FIGHTING" or now < player.busy_until or
                now < player.guard_until or player.stamina < GUARD_COST):
            return False
        player.stamina = round(player.stamina - GUARD_COST, 2)
        player.guard_until = now + GUARD_SECONDS
        return True

    def end_guard(self, player_id):
        if player_id not in self.players:
            raise ValueError("invalid player")
        self.advance()
        player = self.players[player_id]
        if self.phase != "FIGHTING" or player.guard_until <= self.clock():
            return False
        player.guard_until = 0.0
        return True

    def resolve_punch(self, source_player, punch, intensity, tracked):
        """Use current server guard state; the phone cannot set damage."""
        self.advance()
        target = self.players[3 - source_player]
        if self.phase != "FIGHTING" or not tracked:
            return "MISS", 0.0
        blocked = target.guard_until > self.clock()
        factor = BLOCK_DAMAGE_MULTIPLIER if blocked else 1.0
        damage = self._apply_damage(target, BASE_DAMAGE[punch] * intensity * factor)
        return ("BLOCK" if blocked else "HIT"), damage

    def snapshot(self):
        now = self.clock()
        def player_state(player):
            return {
                "health": player.health, "stamina": player.stamina,
                "is_blocking": self.phase == "FIGHTING" and player.guard_until > now,
                "attack_multiplier": 1.0,
                "attack_multiplier_remaining_ms": 0,
                "connected": player.connected,
                "ready": player.ready,
            }
        return {
            "player_1": player_state(self.players[1]),
            "player_2": player_state(self.players[2]),
            "round_time": round(self.round_time, 2),
            "state": self.phase,
            "active_items": self._active_items(),
            "phase_remaining_ms": self.phase_remaining_ms(),
            "match_result": self.match_result(),
            "mode": self.mode,
        }
