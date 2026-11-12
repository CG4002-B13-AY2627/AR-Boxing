"""Weave: 3 s of invincibility for a lot of stamina (CG4002-Viz docs/protocol.md "Weave").

Engine rules, the tutorial bag, the socket flow (schema-checked against the
CG4002-Viz contracts; set CG4002_CONTRACTS_DIR to a checkout that has the
weave schemas), the AI path and the operator key.
"""

import asyncio
import json
from types import SimpleNamespace
import unittest

import websockets

from ai_to_visualizer_demo import AttackIds, run_keyboard_commands, send_ai_demo
from game_engine import (PRACTICE_WINDUP_SECONDS, STAMINA_COST, STAMINA_REGEN_PER_SECOND,
                         WEAVE_COOLDOWN_SECONDS, WEAVE_COST, WEAVE_MIN_CONFIDENCE,
                         WEAVE_SECONDS, GameEngine)
from test_match_flow import FakeClock, contract_validators, joined, to_fighting
from test_tutorial import tutorial_fighting
from visualizer_protocol import PhoneHub


def fighting(clock=None):
    engine = GameEngine(clock=clock or FakeClock())
    engine.start()
    return engine


def validate_state(test, engine):
    validators = contract_validators()
    if "match-state" not in validators:
        test.skipTest("jsonschema or CG4002-Viz contracts unavailable")
    state = PhoneHub(engine=engine).state()
    validators["match-state"].validate(state)
    return state


class EngineWeaveTests(unittest.TestCase):
    def test_weave_charges_stamina_once_and_reports_the_window(self):
        engine = fighting()
        self.assertTrue(engine.start_weave(1))
        self.assertEqual(engine.players[1].stamina, 100.0 - WEAVE_COST)
        state = engine.snapshot()["player_1"]
        self.assertEqual(state["weave_remaining_ms"], int(WEAVE_SECONDS * 1000))
        self.assertEqual(state["weave_cooldown_ms"], 0, "cooldown is 0 while weaving")
        self.assertEqual(engine.snapshot()["player_2"]["weave_remaining_ms"], 0)

    def test_punches_against_a_weaver_are_dodged_for_no_damage(self):
        engine = fighting()
        engine.start_weave(2)
        engine.clock.advance(WEAVE_SECONDS - 0.1)
        self.assertEqual(engine.resolve_punch(1, "RIGHT_UPPERCUT", 1.0, tracked=True), ("DODGE", 0.0))
        self.assertEqual(engine.players[2].health, 100.0)
        engine.clock.advance(0.2)
        outcome, damage = engine.resolve_punch(1, "JAB", 1.0, tracked=True)
        self.assertEqual(outcome, "HIT", "the window has closed")
        self.assertGreater(damage, 0)

    def test_untracked_punches_still_miss(self):
        engine = fighting()
        engine.start_weave(2)
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, tracked=False), ("MISS", 0.0))

    def test_no_stamina_regeneration_while_weaving(self):
        engine = fighting()
        engine.start_weave(1)
        engine.clock.advance(WEAVE_SECONDS)
        engine.advance()
        self.assertEqual(engine.players[1].stamina, 100.0 - WEAVE_COST)
        engine.clock.advance(1.0)
        engine.advance()
        self.assertEqual(engine.players[1].stamina, 100.0 - WEAVE_COST + STAMINA_REGEN_PER_SECOND)

    def test_regeneration_resumes_part_way_through_a_step(self):
        engine = fighting()
        engine.start_weave(1)
        engine.clock.advance(WEAVE_SECONDS + 0.5)   # one long step past the end
        engine.advance()
        self.assertEqual(engine.players[1].stamina,
                         100.0 - WEAVE_COST + 0.5 * STAMINA_REGEN_PER_SECOND)

    def test_no_punch_or_guard_while_weaving_and_weave_ends_a_guard(self):
        engine = fighting()
        self.assertTrue(engine.start_guard(1))
        self.assertTrue(engine.start_weave(1))
        self.assertFalse(engine.snapshot()["player_1"]["is_blocking"], "the weave ended the guard")
        self.assertFalse(engine.try_attack(1, "JAB"))
        self.assertFalse(engine.start_guard(1))
        engine.clock.advance(WEAVE_SECONDS)
        self.assertTrue(engine.try_attack(1, "JAB"), "free again once it ends")

    def test_not_mid_punch_and_not_twice(self):
        engine = fighting()
        engine.try_attack(1, "LEFT_UPPERCUT")
        self.assertFalse(engine.start_weave(1), "mid-punch")
        engine.clock.advance(1.0)
        self.assertTrue(engine.start_weave(1))
        self.assertFalse(engine.start_weave(1), "already weaving")

    def test_cooldown_after_the_weave_ends(self):
        engine = fighting()
        engine.start_weave(1)
        engine.clock.advance(WEAVE_SECONDS + 1.0)
        engine.players[1].stamina = 100.0
        state = engine.snapshot()["player_1"]
        self.assertEqual(state["weave_remaining_ms"], 0)
        self.assertEqual(state["weave_cooldown_ms"], int((WEAVE_COOLDOWN_SECONDS - 1.0) * 1000))
        self.assertFalse(engine.start_weave(1), "still cooling down")
        engine.clock.advance(WEAVE_COOLDOWN_SECONDS - 1.0)
        self.assertEqual(engine.snapshot()["player_1"]["weave_cooldown_ms"], 0)
        self.assertTrue(engine.start_weave(1))

    def test_needs_enough_stamina(self):
        engine = fighting()
        engine.players[1].stamina = WEAVE_COST - 0.01
        self.assertFalse(engine.start_weave(1))
        self.assertEqual(engine.players[1].stamina, WEAVE_COST - 0.01, "a rejected weave is free")

    def test_only_while_fighting(self):
        engine = GameEngine(clock=FakeClock())
        self.assertFalse(engine.start_weave(1), "LOBBY")
        with self.assertRaises(ValueError):
            engine.start_weave(3)

    def test_pause_clears_the_weave_and_cooldown(self):
        engine = to_fighting(joined())
        engine.start_weave(1)
        self.assertTrue(engine.pause())
        state = engine.snapshot()["player_1"]
        self.assertEqual((state["weave_remaining_ms"], state["weave_cooldown_ms"]), (0, 0))
        self.assertEqual(engine.players[1].weave_until, 0.0)

    def test_round_end_and_new_match_clear_it(self):
        engine = fighting()
        engine.start_weave(1)
        engine.clock.advance(engine.round_time)
        engine.advance()
        self.assertEqual(engine.phase, "ROUND_END")
        self.assertEqual(engine.players[1].weave_until, 0.0)
        self.assertEqual(engine.snapshot()["player_1"]["weave_remaining_ms"], 0)
        engine = fighting()
        engine.start_weave(2)
        engine.reset_match()
        self.assertEqual((engine.players[2].weave_until, engine.players[2].weave_cooldown_until),
                         (0.0, 0.0))

    def test_weaving_and_cooling_states_are_contract_valid(self):
        engine = fighting()
        engine.start_weave(1)
        state = validate_state(self, engine)
        self.assertEqual(state["player_1"]["weave_remaining_ms"], 3000)
        engine.clock.advance(WEAVE_SECONDS + 0.5)
        state = validate_state(self, engine)
        self.assertEqual(state["player_1"]["weave_cooldown_ms"], 3500)

    def test_a_weave_costs_more_than_any_punch(self):
        # Since the 11 November rebalance (regen 4/s) a weave costs about two
        # heavy punches, which is ~12 s of regeneration (it was ~6 s before).
        self.assertGreater(WEAVE_COST + WEAVE_SECONDS * STAMINA_REGEN_PER_SECOND,
                           2 * max(STAMINA_COST.values()))


class TutorialWeaveTests(unittest.TestCase):
    def test_weaving_when_the_bag_punch_lands_dodges_it(self):
        engine = tutorial_fighting()
        engine.command(1, "PRACTICE_PUNCH")
        engine.clock.advance(PRACTICE_WINDUP_SECONDS - 0.5)
        self.assertTrue(engine.start_weave(1))
        engine.clock.advance(0.5)
        engine.advance()
        [result] = engine.pop_practice_results()
        self.assertEqual((result["outcome"], result["damage"]), ("DODGE", 0.0))
        self.assertEqual(engine.players[1].health, 100.0)

    def test_the_bag_cannot_weave(self):
        engine = tutorial_fighting()
        self.assertFalse(engine.start_weave(2))


class SocketWeaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.validators = contract_validators()
        self.hub = PhoneHub(engine=fighting(), auto_start=True)
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        self.one = await self.join(url, 1)
        self.two = await self.join(url, 2)

    async def asyncTearDown(self):
        await self.one.close()
        await self.two.close()
        self.server.close()
        await self.server.wait_closed()

    async def join(self, url, player):
        socket = await websockets.connect(url)
        await socket.send(json.dumps({"type": "ClientHello", "protocol_version": 2,
                                      "client_id": f"phone-{player}", "player_id": player}))
        await asyncio.wait_for(socket.recv(), 3)
        return socket

    async def next_of(self, socket, kind, seconds=3):
        async def read():
            while True:
                message = json.loads(await socket.recv())
                if message["type"] == kind:
                    return message
        return await asyncio.wait_for(read(), seconds)

    def check(self, name, message):
        if name in self.validators:
            self.validators[name].validate(message)

    async def test_weave_reaches_both_phones_and_a_dodged_punch_follows(self):
        event = await self.hub.request_weave(2, confidence=0.9, weave_id="weave-a")
        self.assertIsNotNone(event)
        for phone in (self.one, self.two):
            received = await self.next_of(phone, "GameEvent")
            self.check("game-event", received)
            self.assertEqual((received["event"], received["source_player"], received["target_player"],
                              received["attack_id"], received["effect_duration_ms"],
                              received["outcome"], received["damage"]),
                             ("WEAVE", 2, 1, "weave-a", 3000, "NONE", 0.0))
            state = await self.next_of(phone, "MatchState")
            self.check("match-state", state)
            self.assertEqual(state["player_2"]["weave_remaining_ms"], 3000)
            self.assertEqual(state["player_2"]["stamina"], 100.0 - WEAVE_COST)

        # The same action ID again: the first result, no second event or cost.
        seq = self.hub.event_seq
        self.assertEqual(await self.hub.request_weave(2, confidence=0.9, weave_id="weave-a"), event)
        self.assertEqual(self.hub.event_seq, seq)
        self.assertEqual(self.hub.engine.players[2].stamina, 100.0 - WEAVE_COST)
        with self.assertRaises(ValueError):
            await self.hub.request_weave(1, confidence=0.9, weave_id="weave-a")

        # P1 punches the weaver: the phone says tracked, the server says DODGE.
        punch = asyncio.create_task(self.hub.request_punch(
            1, "JAB", 0.9, 0.8, response_timeout_ms=750, attack_id="jab-at-weaver"))
        attempt = await self.next_of(self.one, "PunchAttempt")
        await self.one.send(json.dumps({
            "type": "PunchObservation", "protocol_version": 2,
            "match_id": attempt["match_id"], "stream_id": attempt["stream_id"],
            "attack_id": attempt["attack_id"], "observer_player": 1,
            "observation": "TARGET_TRACKED", "target_age_ms": 20, "client_timestamp": 1,
        }))
        final = await asyncio.wait_for(punch, 3)
        self.check("game-event", final)
        self.assertEqual((final["outcome"], final["damage"]), ("DODGE", 0.0))
        self.assertEqual(self.hub.engine.players[2].health, 100.0)

    async def test_a_rejected_weave_sends_state_only(self):
        self.hub.engine.players[1].stamina = 10.0
        seq = self.hub.event_seq
        self.assertIsNone(await self.hub.request_weave(1, weave_id="tired"))
        self.assertEqual(self.hub.event_seq, seq)
        state = await self.next_of(self.one, "MatchState")
        self.assertEqual(state["player_1"]["weave_remaining_ms"], 0)

    async def test_invalid_requests_are_refused(self):
        for bad in ({"source_player": 3}, {"source_player": 1, "confidence": 1.5},
                    {"source_player": 1, "weave_id": "bad id"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await self.hub.request_weave(**bad)


class AiAndKeyboardWeaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_weave_needs_confidence_and_a_stable_id(self):
        hub = PhoneHub(engine=fighting(), auto_start=True)
        weak = SimpleNamespace(action="weave", t=0.0, confidence=WEAVE_MIN_CONFIDENCE - 0.01,
                               intensity=0.0, edge=None)
        self.assertIsNone(await send_ai_demo(hub, 0, weak, {}, 0.6, attack_id="w-1"))
        self.assertEqual(hub.engine.players[1].weave_until, 0.0)
        sure = SimpleNamespace(action="weave", t=0.0, confidence=0.95, intensity=0.0, edge=None)
        event = await send_ai_demo(hub, 0, sure, {}, 0.6, attack_id="w-2")
        self.assertEqual((event["event"], event["source_player"]), ("WEAVE", 1))
        with self.assertRaises(ValueError):
            await send_ai_demo(hub, 0, sure, {}, 0.6, attack_id=None)

    async def test_w_key_weaves_for_the_selected_player(self):
        hub = PhoneHub(engine=fighting(), auto_start=True)
        commands = asyncio.Queue()
        for key in ("2", "w", "w", "q"):
            commands.put_nowait(key)
        args = SimpleNamespace(fake_confidence=0.95, demo_intensity=0.6, response_timeout_ms=750)
        await asyncio.wait_for(run_keyboard_commands(args, hub, AttackIds("keys"), commands), 3)
        self.assertGreater(hub.engine.players[2].weave_until, 0.0)
        self.assertEqual(hub.engine.players[2].stamina, 100.0 - WEAVE_COST,
                         "the second press is rejected (already weaving)")
        self.assertEqual(hub.engine.players[1].weave_until, 0.0)


if __name__ == "__main__":
    unittest.main()
