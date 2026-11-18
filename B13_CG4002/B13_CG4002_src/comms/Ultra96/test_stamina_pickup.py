"""Stamina pickup (water bottle): engine rules, spawn preference, the socket flow and the b key."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import websockets

from ai_to_visualizer_demo import AttackIds, run_keyboard_commands
from game_engine import ITEM_TYPES, STAMINA_ITEM_AMOUNT, GameEngine
from test_match_flow import FakeClock, contract_validators
from visualizer_protocol import PhoneHub


def fighting(clock=None):
    engine = GameEngine(clock=clock or FakeClock())
    engine.start()
    return engine


def drink(engine, player=1):
    item = engine.spawn_stamina(player)
    return engine.collect_item(player, item.item_id, "AVAILABLE", 0.3)


class EngineStaminaPickupTests(unittest.TestCase):
    def test_stamina_item_shape_is_contract_valid(self):
        engine = fighting()
        item = engine.spawn_stamina(1)
        self.assertEqual(item.item_type, "STAMINA")
        self.assertTrue(item.item_id.startswith("stamina-p1-"))
        self.assertEqual((item.magnitude, item.effect_duration_ms), (STAMINA_ITEM_AMOUNT, 0))
        listed = engine.snapshot()["active_items"][0]
        self.assertEqual((listed["item_type"], listed["magnitude"], listed["effect_duration_ms"]),
                         ("STAMINA", 40.0, 0))
        validators = contract_validators()
        if "match-state" in validators:
            validators["match-state"].validate(PhoneHub(engine=engine).state())

    def test_collect_adds_forty_and_reports_the_actual_gain(self):
        engine = fighting()
        engine.players[1].stamina = 30.0
        engine.players[1].health = 70.0
        self.assertEqual(drink(engine), ("ACCEPTED", "STAMINA", 40.0))
        self.assertEqual(engine.players[1].stamina, 70.0)
        self.assertEqual(engine.players[1].health, 70.0, "stamina does not heal")
        engine.players[1].stamina = 85.0
        self.assertEqual(drink(engine), ("ACCEPTED", "STAMINA", 15.0))
        self.assertEqual(engine.players[1].stamina, 100.0)

    def test_consumed_even_at_full_stamina(self):
        engine = fighting()
        self.assertEqual(engine.players[1].stamina, 100.0)
        self.assertEqual(drink(engine), ("ACCEPTED", "STAMINA", 0.0))
        self.assertEqual(engine.items, {})
        self.assertEqual(engine.snapshot()["active_items"], [])

    def test_collect_health_reports_zero_for_stamina(self):
        engine = fighting()
        engine.players[1].stamina = 10.0
        item = engine.spawn_stamina(1)
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.3), ("ACCEPTED", 0.0))

    def test_one_item_per_player_across_all_three_types(self):
        self.assertEqual(set(ITEM_TYPES), {"HEALTH", "STAMINA", "ATTACK_MULTIPLIER"})
        for first in ITEM_TYPES:
            engine = fighting()
            self.assertIsNotNone(engine.spawn_item(1, first))
            for other in ITEM_TYPES:
                self.assertIsNone(engine.spawn_item(1, other), (first, other))
            self.assertIsNotNone(engine.spawn_stamina(2), "the other player has their own slot")

    def test_spawn_preference_health_then_stamina_then_random(self):
        engine = fighting()
        player = engine.players[1]
        with patch.object(engine.rng, "choice", return_value="ATTACK_MULTIPLIER") as choose:
            player.health, player.stamina = 40.0, 10.0
            self.assertEqual(engine.next_spawn_type(1), "HEALTH")
            player.health, player.stamina = 80.0, 39.0
            self.assertEqual(engine.next_spawn_type(1), "STAMINA")
            choose.assert_not_called()
            player.stamina = 40.0
            self.assertEqual(engine.next_spawn_type(1), "ATTACK_MULTIPLIER")
            choose.assert_called_once_with(ITEM_TYPES)


class SocketStaminaPickupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.validators = contract_validators()
        self.hub = PhoneHub(engine=fighting(), auto_start=True)
        self.hub.engine.players[1].stamina = 50.0
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])
        self.one = await self.join(url, 1)
        self.two = await self.join(url, 2)
        self.item = await self.hub.spawn_item(1, "STAMINA")

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

    async def test_a_stamina_pickup_reaches_both_phones(self):
        await self.hub.request_pickup(1, "grab-water")
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
            self.assertEqual((event["event"], event["item_type"], event["effect_duration_ms"]),
                             ("ITEM_PICKUP", "STAMINA", 0))
            # Stamina regenerates between the setup and the pickup, so the gain
            # is up to 40 (the actual amount added), and the state agrees.
            self.assertGreater(event["magnitude"], 0)
            self.assertLessEqual(event["magnitude"], STAMINA_ITEM_AMOUNT)
            state = await self.next_of(phone, "MatchState")
            if "match-state" in self.validators:
                self.validators["match-state"].validate(state)
            self.assertGreaterEqual(state["player_1"]["stamina"], 90.0)
            self.assertEqual(state["active_items"], [])


class KeyboardStaminaPickupTests(unittest.IsolatedAsyncioTestCase):
    async def test_b_key_spawns_stamina_for_the_selected_player(self):
        hub = PhoneHub(engine=fighting(), auto_start=True)
        commands = asyncio.Queue()
        for key in ("2", "b", "1", "o", "q"):
            commands.put_nowait(key)
        args = SimpleNamespace(fake_confidence=0.95, demo_intensity=0.6, response_timeout_ms=750)
        await asyncio.wait_for(run_keyboard_commands(args, hub, AttackIds("keys"), commands), 3)
        self.assertEqual(hub.engine.items[2].item_type, "STAMINA")
        self.assertEqual(hub.engine.items[1].item_type, "ATTACK_MULTIPLIER")


if __name__ == "__main__":
    unittest.main()
