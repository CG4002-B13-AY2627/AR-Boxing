"""Deterministic game-rule tests; no FPGA or wall-clock sleeps."""

import json
import os
from pathlib import Path
import unittest

from game_engine import (
    ANIMATION_SECONDS, BASE_DAMAGE, BLOCK_DAMAGE_MULTIPLIER, GameEngine,
    GUARD_COST, GUARD_SECONDS, HELD_GUARD_COST_PER_SECOND, HELD_GUARD_SENSOR_TIMEOUT, STAMINA_COST,
    STAMINA_REGEN_PER_SECOND,
)
from visualizer_protocol import PhoneHub


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class GameEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.game = GameEngine(clock=self.clock)

    def test_ai_guard_holds_with_sensor_data_until_release(self):
        self.game.start()
        self.game.note_sensor_pair(1)
        self.assertTrue(self.game.start_guard(1, held=True))
        self.assertEqual(self.game.players[1].stamina, 100)
        for _ in range(20):
            self.clock.advance(0.25)
            self.game.note_sensor_pair(1)
        self.assertTrue(self.game.snapshot()["player_1"]["is_blocking"])
        self.assertEqual(self.game.resolve_punch(2, "JAB", 1.0, True)[0], "BLOCK")
        self.assertEqual(self.game.players[1].stamina, 100 - 5 * HELD_GUARD_COST_PER_SECOND)
        self.assertFalse(self.game.try_attack(1, "JAB"))
        self.assertTrue(self.game.end_guard(1))
        self.assertTrue(self.game.try_attack(1, "JAB"))

    def test_ai_guard_exhaustion_releases_and_recovers_without_rearming(self):
        self.game.start()
        player = self.game.players[2]
        self.game.note_sensor_pair(2)
        player.stamina = 0
        self.assertFalse(self.game.start_guard(2, held=True))
        player.stamina = HELD_GUARD_COST_PER_SECOND / 2
        self.assertTrue(self.game.start_guard(2, held=True))
        self.clock.advance(0.25)
        self.game.note_sensor_pair(2)
        self.assertEqual(self.game.resolve_punch(1, "JAB", 1.0, True)[0], "BLOCK")
        self.assertEqual(player.stamina, HELD_GUARD_COST_PER_SECOND / 4)
        self.clock.advance(0.25)
        self.game.note_sensor_pair(2)
        self.assertEqual(self.game.resolve_punch(1, "JAB", 1.0, True)[0], "HIT")
        self.assertEqual(player.stamina, 0)
        self.clock.advance(0.25)
        self.game.note_sensor_pair(2)
        self.game.advance()
        self.assertEqual(player.stamina, STAMINA_REGEN_PER_SECOND / 4)
        self.assertFalse(self.game.snapshot()["player_2"]["is_blocking"])

    def test_disconnect_charges_guard_only_until_disconnect(self):
        self.game.start()
        self.game.note_sensor_pair(1)
        self.assertTrue(self.game.start_guard(1, held=True))
        self.clock.advance(0.5)
        self.game.sensor_stream_lost(1)
        self.assertEqual(self.game.players[1].stamina, 100 - HELD_GUARD_COST_PER_SECOND / 2)
        self.clock.advance(0.25)
        self.game.advance()
        self.assertEqual(self.game.players[1].stamina,
                         100 - HELD_GUARD_COST_PER_SECOND / 2 + STAMINA_REGEN_PER_SECOND / 4)

    def test_ai_guard_clears_on_stream_loss_and_does_not_revive_with_samples(self):
        for disconnect in (False, True):
            with self.subTest(disconnect=disconnect):
                self.game = GameEngine(clock=self.clock)
                self.game.start()
                self.assertFalse(self.game.start_guard(2, held=True))
                self.game.note_sensor_pair(2)
                self.assertTrue(self.game.start_guard(2, held=True))
                if disconnect:
                    self.game.sensor_stream_lost(2)
                else:
                    self.clock.advance(HELD_GUARD_SENSOR_TIMEOUT)
                self.assertFalse(self.game.snapshot()["player_2"]["is_blocking"])
                self.game.note_sensor_pair(2)
                self.assertFalse(self.game.snapshot()["player_2"]["is_blocking"])
                self.assertTrue(self.game.start_guard(2, held=True))

    def test_keyboard_guard_still_expires_even_with_sensor_data(self):
        self.game.start()
        self.assertTrue(self.game.start_guard(1))
        for _ in range(4):
            self.clock.advance(GUARD_SECONDS / 4)
            self.game.note_sensor_pair(1)
        self.assertFalse(self.game.snapshot()["player_1"]["is_blocking"])

    def test_lobby_start_pause_resume_timer_and_round_end(self):
        self.assertEqual(self.game.snapshot()["state"], "LOBBY")
        self.assertFalse(self.game.try_attack(1, "JAB"))
        self.assertTrue(self.game.start())
        self.clock.advance(10)
        self.game.advance()
        self.assertEqual(self.game.snapshot()["round_time"], 80.0)
        self.assertTrue(self.game.pause())
        self.clock.advance(30)
        self.game.advance()
        self.assertEqual(self.game.snapshot()["round_time"], 80.0)
        self.assertFalse(self.game.try_attack(1, "JAB"))
        self.assertTrue(self.game.resume())
        self.clock.advance(80)
        self.game.advance()
        self.assertEqual(self.game.pop_transitions(), ["ROUND_END"])
        self.assertEqual(self.game.snapshot()["round_time"], 0.0)
        self.assertFalse(self.game.try_attack(1, "JAB"))
        self.clock.advance(2)
        self.game.advance()
        self.assertEqual(self.game.pop_transitions(), ["MATCH_END"])
        self.assertEqual(self.game.snapshot()["state"], "MATCH_END")

    def test_attack_costs_damage_order_animation_lock_and_regeneration(self):
        self.game.start()
        for punch in ("JAB", "CROSS", "LEFT_HOOK", "LEFT_UPPERCUT"):
            self.assertTrue(self.game.try_attack(1, punch))
            self.assertFalse(self.game.try_attack(1, punch))
            self.assertEqual(self.game.players[1].busy_until,
                             self.clock.now + ANIMATION_SECONDS[punch])
            self.clock.advance(ANIMATION_SECONDS[punch])
            self.game.advance()
        self.assertEqual([BASE_DAMAGE[p] for p in
                          ("JAB", "CROSS", "LEFT_HOOK", "LEFT_UPPERCUT")],
                         [5, 7, 10, 15])
        self.assertEqual([STAMINA_COST[p] for p in
                          ("JAB", "CROSS", "LEFT_HOOK", "LEFT_UPPERCUT")],
                         [8, 10, 15, 22])
        expected = 100 - sum((8, 10, 15, 22)) + sum((0.5, 0.5, 0.7, 1.0)) * 12
        self.assertEqual(self.game.players[1].stamina, round(expected, 2))
        self.game.players[1].stamina = 1.0
        self.assertFalse(self.game.try_attack(1, "JAB"))
        self.clock.advance(1)
        self.game.advance()
        self.assertEqual(self.game.players[1].stamina,
                         1.0 + STAMINA_REGEN_PER_SECOND)
        self.assertTrue(self.game.try_attack(1, "JAB"))

    def test_guard_fixed_window_reduced_damage_and_early_end(self):
        self.game.start()
        self.assertTrue(self.game.start_guard(2))
        self.assertEqual(self.game.players[2].stamina, 100 - GUARD_COST)
        self.assertFalse(self.game.start_guard(2))  # no duration extension
        self.assertFalse(self.game.try_attack(2, "JAB"))
        outcome, damage = self.game.resolve_punch(1, "JAB", 1.0, True)
        self.assertEqual((outcome, damage),
                         ("BLOCK", 5 * BLOCK_DAMAGE_MULTIPLIER))
        self.assertEqual(self.game.players[2].health, 98.5)
        self.clock.advance(GUARD_SECONDS)
        self.game.advance()
        self.assertFalse(self.game.snapshot()["player_2"]["is_blocking"])
        outcome, damage = self.game.resolve_punch(1, "JAB", 1.0, True)
        self.assertEqual((outcome, damage), ("HIT", 5.0))
        self.assertTrue(self.game.start_guard(2))
        self.assertTrue(self.game.end_guard(2))
        self.assertFalse(self.game.end_guard(2))
        self.assertEqual(self.game.resolve_punch(1, "JAB", 1.0, True)[0], "HIT")

    def test_miss_no_damage_and_knockout_clamps_health(self):
        self.game.start()
        self.assertEqual(self.game.resolve_punch(1, "LEFT_UPPERCUT", 1.0, False),
                         ("MISS", 0.0))
        self.assertEqual(self.game.players[2].health, 100.0)
        self.game.players[2].health = 4.0
        self.assertEqual(self.game.resolve_punch(1, "LEFT_UPPERCUT", 1.0, True),
                         ("HIT", 4.0))
        self.assertEqual(self.game.players[2].health, 0.0)
        self.assertEqual(self.game.pop_transitions(), ["ROUND_END"])
        self.assertEqual(self.game.snapshot()["state"], "ROUND_END")

    def test_actual_damage_increases_from_jab_to_hook_to_uppercut(self):
        for punch, expected in (("JAB", 5.0), ("LEFT_HOOK", 10.0),
                                ("RIGHT_UPPERCUT", 15.0)):
            game = GameEngine(clock=self.clock)
            game.start()
            self.assertEqual(game.resolve_punch(1, punch, 1.0, True),
                             ("HIT", expected))
            self.assertEqual(game.players[2].health, 100.0 - expected)


class CapturingSocket:
    def __init__(self):
        self.messages = []

    async def send(self, payload):
        self.messages.append(json.loads(payload))


class GameEngineTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_guard_release_is_applied_before_the_following_punch(self):
        import asyncio
        from ai_to_visualizer_demo import DEFAULT_ACTION_MAP, FakeAiEvent, send_ai_demo

        clock = FakeClock()
        engine = GameEngine(clock=clock)
        engine.start()
        engine.note_sensor_pair(1)
        hub = PhoneHub(engine=engine)
        start = FakeAiEvent("block", 0.0, 0.9, 0.0, "start")
        self.assertIsNotNone(await send_ai_demo(
            hub, 0, start, DEFAULT_ACTION_MAP, 1.0, attack_id="hold", held_guard=True))
        end = FakeAiEvent("block", 0.25, 0.9, 0.0, "end")
        punch = FakeAiEvent("l_straight", 0.25, 0.9, 1.0, None)
        release, attack = await asyncio.gather(
            send_ai_demo(hub, 0, end, DEFAULT_ACTION_MAP, 1.0, 100, "release", held_guard=True),
            send_ai_demo(hub, 0, punch, DEFAULT_ACTION_MAP, 1.0, 100, "punch", held_guard=True),
        )
        self.assertIsNotNone(release)
        self.assertEqual(attack["punch"], "JAB")
        self.assertFalse(engine.snapshot()["player_1"]["is_blocking"])

    async def test_guard_and_round_transitions_match_phone_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        default = Path(__file__).resolve().parents[3] / "CG4002-Viz" / "contracts"
        contracts = Path(os.environ.get("CG4002_CONTRACTS_DIR", default))
        if not contracts.is_dir():
            self.skipTest("CG4002-Viz contracts checkout is unavailable")
        schemas = {
            name: Draft202012Validator(json.loads(
                (contracts / f"{name}.schema.json").read_text(encoding="utf8")))
            for name in ("game-event", "match-state")
        }
        clock = FakeClock()
        engine = GameEngine(clock=clock, round_seconds=1)
        engine.start()
        hub = PhoneHub(engine=engine)
        one, two = CapturingSocket(), CapturingSocket()
        hub.ready = {1: one, 2: two}
        guard = await hub.request_guard(2, guard_id="guard-p2-1")
        self.assertEqual(guard, one.messages[0])
        self.assertEqual(one.messages, two.messages)
        self.assertTrue(one.messages[-1]["player_2"]["is_blocking"])
        self.assertEqual(await hub.request_guard(2, guard_id="guard-p2-1"), guard)
        self.assertEqual(len(one.messages), 2)
        with self.assertRaises(ValueError):
            await hub.request_guard(1, guard_id="guard-p2-1")
        ended = await hub.request_guard(2, active=False, guard_id="guard-p2-end")
        self.assertEqual(ended, one.messages[-2])
        self.assertFalse(one.messages[-1]["player_2"]["is_blocking"])
        self.assertEqual(await hub.request_guard(
            2, active=False, guard_id="guard-p2-end"), ended)
        self.assertEqual(len(one.messages), 4)
        clock.advance(1)
        await hub.broadcast_state()
        self.assertEqual(one.messages[-2]["event"], "ROUND_TRANSITION")
        self.assertEqual(one.messages[-1]["state"], "ROUND_END")
        clock.advance(2)
        await hub.broadcast_state()
        self.assertEqual(one.messages[-2]["event"], "ROUND_TRANSITION")
        self.assertEqual(one.messages[-1]["state"], "MATCH_END")
        self.assertEqual(one.messages, two.messages)
        for message in one.messages:
            name = "game-event" if message["type"] == "GameEvent" else "match-state"
            schemas[name].validate(message)

    async def test_rejected_attack_id_stays_rejected_after_cooldown(self):
        clock = FakeClock()
        engine = GameEngine(clock=clock)
        engine.start()
        hub = PhoneHub(engine=engine)
        self.assertTrue(engine.try_attack(1, "JAB"))
        before = engine.players[1].stamina
        args = (1, "JAB", 0.9, 1.0)
        self.assertIsNone(await hub.request_punch(
            *args, attack_id="busy-attack-1"))
        self.assertEqual(engine.players[1].stamina, before)
        clock.advance(1)
        self.assertIsNone(await hub.request_punch(
            *args, attack_id="busy-attack-1"))
        self.assertEqual(engine.players[1].stamina, before)
        self.assertNotIn("busy-attack-1", hub.attacks)


if __name__ == "__main__":
    unittest.main()
