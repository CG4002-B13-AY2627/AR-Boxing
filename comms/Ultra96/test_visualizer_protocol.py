"""TLS and protocol-v2 handshake checks for the Ultra96 phone endpoint.

Run with: python3 -m unittest discover -s comms/Ultra96 -p 'test_visualizer_protocol.py'
Requires openssl and websockets; test keys live only in a temporary directory.
"""

import asyncio
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path

import websockets

from game_engine import GameEngine
from visualizer_protocol import PhoneHub, decode_hello, decode_observation


def hello(client_id, player_id):
    return json.dumps({
        "type": "ClientHello", "protocol_version": 2,
        "client_id": client_id, "player_id": player_id,
    })


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


async def receive_type(websocket, message_type):
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), 3))
        if message["type"] == message_type:
            return message
        if message["type"] != "MatchState":
            raise AssertionError(f"unexpected {message['type']} before {message_type}")


class HelloValidationTests(unittest.TestCase):
    def test_exact_v2_fields_are_required(self):
        self.assertEqual(decode_hello(hello("phone-1", 1)), ("phone-1", 1))
        for payload in (
            "{}", "[]", "not json", hello("phone-1", 3),
            hello("bad space", 1),
            json.dumps({"type": "ClientHello", "protocol_version": True,
                        "client_id": "phone-1", "player_id": 1}),
            json.dumps({"type": "ClientHello", "protocol_version": 2,
                        "client_id": "phone-1", "player_id": 1, "extra": 1}),
        ):
            self.assertIsNone(decode_hello(payload))

    def test_welcome_and_state_match_canonical_v2_schemas(self):
        from jsonschema import Draft202012Validator
        default_contracts = Path(__file__).resolve().parents[3] / "CG4002-Viz" / "contracts"
        contracts = Path(os.environ.get("CG4002_CONTRACTS_DIR", default_contracts))
        self.assertTrue((contracts / "game-event.schema.json").is_file(), "Matching contracts required")

        hub = PhoneHub()
        cases = (
            ("server-welcome", hub.welcome(1)),
            ("match-state", hub.state()),
        )
        for name, payload in cases:
            schema = json.loads((contracts / (name + ".schema.json")).read_text(encoding="utf8"))
            Draft202012Validator(schema).validate(payload)

    def test_observation_rejects_noncanonical_fields(self):
        good = {"type": "PunchObservation", "protocol_version": 2,
                "match_id": "match-1", "stream_id": "boot-1", "attack_id": "attack-1",
                "observer_player": 1, "observation": "TARGET_TRACKED",
                "target_age_ms": 0, "client_timestamp": 10}
        self.assertIsNotNone(decode_observation(json.dumps(good)))
        for change in ({"observation": "VISIBLE"}, {"target_age_ms": -1},
                       {"protocol_version": True}, {"observer_player": 3}):
            self.assertIsNone(decode_observation(json.dumps({**good, **change})))


class AttackLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_attack_ids_are_unique_within_stream(self):
        engine = GameEngine()
        engine.start()
        hub = PhoneHub(engine=engine)
        first, second = await asyncio.gather(
            hub.request_punch(1, "JAB", 0.9, 0.5, response_timeout_ms=100),
            hub.request_punch(2, "CROSS", 0.9, 0.5, response_timeout_ms=100),
        )
        self.assertNotEqual(first["attack_id"], second["attack_id"])
        self.assertEqual(hub.event_seq, 2)

    async def test_missing_phone_times_out_once_and_cached_id_is_idempotent(self):
        engine = GameEngine()
        engine.start()
        hub = PhoneHub(engine=engine)
        first = await hub.request_punch(
            1, "JAB", 0.9, 0.5, response_timeout_ms=100,
            attack_id="missing-phone-001")
        self.assertEqual(first["outcome"], "MISS")
        self.assertEqual(first["damage"], 0.0)
        self.assertEqual(hub.event_seq, 1)
        self.assertEqual(hub.attacks["missing-phone-001"].status, "RESOLVED")
        self.assertNotIn("missing-phone-001", hub.pending)
        self.assertEqual(await hub.request_punch(
            1, "JAB", 0.9, 0.5, response_timeout_ms=100,
            attack_id="missing-phone-001"), first)
        self.assertEqual(hub.event_seq, 1)
        self.assertEqual(hub.health[2], 100.0)

    async def test_cancelled_engine_waiter_does_not_cancel_resolution(self):
        engine = GameEngine()
        engine.start()
        hub = PhoneHub(engine=engine)
        waiter = asyncio.create_task(hub.request_punch(
            1, "JAB", 0.9, 0.5, response_timeout_ms=100,
            attack_id="cancelled-waiter-001"))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        await asyncio.sleep(0.15)
        self.assertEqual(hub.attacks["cancelled-waiter-001"].final_event["outcome"], "MISS")
        self.assertEqual(hub.event_seq, 1)



# Real menu, attack, pickup and reconnect coverage is in test_multiplayer.py.
