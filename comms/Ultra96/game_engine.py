"""Deterministic CPU authority. No networking, Unity, or FPGA dependencies."""
from dataclasses import dataclass
import math
import random
import time
import uuid

BASE_DAMAGE = dict(JAB=5.0, CROSS=7.0, LEFT_HOOK=10.0, RIGHT_HOOK=10.0,
                   LEFT_UPPERCUT=15.0, RIGHT_UPPERCUT=15.0)
STAMINA_COST = dict(JAB=8.0, CROSS=10.0, LEFT_HOOK=15.0, RIGHT_HOOK=15.0,
                    LEFT_UPPERCUT=22.0, RIGHT_UPPERCUT=22.0)
ANIMATION_SECONDS = dict(JAB=.5, CROSS=.5, LEFT_HOOK=.7, RIGHT_HOOK=.7,
                         LEFT_UPPERCUT=1.0, RIGHT_UPPERCUT=1.0)
STAMINA_REGEN_PER_SECOND = 12.0
GUARD_COST, GUARD_SECONDS, BLOCK_DAMAGE_MULTIPLIER = 8.0, 1.0, .3
ROUND_SECONDS, ROUND_END_SECONDS = 90.0, 2.0


@dataclass
class Player:
    health: float = 100.0
    stamina: float = 100.0
    busy_until: float = 0.0
    guard_until: float = 0.0
    connected: bool = False
    ready: bool = False


class GameEngine:
    def __init__(self, clock=time.monotonic, round_seconds=ROUND_SECONDS,
                 required_players=2, countdown_seconds=3.0, spawn_seconds=30.0,
                 item_lifetime=30.0, seed=None):
        if (required_players not in (1, 2) or
                any(not math.isfinite(v) or v <= 0 for v in
                    (round_seconds, countdown_seconds, spawn_seconds, item_lifetime)) or
                countdown_seconds > 600 or item_lifetime > 120):
            raise ValueError("invalid match configuration")
        self.clock = clock
        self.required_players = required_players
        self.countdown_seconds, self.spawn_seconds = countdown_seconds, spawn_seconds
        self.item_lifetime = item_lifetime
        self.rng = random.Random(seed)
        self.players = {1: Player(), 2: Player()}
        self.phase, self.round_time = "LOBBY", float(round_seconds)
        self.last_tick = clock()
        self.phase_until = None
        self.fight_time, self.next_spawn = 0.0, spawn_seconds
        self.fight_epoch = 0
        self.items = {}
        self.transitions = []

    def _phase(self, phase, at, announce=True):
        self.phase = phase
        self.phase_until = (at + self.countdown_seconds if phase == "COUNTDOWN" else
                            at + ROUND_END_SECONDS if phase == "ROUND_END" else None)
        for player in self.players.values():
            player.ready = False
            if phase != "FIGHTING":
                player.guard_until = player.busy_until = 0.0
        if phase == "FIGHTING":
            self.fight_epoch += 1
        if phase in ("ROUND_END", "MATCH_END"):
            self.items.clear()
        if announce:
            self.transitions.append(phase)

    def start(self):
        """Explicit test start; normal joins always use commands."""
        if self.phase != "LOBBY":
            return False
        self.last_tick = self.clock()
        self._phase("FIGHTING", self.last_tick, announce=False)
        return True

    def pause(self):
        self.advance()
        if self.phase not in ("FIGHTING", "COUNTDOWN"):
            return False
        self._phase("PAUSED", self.clock(), announce=False)
        return True

    def resume(self):
        """Explicit test helper. Phone RESUME always enters COUNTDOWN."""
        if self.phase != "PAUSED":
            return False
        self.last_tick = self.clock()
        self._phase("FIGHTING", self.last_tick, announce=False)
        return True

    def set_connected(self, player_id, connected):
        self.advance()
        player = self.players[player_id]
        player.connected = connected
        if not connected:
            player.ready = False
            if self.phase in ("FIGHTING", "COUNTDOWN"):
                self._phase("PAUSED", self.clock())

    def command(self, player_id, command):
        self.advance()
        player = self.players[player_id]
        if not player.connected:
            return False
        expected = {"LOBBY": ("READY", "UNREADY"),
                    "CALIBRATING": ("CALIBRATED",), "PAUSED": ("RESUME",)}
        if command == "PAUSE" and self.phase == "FIGHTING":
            self._phase("PAUSED", self.clock())
            return True
        if command not in expected.get(self.phase, ()):
            return False
        player.ready = command != "UNREADY"
        connected = [p for p in self.players.values() if p.connected]
        if len(connected) >= self.required_players and all(p.ready for p in connected):
            self._phase("CALIBRATING" if self.phase == "LOBBY" else "COUNTDOWN", self.clock())
        return True

    def advance(self):
        now, previous = self.clock(), self.last_tick
        self.last_tick = now
        if self.phase == "COUNTDOWN" and now >= self.phase_until:
            previous = self.phase_until
            self._phase("FIGHTING", previous)
        if self.phase == "FIGHTING":
            elapsed = max(0.0, now - previous)
            active = min(elapsed, self.round_time)
            self.fight_time += active
            for player in self.players.values():
                player.stamina = round(min(100.0, player.stamina + active * STAMINA_REGEN_PER_SECOND), 10)
                if now >= player.guard_until:
                    player.guard_until = 0.0
            self.round_time = max(0.0, self.round_time - elapsed)
            self.items = {p: item for p, item in self.items.items() if item[1] > self.fight_time}
            if self.round_time == 0:
                self._phase("ROUND_END", previous + active)
            elif self.fight_time >= self.next_spawn:
                # One current batch, never replay a backlog of missed boundaries.
                self.next_spawn = (math.floor(self.fight_time / self.spawn_seconds) + 1) * self.spawn_seconds
                for owner in (1, 2):
                    self.spawn_health(owner)
        if self.phase == "ROUND_END" and now >= self.phase_until:
            self._phase("MATCH_END", self.phase_until)

    def pop_transitions(self):
        result, self.transitions = self.transitions, []
        return result

    def try_attack(self, player_id, punch):
        if player_id not in self.players or punch not in STAMINA_COST:
            raise ValueError("invalid attack")
        self.advance()
        player, now = self.players[player_id], self.clock()
        if (self.phase != "FIGHTING" or now < player.busy_until or
                now < player.guard_until or player.stamina < STAMINA_COST[punch]):
            return False
        player.stamina -= STAMINA_COST[punch]
        player.busy_until = now + ANIMATION_SECONDS[punch]
        return True

    def start_guard(self, player_id):
        self.advance()
        player, now = self.players[player_id], self.clock()
        if (self.phase != "FIGHTING" or now < player.busy_until or
                now < player.guard_until or player.stamina < GUARD_COST):
            return False
        player.stamina -= GUARD_COST
        player.guard_until = now + GUARD_SECONDS
        return True

    def end_guard(self, player_id):
        self.advance()
        player = self.players[player_id]
        if self.phase != "FIGHTING" or player.guard_until <= self.clock():
            return False
        player.guard_until = 0.0
        return True

    def resolve_punch(self, source_player, punch, intensity, tracked):
        self.advance()
        target = self.players[3 - source_player]
        if self.phase != "FIGHTING" or not tracked:
            return "MISS", 0.0
        blocked = target.guard_until > self.clock()
        damage = round(min(target.health, BASE_DAMAGE[punch] * intensity *
                           (BLOCK_DAMAGE_MULTIPLIER if blocked else 1.0)), 2)
        target.health = round(max(0.0, target.health - damage), 2)
        if target.health == 0:
            self._phase("ROUND_END", self.clock())
        return ("BLOCK" if blocked else "HIT"), damage

    def spawn_health(self, player_id):
        """Operator diagnostic and automatic schedule share this rule."""
        if self.phase != "FIGHTING" or player_id not in self.players or player_id in self.items:
            return False
        self.items[player_id] = (dict(id="health-" + uuid.uuid4().hex,
            item_type="HEALTH", owner_player=player_id, distance_m=1.0,
            bearing_degrees=self.rng.uniform(-65, 65), magnitude=25.0,
            effect_duration_ms=0), self.fight_time + self.item_lifetime)
        return True

    def collect_health(self, player_id, item_id, distance):
        self.advance()
        if self.phase != "FIGHTING":
            return "MATCH_NOT_ACTIVE", 0.0
        item = self.items.get(player_id)
        if item is None or item[0]["id"] != item_id:
            return "ITEM_NOT_FOUND", 0.0
        if not math.isfinite(distance) or distance < 0:
            return "INVALID_REQUEST", 0.0
        if distance > .5:
            return "OUT_OF_RANGE", 0.0
        previous = self.players[player_id].health
        self.players[player_id].health = min(100.0, previous + item[0]["magnitude"])
        del self.items[player_id]
        return "ACCEPTED", self.players[player_id].health - previous

    def snapshot(self):
        def player_state(player):
            return dict(health=player.health, stamina=round(player.stamina, 2),
                is_blocking=self.phase == "FIGHTING" and player.guard_until > self.clock(),
                attack_multiplier=1.0, attack_multiplier_remaining_ms=0,
                connected=player.connected, ready=player.ready)
        result = "PENDING"
        if self.phase == "MATCH_END":
            one, two = self.players[1].health, self.players[2].health
            result = "DRAW" if one == two else "P1_WIN" if one > two else "P2_WIN"
        return dict(player_1=player_state(self.players[1]), player_2=player_state(self.players[2]),
            round_time=round(self.round_time, 2), state=self.phase, match_result=result,
            phase_remaining_ms=max(0, math.ceil((self.phase_until - self.clock()) * 1000))
                if self.phase_until is not None else 0,
            active_items=[dict(payload, remaining_ms=max(0, math.ceil((expiry-self.fight_time)*1000)))
                          for payload, expiry in self.items.values()])
