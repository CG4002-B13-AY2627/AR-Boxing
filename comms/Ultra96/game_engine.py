"""Deterministic Ultra96 match rules, independent of WebSocket transport.

Only server-originated classified actions call these methods. Phone messages
provide target observations, never authoritative damage or guard decisions.
"""

from dataclasses import dataclass
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


@dataclass
class Player:
    health: float = 100.0
    stamina: float = 100.0
    busy_until: float = 0.0
    guard_until: float = 0.0


class GameEngine:
    """A single-round, two-player authority with an injectable monotonic clock."""

    def __init__(self, clock=time.monotonic, round_seconds=ROUND_SECONDS):
        if round_seconds <= 0:
            raise ValueError("round_seconds must be positive")
        self.clock = clock
        self.players = {1: Player(), 2: Player()}
        self.phase = "LOBBY"
        self.round_time = float(round_seconds)
        self.last_tick = clock()
        self.round_end_at = None
        self.transitions = []

    def start(self):
        if self.phase != "LOBBY":
            return False
        self.last_tick = self.clock()
        self.phase = "FIGHTING"
        return True

    def pause(self):
        if self.phase != "FIGHTING":
            return False
        self.advance()
        if self.phase != "FIGHTING":
            return False
        self.phase = "PAUSED"
        for player in self.players.values():
            player.guard_until = 0.0
            player.busy_until = 0.0
        return True

    def resume(self):
        if self.phase != "PAUSED":
            return False
        self.last_tick = self.clock()
        self.phase = "FIGHTING"
        return True

    def advance(self):
        """Apply elapsed time; return any phase transitions for event emission."""
        now = self.clock()
        elapsed = max(0.0, now - self.last_tick)
        self.last_tick = now
        if self.phase == "FIGHTING":
            active = min(elapsed, self.round_time)
            for player in self.players.values():
                player.stamina = round(min(100.0, player.stamina +
                                           active * STAMINA_REGEN_PER_SECOND), 2)
                if now >= player.guard_until:
                    player.guard_until = 0.0
            self.round_time = max(0.0, self.round_time - elapsed)
            if self.round_time == 0.0:
                self._end_round(now)
        if self.phase == "ROUND_END" and now >= self.round_end_at:
            self.phase = "MATCH_END"
            self.transitions.append("MATCH_END")

    def pop_transitions(self):
        transitions = self.transitions
        self.transitions = []
        return transitions

    def _end_round(self, now):
        if self.phase != "FIGHTING":
            return
        self.phase = "ROUND_END"
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
        damage = round(min(target.health, BASE_DAMAGE[punch] * intensity * factor), 2)
        target.health = round(max(0.0, target.health - damage), 2)
        if target.health == 0.0:
            self._end_round(self.clock())
        return ("BLOCK" if blocked else "HIT"), damage

    def snapshot(self):
        now = self.clock()
        def player_state(player):
            return {
                "health": player.health, "stamina": player.stamina,
                "is_blocking": self.phase == "FIGHTING" and player.guard_until > now,
                "attack_multiplier": 1.0,
                "attack_multiplier_remaining_ms": 0,
            }
        return {
            "player_1": player_state(self.players[1]),
            "player_2": player_state(self.players[2]),
            "round_time": round(self.round_time, 2),
            "state": self.phase,
            "active_items": [],
        }
