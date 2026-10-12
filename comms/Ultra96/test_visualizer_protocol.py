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

from visualizer_protocol import PhoneHub, decode_hello


def hello(client_id, player_id):
    return json.dumps({
        "type": "ClientHello", "protocol_version": 2,
        "client_id": client_id, "player_id": player_id,
    })


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

    def test_demo_messages_match_canonical_v2_schemas_when_available(self):
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
            ("game-event", hub.demo_punch(1, "JAB", 0.9, 0.5)),
        )
        for name, payload in cases:
            schema = json.loads((contracts / (name + ".schema.json")).read_text(encoding="utf8"))
            Draft202012Validator(schema).validate(payload)


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
            hub = PhoneHub()
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

                        async with websockets.connect(url, ssl=client_tls) as duplicate:
                            await duplicate.send(hello("intruder", 1))
                            with self.assertRaises(websockets.exceptions.ConnectionClosed) as error:
                                await duplicate.recv()
                            self.assertEqual(error.exception.rcvd.code, 1008)

                        await hub.broadcast_demo_punch(1, "JAB", 0.9, 0.5)
                        event_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                        event_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                        self.assertEqual(event_one, event_two)
                        self.assertEqual(event_one["outcome"], "MISS")
                        self.assertEqual(event_one["damage"], 0.0)

                        # Exercise the sensor-pipeline thread's handoff to the
                        # same phone hub without requiring a physical ESP32.
                        import comms_server
                        with comms_server.pipeline_lock:
                            comms_server.visualizer_loop = asyncio.get_running_loop()
                            comms_server.visualizer_hub = hub
                        try:
                            comms_server.push_random_ai_event(1)
                            pipeline_one = json.loads(await asyncio.wait_for(one.recv(), 3))
                            pipeline_two = json.loads(await asyncio.wait_for(two.recv(), 3))
                            self.assertEqual(pipeline_one, pipeline_two)
                            self.assertEqual(pipeline_one["type"], "GameEvent")
                            self.assertEqual(pipeline_one["damage"], 0.0)
                        finally:
                            with comms_server.pipeline_lock:
                                comms_server.visualizer_loop = None
                                comms_server.visualizer_hub = None

                await asyncio.sleep(0.05)
                async with websockets.connect(url, ssl=client_tls) as rejoined:
                    await rejoined.send(hello("phone-one", 1))
                    self.assertEqual(json.loads(await rejoined.recv())["player_id"], 1)
                    self.assertEqual(json.loads(await rejoined.recv())["type"], "MatchState")


if __name__ == "__main__":
    unittest.main()
