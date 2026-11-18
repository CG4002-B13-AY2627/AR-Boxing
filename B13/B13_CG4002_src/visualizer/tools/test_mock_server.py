"""Automated tests for the external WebSocket pickup authority."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import unittest
from pathlib import Path

import websockets
from jsonschema import Draft202012Validator
from websockets.asyncio.server import serve

from tools.mock_server import (
    ATTACK_ITEM_ID,
    HEALTH_ITEM_ID,
    DeliveryOptions,
    Simulation,
    broadcast,
    default_sequence_start,
    handle_client,
)


ROOT = Path(__file__).resolve().parents[1]


class SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.event_validator = Draft202012Validator(
            json.loads(
                (ROOT / "contracts" / "game-event.schema.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        cls.state_validator = Draft202012Validator(
            json.loads(
                (ROOT / "contracts" / "match-state.schema.json").read_text(
                    encoding="utf-8"
                )
            )
        )

    def validate_message(self, message: dict[str, object]) -> None:
        validator = (
            self.event_validator
            if message["type"] == "GameEvent"
            else self.state_validator
        )
        validator.validate(message)

    def test_health_lifecycle_emits_event_then_converged_state(self) -> None:
        simulation = Simulation(
            sequence_start=100,
            attack_interval_seconds=0.0,
            health_bearing_degrees=-25.0,
        )

        before_spawn = simulation.state(1.9)
        spawned = simulation.state(2.0)
        events = simulation.advance(6.0)
        collected = simulation.state(6.0)

        self.assertEqual(before_spawn["active_items"], [])
        self.assertEqual(spawned["active_items"][0]["id"], HEALTH_ITEM_ID)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "ITEM_PICKUP")
        self.assertEqual(collected["active_items"], [])
        self.assertEqual(collected["player_1"]["health"], 85.0)
        for message in (before_spawn, spawned, *events, collected):
            self.validate_message(message)

    def test_health_clamps_and_uncollected_item_expires(self) -> None:
        collected = Simulation(
            player_one_health=90.0,
            attack_interval_seconds=0.0,
            health_bearing_degrees=0.0,
        )
        collected.advance(6.0)
        self.assertEqual(collected.state(6.0)["player_1"]["health"], 100.0)

        expired = Simulation(
            attack_interval_seconds=0.0,
            auto_collect_health=False,
            health_bearing_degrees=0.0,
        )
        self.assertTrue(expired.state(9.9)["active_items"])
        self.assertEqual(expired.state(10.0)["active_items"], [])
        self.assertEqual(expired.state(10.0)["player_1"]["health"], 60.0)

    def test_optional_attack_item_expires_without_client_gameplay_effect(self) -> None:
        simulation = Simulation(
            attack_interval_seconds=0.0,
            include_attack_item=True,
            auto_collect_health=False,
            health_bearing_degrees=0.0,
        )

        active_ids = {item["id"] for item in simulation.state(3.0)["active_items"]}
        expired_ids = {item["id"] for item in simulation.state(8.0)["active_items"]}

        self.assertIn(ATTACK_ITEM_ID, active_ids)
        self.assertNotIn(ATTACK_ITEM_ID, expired_ids)

    def test_fault_delivery_is_schema_valid_and_deterministic(self) -> None:
        simulation = Simulation(
            sequence_start=500,
            attack_interval_seconds=0.0,
            health_bearing_degrees=25.0,
        )
        delivery = DeliveryOptions(
            duplicate_once=True,
            stale_once=True,
            burst_size=70,
        )

        spawn_messages = delivery.build_messages(simulation, 2.0)
        collection_messages = delivery.build_messages(simulation, 6.0)

        self.assertEqual(len(spawn_messages), 71)
        pickup_events = [
            message
            for message in collection_messages
            if message.get("event") == "ITEM_PICKUP"
        ]
        self.assertEqual(len(pickup_events), 2)
        self.assertEqual(pickup_events[0]["seq"], pickup_events[1]["seq"])
        state_sequences = [
            message["seq"]
            for message in collection_messages
            if message["type"] == "MatchState"
        ]
        self.assertLess(state_sequences[-1], state_sequences[0])
        for message in (*spawn_messages, *collection_messages):
            self.validate_message(message)

    def test_default_restart_sequence_base_moves_forward(self) -> None:
        first = default_sequence_start()
        time.sleep(0.002)
        second = default_sequence_start()
        self.assertGreater(second, first)


class WebSocketReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_converges_after_missed_pickup_event(self) -> None:
        clients = set()
        simulation = Simulation(
            sequence_start=900,
            attack_interval_seconds=0.0,
            health_spawn_seconds=0.05,
            health_collect_seconds=0.25,
            health_expire_seconds=1.0,
            health_bearing_degrees=0.0,
            started_at=time.monotonic(),
        )
        delivery = DeliveryOptions()

        async with serve(
            lambda websocket: handle_client(websocket, clients, simulation),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            broadcaster = asyncio.create_task(
                broadcast(clients, simulation, delivery, 0.01)
            )
            try:
                async with websockets.connect(url) as websocket:
                    await self.receive_matching(
                        websocket,
                        lambda message: any(
                            item.get("id") == HEALTH_ITEM_ID
                            for item in message.get("active_items", [])
                        ),
                    )

                await asyncio.sleep(0.30)
                async with websockets.connect(url) as websocket:
                    converged = await self.receive_matching(
                        websocket,
                        lambda message: message.get("type") == "MatchState"
                        and not message.get("active_items")
                        and message["player_1"]["health"] == 85.0,
                    )
                self.assertEqual(converged["player_1"]["health"], 85.0)
            finally:
                broadcaster.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await broadcaster

    async def receive_matching(self, websocket: object, predicate: object) -> dict[str, object]:
        async with asyncio.timeout(2.0):
            while True:
                message = json.loads(await websocket.recv())
                if predicate(message):
                    return message


if __name__ == "__main__":
    unittest.main()
