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

    def test_welcome_and_state_match_canonical_v2_schemas_when_available(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        default_contracts = Path(__file__).resolve().parents[3] / "CG4002-Viz" / "contracts"
        contracts = Path(os.environ.get("CG4002_CONTRACTS_DIR", default_contracts))
        if not (contracts / "game-event.schema.json").is_file():
            self.skipTest("canonical CG4002-Viz contracts checkout is unavailable")

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


@unittest.skipUnless(shutil.which("openssl"), "openssl is required for TLS test")
class EncryptedHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_strict_tls_two_players_rejection_and_reconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "test.crt"
            key = Path(directory) / "test.key"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1",
                "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=IP:127.0.0.1",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_tls.load_cert_chain(cert, key)
            client_tls = ssl.create_default_context(cafile=str(cert))
            clock = FakeClock()
            hub = PhoneHub(engine=GameEngine(clock=clock), auto_start=True)
            validators = {}
            try:
                from jsonschema import Draft202012Validator
                default_contracts = Path(__file__).resolve().parents[3] / "CG4002-Viz" / "contracts"
                contracts = Path(os.environ.get("CG4002_CONTRACTS_DIR", default_contracts))
                for name in ("punch-attempt", "game-event", "match-state"):
                    schema = json.loads((contracts / (name + ".schema.json")).read_text(encoding="utf8"))
                    validators[name] = Draft202012Validator(schema)
            except (ImportError, FileNotFoundError):
                validators = {}
            async with websockets.serve(
                hub.handle, "127.0.0.1", 0, ssl=server_tls, max_size=65536,
            ) as server:
                url = "wss://127.0.0.1:" + str(server.sockets[0].getsockname()[1])

                # An untrusted chain must fail; no test ever disables validation.
                with self.assertRaises((ssl.SSLError, OSError)):
                    async with websockets.connect(url):
                        pass

                async with websockets.connect(url, ssl=client_tls) as one:
                    await one.send(hello("phone-one", 1))
                    welcome_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                    state_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                    self.assertEqual(welcome_one["player_id"], 1)
                    self.assertEqual(state_one["type"], "MatchState")

                    async with websockets.connect(url, ssl=client_tls) as two:
                        await two.send(hello("phone-two", 2))
                        welcome_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                        state_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                        self.assertEqual(welcome_two["player_id"], 2)
                        self.assertEqual(welcome_one["stream_id"], welcome_two["stream_id"])
                        self.assertEqual(state_one["match_id"], state_two["match_id"])
                        fighting_one = json.loads(await one.recv())
                        self.assertEqual(fighting_one["state"], "FIGHTING")
                        self.assertEqual(state_two["state"], "FIGHTING")

                        async with websockets.connect(url, ssl=client_tls) as duplicate:
                            await duplicate.send(hello("intruder", 1))
                            with self.assertRaises(websockets.exceptions.ConnectionClosed) as error:
                                await duplicate.recv()
                            self.assertEqual(error.exception.rcvd.code, 1008)

                        for source, wire, outcome in (
                            (1, "TARGET_TRACKED", "HIT"),
                            (2, "TARGET_NOT_TRACKED", "MISS"),
                            (1, "TRACKING_UNAVAILABLE", "MISS"),
                        ):
                            before = hub.health[3 - source]
                            task = asyncio.create_task(hub.request_punch(source, "JAB", 0.9, 0.5))
                            requester = one if source == 1 else two
                            attempt = await receive_type(requester, "PunchAttempt")
                            self.assertEqual(attempt["type"], "PunchAttempt")
                            if validators:
                                validators["punch-attempt"].validate(attempt)
                            response = {"type": "PunchObservation", "protocol_version": 2,
                                        "match_id": attempt["match_id"],
                                        "stream_id": attempt["stream_id"],
                                        "attack_id": attempt["attack_id"],
                                        "observer_player": source, "observation": wire,
                                        "client_timestamp": 123}
                            if wire == "TARGET_TRACKED":
                                response["target_age_ms"] = 0
                            await requester.send(json.dumps(response))
                            event_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                            event_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                            final_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                            final_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                            self.assertEqual(event_one, event_two)
                            self.assertEqual(final_one, final_two)
                            if validators:
                                validators["game-event"].validate(event_one)
                                validators["match-state"].validate(final_one)
                            self.assertEqual(event_one["outcome"], outcome)
                            self.assertEqual(final_one["player_1"]["health"], hub.health[1])
                            self.assertEqual(final_one["player_2"]["health"], hub.health[2])
                            self.assertEqual(event_one["damage"] > 0, outcome == "HIT")
                            self.assertEqual(before - hub.health[3 - source], event_one["damage"])
                            await task
                            if wire == "TARGET_TRACKED":
                                conflict = {**response, "observation": "TARGET_NOT_TRACKED"}
                                await requester.send(json.dumps(conflict))
                                with self.assertRaises(asyncio.TimeoutError):
                                    await asyncio.wait_for(requester.recv(), 0.03)
                            await requester.send(json.dumps(response))
                            self.assertEqual(json.loads(await requester.recv()), event_one)
                            replay_state = json.loads(await requester.recv())
                            self.assertEqual(replay_state["player_1"]["health"], hub.health[1])
                            self.assertEqual(replay_state["player_2"]["health"], hub.health[2])
                            other = two if source == 1 else one
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(other.recv(), 0.03)
                            clock.advance(1.1)

                        guard = await hub.request_guard(2, guard_id="legacy-test-guard-1")
                        self.assertEqual(json.loads(await one.recv()), guard)
                        self.assertEqual(json.loads(await two.recv()), guard)
                        guard_one = json.loads(await one.recv())
                        self.assertEqual(guard_one, json.loads(await two.recv()))
                        self.assertTrue(guard_one["player_2"]["is_blocking"])
                        task = asyncio.create_task(hub.request_punch(1, "JAB", 0.9, 0.5))
                        attempt = await receive_type(one, "PunchAttempt")
                        await one.send(json.dumps({
                            "type": "PunchObservation", "protocol_version": 2,
                            "match_id": attempt["match_id"],
                            "stream_id": attempt["stream_id"],
                            "attack_id": attempt["attack_id"],
                            "observer_player": 1, "observation": "TARGET_TRACKED",
                            "target_age_ms": 0, "client_timestamp": 126,
                        }))
                        blocked_one = json.loads(await one.recv())
                        blocked_two = json.loads(await two.recv())
                        self.assertEqual(blocked_one, blocked_two)
                        self.assertEqual(blocked_one["outcome"], "BLOCK")
                        self.assertEqual(blocked_one["damage"], 0.75)
                        self.assertEqual(json.loads(await one.recv()), json.loads(await two.recv()))
                        await task
                        clock.advance(1.1)

                        # A duplicated engine request with the same stable ID
                        # creates only one attempt, one event, and one mutation.
                        stable_id = "engine-attack-001"
                        before = hub.health[2]
                        first = asyncio.create_task(hub.request_punch(
                            1, "JAB", 0.9, 0.5, attack_id=stable_id))
                        second = asyncio.create_task(hub.request_punch(
                            1, "JAB", 0.9, 0.5, attack_id=stable_id))
                        stable_attempt = json.loads(await asyncio.wait_for(one.recv(), 3))
                        self.assertEqual(stable_attempt["attack_id"], stable_id)
                        stable_observation = {
                            "type": "PunchObservation", "protocol_version": 2,
                            "match_id": stable_attempt["match_id"],
                            "stream_id": stable_attempt["stream_id"],
                            "attack_id": stable_id, "observer_player": 1,
                            "observation": "TARGET_TRACKED", "target_age_ms": 0,
                            "client_timestamp": 128,
                        }
                        await one.send(json.dumps(stable_observation))
                        await one.send(json.dumps(stable_observation))
                        stable_one = json.loads(await one.recv())
                        self.assertEqual(stable_one, json.loads(await two.recv()))
                        self.assertEqual(json.loads(await one.recv()), json.loads(await two.recv()))
                        self.assertEqual(await first, await second)
                        self.assertEqual(before - hub.health[2], stable_one["damage"])
                        self.assertEqual(await hub.request_punch(
                            1, "JAB", 0.9, 0.5, attack_id=stable_id), stable_one)
                        with self.assertRaises(ValueError):
                            await hub.request_punch(
                                1, "CROSS", 0.9, 0.5, attack_id=stable_id)
                        try:
                            replay = json.loads(await asyncio.wait_for(one.recv(), 0.03))
                        except asyncio.TimeoutError:
                            pass  # duplicate arrived while still pending
                        else:
                            self.assertEqual(replay, stable_one)
                            self.assertEqual(json.loads(await one.recv())["type"], "MatchState")
                        with self.assertRaises(asyncio.TimeoutError):
                            await asyncio.wait_for(one.recv(), 0.03)
                        clock.advance(1.1)

                        # The other phone cannot answer an attacker's request.
                        task = asyncio.create_task(hub.request_punch(1, "JAB", 0.9, 0.5))
                        attempt = await receive_type(one, "PunchAttempt")
                        wrong = {"type": "PunchObservation", "protocol_version": 2,
                                 "match_id": attempt["match_id"],
                                 "stream_id": attempt["stream_id"],
                                 "attack_id": attempt["attack_id"],
                                 "observer_player": 2,
                                 "observation": "TARGET_TRACKED",
                                 "target_age_ms": 0, "client_timestamp": 125}
                        await two.send(json.dumps(wrong))
                        self.assertFalse(task.done())
                        wrong["observer_player"] = 1
                        wrong["observation"] = "TARGET_NOT_TRACKED"
                        await one.send(json.dumps(wrong))
                        self.assertEqual(json.loads(await one.recv()), json.loads(await two.recv()))
                        self.assertEqual(json.loads(await one.recv()), json.loads(await two.recv()))
                        await task
                        clock.advance(1.1)

                        # No response fails safe to a zero-damage miss.
                        task = asyncio.create_task(hub.request_punch(
                            1, "JAB", 0.9, 0.5, response_timeout_ms=100))
                        await receive_type(one, "PunchAttempt")
                        timeout_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                        timeout_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                        self.assertEqual(timeout_one, timeout_two)
                        self.assertEqual(timeout_one["outcome"], "MISS")
                        self.assertEqual(timeout_one["damage"], 0.0)
                        self.assertEqual(json.loads(await one.recv()), json.loads(await two.recv()))
                        await task
                        # A late observation cannot turn the timeout miss into a hit.
                        await one.send(json.dumps({
                            "type": "PunchObservation", "protocol_version": 2,
                            "match_id": timeout_one["match_id"],
                            "stream_id": timeout_one["stream_id"],
                            "attack_id": timeout_one["attack_id"],
                            "observer_player": 1, "observation": "TARGET_TRACKED",
                            "target_age_ms": 0, "client_timestamp": 129,
                        }))
                        self.assertEqual(json.loads(await one.recv()), timeout_one)
                        await one.recv()  # fresh convergence state for requester only
                        clock.advance(1.1)

                        # Disconnect before replying, rejoin the same reserved
                        # player slot, and finish the original pending ID once.
                        reconnect_task = asyncio.create_task(hub.request_punch(
                            1, "CROSS", 0.9, 0.5, response_timeout_ms=2000,
                            attack_id="reconnect-attack-001"))
                        first_attempt = await receive_type(one, "PunchAttempt")
                        await one.close()
                        await asyncio.sleep(0.02)
                        async with websockets.connect(url, ssl=client_tls) as resumed:
                            await resumed.send(hello("phone-one", 1))
                            self.assertEqual(json.loads(await resumed.recv())["player_id"], 1)
                            self.assertEqual(json.loads(await resumed.recv())["type"], "MatchState")
                            resent = json.loads(await asyncio.wait_for(resumed.recv(), 3))
                            self.assertEqual(resent["attack_id"], first_attempt["attack_id"])
                            resumed_observation = {
                                "type": "PunchObservation", "protocol_version": 2,
                                "match_id": resent["match_id"],
                                "stream_id": resent["stream_id"],
                                "attack_id": resent["attack_id"],
                                "observer_player": 1,
                                "observation": "TARGET_TRACKED", "target_age_ms": 0,
                                "client_timestamp": 130,
                            }
                            await resumed.send(json.dumps(resumed_observation))
                            final_resumed = json.loads(await resumed.recv())
                            self.assertEqual(final_resumed, await receive_type(two, "GameEvent"))
                            self.assertEqual(json.loads(await resumed.recv()), json.loads(await two.recv()))
                            self.assertEqual(await reconnect_task, final_resumed)
                            before_retry = hub.health[2]
                            await resumed.send(json.dumps(resumed_observation))
                            self.assertEqual(json.loads(await resumed.recv()), final_resumed)
                            await resumed.recv()  # fresh state acknowledges the retry
                            self.assertEqual(hub.health[2], before_retry)
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(two.recv(), 0.03)

                await asyncio.sleep(0.05)
                async with websockets.connect(url, ssl=client_tls) as rejoined:
                    await rejoined.send(hello("phone-one", 1))
                    self.assertEqual(json.loads(await rejoined.recv())["player_id"], 1)
                    self.assertEqual(json.loads(await rejoined.recv())["type"], "MatchState")


if __name__ == "__main__":
    unittest.main()
