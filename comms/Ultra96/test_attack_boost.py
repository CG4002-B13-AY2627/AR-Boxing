"""Attack boost pickup: engine rules, damage scaling, the socket flow and operator keys."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import websockets

from ai_to_visualizer_demo import AttackIds, run_keyboard_commands
from game_engine import (ROUND_SECONDS, ATTACK_BOOST_SECONDS, ATTACK_ITEM_MULTIPLIER, BASE_DAMAGE,
                         BLOCK_DAMAGE_MULTIPLIER, GameEngine)
from test_match_flow import FakeClock, contract_validators
from visualizer_protocol import PhoneHub


def fighting(clock=None):
    engine = GameEngine(clock=clock or FakeClock())
    engine.start()
    return engine


def boost(engine, player=1):
    item = engine.spawn_attack(player)
    return engine.collect_item(player, item.item_id, "AVAILABLE", 0.3)


class EngineAttackBoostTests(unittest.TestCase):
    def test_attack_item_is_contract_valid_and_shares_the_one_item_slot(self):
        engine = fighting()
        item = engine.spawn_attack(1)
        self.assertEqual(item.item_type, "ATTACK_MULTIPLIER")
        self.assertTrue(item.item_id.startswith("attack-p1-"))
        self.assertIsNone(engine.spawn_health(1), "one item per player, of either type")
        listed = engine.snapshot()["active_items"][0]
        self.assertEqual((listed["item_type"], listed["magnitude"], listed["effect_duration_ms"]),
                         ("ATTACK_MULTIPLIER", ATTACK_ITEM_MULTIPLIER, 30000))
        validators = contract_validators()
        if "match-state" in validators:
            validators["match-state"].validate(PhoneHub(engine=engine).state())

    def test_collect_starts_the_boost_without_healing(self):
        engine = fighting()
        engine.players[1].health = 60.0
        self.assertEqual(boost(engine), ("ACCEPTED", "ATTACK_MULTIPLIER", ATTACK_ITEM_MULTIPLIER))
        self.assertEqual(engine.players[1].health, 60.0)
        state = engine.snapshot()
        self.assertEqual(state["player_1"]["attack_multiplier"], ATTACK_ITEM_MULTIPLIER)
        self.assertEqual(state["player_1"]["attack_multiplier_remaining_ms"], 30000)
        self.assertEqual(state["player_2"]["attack_multiplier"], 1.0)
        self.assertEqual(state["player_2"]["attack_multiplier_remaining_ms"], 0)
        self.assertEqual(state["active_items"], [])

    def test_collect_health_still_reports_zero_gain_for_a_boost(self):
        engine = fighting()
        item = engine.spawn_attack(1)
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.3), ("ACCEPTED", 0.0))

    def test_boost_multiplies_damage_before_the_block_factor(self):
        engine = fighting()
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, True), ("HIT", BASE_DAMAGE["JAB"]))
        boost(engine)
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, True),
                         ("HIT", BASE_DAMAGE["JAB"] * ATTACK_ITEM_MULTIPLIER))
        self.assertTrue(engine.start_guard(2))
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, True),
                         ("BLOCK", round(BASE_DAMAGE["JAB"] * ATTACK_ITEM_MULTIPLIER *
                                         BLOCK_DAMAGE_MULTIPLIER, 2)))
        self.assertEqual(engine.resolve_punch(2, "JAB", 1.0, True), ("HIT", BASE_DAMAGE["JAB"]),
                         "only the boosted player hits harder")

    def test_boost_counts_fight_time_only_then_ends(self):
        engine = fighting()
        boost(engine)
        engine.clock.advance(10)
        engine.pause()
        engine.clock.advance(100)          # paused: the boost timer is frozen
        engine.resume()
        engine.advance()
        self.assertEqual(engine.snapshot()["player_1"]["attack_multiplier_remaining_ms"], 20000)
        engine.clock.advance(20)
        engine.advance()
        state = engine.snapshot()["player_1"]
        self.assertEqual((state["attack_multiplier"], state["attack_multiplier_remaining_ms"]), (1.0, 0))
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, True), ("HIT", BASE_DAMAGE["JAB"]))

    def test_collecting_again_refreshes_instead_of_stacking(self):
        engine = fighting()
        boost(engine)
        engine.clock.advance(20)
        boost(engine)
        state = engine.snapshot()["player_1"]
        self.assertEqual(state["attack_multiplier"], ATTACK_ITEM_MULTIPLIER)
        self.assertEqual(state["attack_multiplier_remaining_ms"], int(ATTACK_BOOST_SECONDS * 1000))

    def test_round_end_and_new_match_clear_the_boost(self):
        engine = fighting()
        boost(engine)
        engine.clock.advance(ROUND_SECONDS)
        engine.advance()
        self.assertEqual(engine.phase, "ROUND_END")
        self.assertEqual(engine.snapshot()["player_1"]["attack_multiplier"], 1.0)
        validators = contract_validators()
        if "match-state" in validators:
            validators["match-state"].validate(PhoneHub(engine=engine).state())

        engine = fighting()
        boost(engine)
        engine.reset_match()
        self.assertEqual(engine.snapshot()["player_1"]["attack_multiplier_remaining_ms"], 0)

    def test_timed_spawns_use_independent_fight_clock_deadlines_and_types(self):
        clock = FakeClock()
        engine = fighting(clock)
        engine.players[1].health = 40.0
        with patch.object(engine.rng, "uniform", side_effect=(24, 36)) as draw_delay:
            self.assertEqual(engine.spawn_due_items((1, 2), 30), [])
            self.assertEqual([call.args for call in draw_delay.call_args_list], [(24, 36)] * 2)
        clock.advance(24)
        with patch.object(engine.rng, "choice", return_value="ATTACK_MULTIPLIER") as choose:
            [one] = engine.spawn_due_items((1, 2), 30)
            self.assertEqual((one.owner, one.item_type), (1, "HEALTH"))
            choose.assert_not_called()
            engine.pause()
            clock.advance(120)
            self.assertEqual(engine.spawn_due_items((1, 2), 30), [])
            engine.resume()
            clock.advance(12)
            [two] = engine.spawn_due_items((1, 2), 30)
            self.assertEqual((two.owner, two.item_type), (2, "ATTACK_MULTIPLIER"))
            self.assertEqual(set(engine.items), {1, 2})
        engine.collect_item(1, one.item_id, "AVAILABLE", 0.2)
        with patch.object(engine.rng, "uniform", return_value=24):
            self.assertEqual(engine.spawn_due_items((1, 2), 30), [])
        self.assertEqual(engine.players[1].next_item_at, 60)
        engine.reset_match()
        self.assertIsNone(engine.players[1].next_item_at)

    def test_unknown_item_type_is_refused(self):
        with self.assertRaises(ValueError):
            fighting().spawn_item(1, "STAMINA")


class SocketAttackBoostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.validators = contract_validators()
        self.hub = PhoneHub(engine=fighting(), auto_start=True)
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        self.one = await self.join(url, 1)
        self.two = await self.join(url, 2)
        self.item = await self.hub.spawn_attack(1)

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

    async def test_a_boost_pickup_reaches_both_phones_with_the_multiplier(self):
        await self.hub.request_pickup(1, "grab-boost")
        check = await self.next_of(self.one, "PickupCheck")
        self.assertEqual(check["item_id"], self.item.item_id)
        await self.one.send(json.dumps({
            "type": "PickupObservation", "protocol_version": 2,
            "match_id": check["match_id"], "stream_id": check["stream_id"],
            "request_id": check["request_id"], "item_id": check["item_id"],
            "player_id": 1, "observation": "AVAILABLE", "client_timestamp": 1,
            "observed_distance_m": 0.3, "hand": "RIGHT",
        }))
        result = await self.next_of(self.one, "PickupResult")
        self.assertEqual((result["accepted"], result["reason"]), (True, "ACCEPTED"))
        for phone in (self.one, self.two):
            event = await self.next_of(phone, "GameEvent")
            if "game-event" in self.validators:
                self.validators["game-event"].validate(event)
            self.assertEqual((event["event"], event["item_type"], event["magnitude"],
                              event["effect_duration_ms"]),
                             ("ITEM_PICKUP", "ATTACK_MULTIPLIER", ATTACK_ITEM_MULTIPLIER, 30000))
            state = await self.next_of(phone, "MatchState")
            if "match-state" in self.validators:
                self.validators["match-state"].validate(state)
            self.assertEqual(state["player_1"]["attack_multiplier"], ATTACK_ITEM_MULTIPLIER)
            self.assertEqual(state["player_1"]["attack_multiplier_remaining_ms"], 30000)
            self.assertEqual(state["player_1"]["health"], 100.0)


class KeyboardAttackBoostTests(unittest.IsolatedAsyncioTestCase):
    async def test_o_key_spawns_an_attack_boost_for_the_selected_player(self):
        hub = PhoneHub(engine=fighting(), auto_start=True)
        commands = asyncio.Queue()
        for key in ("2", "o", "1", "i", "q"):
            commands.put_nowait(key)
        args = SimpleNamespace(fake_confidence=0.95, demo_intensity=0.6, response_timeout_ms=750)
        await asyncio.wait_for(run_keyboard_commands(args, hub, AttackIds("keys"), commands), 3)
        self.assertEqual(hub.engine.items[2].item_type, "ATTACK_MULTIPLIER")
        self.assertEqual(hub.engine.items[1].item_type, "HEALTH")


if __name__ == "__main__":
    unittest.main()
