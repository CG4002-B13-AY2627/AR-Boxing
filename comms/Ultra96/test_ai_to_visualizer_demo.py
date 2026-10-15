"""Hardware-free, strict-TLS test of the AI adapter and complete phone flow."""

import asyncio
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import websockets

from ai_to_visualizer_demo import (
    AttackIds, DEFAULT_ACTION_MAP, FakeAiEvent, run_fake,
    run_keyboard_commands, send_ai_demo,
)
from game_engine import GameEngine
from visualizer_protocol import PhoneHub


def hello(player):
    return json.dumps({
        "type": "ClientHello", "protocol_version": 2,
        "client_id": f"test-phone-{player}", "player_id": player,
    })


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


async def receive_type(websocket, message_type):
    """Ignore newer convergence snapshots while waiting for a transient event."""
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), 3))
        if message["type"] == message_type:
            return message
        if message["type"] != "MatchState":
            raise AssertionError(f"unexpected {message['type']} before {message_type}")


@unittest.skipUnless(shutil.which("openssl"), "openssl is required for TLS test")
class AiDemoFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_guard_punch_retry_and_state_to_both_phones(self):
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
            hub = PhoneHub(engine=GameEngine(clock=FakeClock()))
            args = SimpleNamespace(fake_confidence=0.95, demo_intensity=0.6,
                                   response_timeout_ms=1000)
            commands = asyncio.Queue()

            async with websockets.serve(hub.handle, "127.0.0.1", 0, ssl=server_tls) as server:
                url = "wss://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
                async with websockets.connect(url, ssl=client_tls) as one:
                    await one.send(hello(1))
                    await receive_type(one, "ServerWelcome")
                    await receive_type(one, "MatchState")
                    async with websockets.connect(url, ssl=client_tls) as two:
                        await two.send(hello(2))
                        await receive_type(two, "ServerWelcome")
                        await receive_type(two, "MatchState")
                        task = asyncio.create_task(run_keyboard_commands(
                            args, hub, AttackIds("keys"), commands))
                        try:
                            await commands.put("g")  # P1 guards
                            guard_one = await receive_type(one, "GameEvent")
                            guard_two = await receive_type(two, "GameEvent")
                            self.assertEqual(guard_one, guard_two)
                            self.assertEqual(guard_one["event"], "GUARD")
                            state_one = await receive_type(one, "MatchState")
                            self.assertEqual(state_one, await receive_type(two, "MatchState"))
                            self.assertTrue(state_one["player_1"]["is_blocking"])
                            self.assertEqual(state_one["player_1"]["stamina"], 92.0)

                            await commands.put("2")
                            await commands.put("h")  # P2 attacks guarded P1
                            attempt = await receive_type(two, "PunchAttempt")
                            self.assertEqual(attempt["punch"], "RIGHT_HOOK")
                            await two.send(json.dumps({
                                "type": "PunchObservation", "protocol_version": 2,
                                "match_id": attempt["match_id"],
                                "stream_id": attempt["stream_id"],
                                "attack_id": attempt["attack_id"],
                                "observer_player": 2,
                                "observation": "TARGET_TRACKED",
                                "target_age_ms": 0, "client_timestamp": 123,
                            }))
                            event_one = await receive_type(one, "GameEvent")
                            self.assertEqual(event_one, await receive_type(two, "GameEvent"))
                            self.assertEqual(event_one["outcome"], "BLOCK")
                            self.assertEqual(event_one["damage"], 1.8)
                            final_one = await receive_type(one, "MatchState")
                            self.assertEqual(final_one, await receive_type(two, "MatchState"))
                            self.assertEqual(final_one["player_1"]["health"], 98.2)
                            self.assertEqual(final_one["player_2"]["stamina"], 85.0)

                            await commands.put("s")  # force a fresh MatchState
                            snapshot_one = await receive_type(one, "MatchState")
                            self.assertEqual(snapshot_one, await receive_type(two, "MatchState"))
                            self.assertGreater(snapshot_one["seq"], final_one["seq"])
                            await commands.put("r")  # same attack ID: cached, no broadcast
                            await commands.put("q")
                            await asyncio.wait_for(task, 3)
                            self.assertEqual(hub.health[1], 98.2)
                            self.assertEqual(hub.event_seq, event_one["seq"])
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(one.recv(), 0.05)
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(two.recv(), 0.05)
                        finally:
                            if not task.done():
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)

    async def test_fake_ai_attempt_observation_and_identical_final_state(self):
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
            hub = PhoneHub(engine=GameEngine(clock=clock))
            ids = AttackIds("fixture-run")

            async with websockets.serve(hub.handle, "127.0.0.1", 0, ssl=server_tls) as server:
                url = "wss://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
                async with websockets.connect(url, ssl=client_tls) as one:
                    await one.send(hello(1))
                    self.assertEqual(json.loads(await one.recv())["player_id"], 1)
                    await one.recv()  # initial MatchState
                    async with websockets.connect(url, ssl=client_tls) as two:
                        await two.send(hello(2))
                        self.assertEqual(json.loads(await two.recv())["player_id"], 2)
                        await two.recv()  # initial MatchState
                        guard = await hub.request_guard(2, guard_id="test-guard-p2-1")
                        self.assertEqual(guard, await receive_type(one, "GameEvent"))
                        self.assertEqual(guard, await receive_type(two, "GameEvent"))
                        guard_state_one = await receive_type(one, "MatchState")
                        guard_state_two = await receive_type(two, "MatchState")
                        self.assertEqual(guard_state_one, guard_state_two)
                        self.assertTrue(guard_state_one["player_2"]["is_blocking"])
                        self.assertEqual(guard_state_one["player_2"]["stamina"], 92.0)

                        for index, (player, action, observation, expected) in enumerate((
                            (1, "l_hook", "TARGET_TRACKED", "BLOCK"),
                            (1, "l_hook", "TARGET_TRACKED", "HIT"),
                            (1, "l_hook", "TARGET_NOT_TRACKED", "MISS"),
                            (1, "l_hook", "TRACKING_UNAVAILABLE", "MISS"),
                            (2, "r_hook", "TARGET_TRACKED", "HIT"),
                        ), start=1):
                            attack_id = f"ai-fixture-run-p{player}-{index}"
                            event = FakeAiEvent(action, 0.0, 0.95)
                            target = 3 - player
                            before = hub.health[target]
                            fake_args = SimpleNamespace(
                                fake_player=player, fake_action=action, fake_punch=None,
                                fake_confidence=0.95,
                                fake_count=1, fake_interval=0, demo_intensity=0.6,
                                response_timeout_ms=1000, fake_retry=True,
                                fake_defender_guard=False,
                            )
                            task = asyncio.create_task(run_fake(
                                fake_args, hub, DEFAULT_ACTION_MAP, ids))
                            attacker = one if player == 1 else two
                            attempt = await receive_type(attacker, "PunchAttempt")
                            self.assertEqual(attempt["type"], "PunchAttempt")
                            self.assertEqual(attempt["attack_id"], attack_id)
                            self.assertEqual(attempt["punch"],
                                             "LEFT_HOOK" if player == 1 else "RIGHT_HOOK")
                            self.assertEqual(attempt["source_player"], player)
                            self.assertEqual(attempt["target_player"], target)
                            response = {
                                "type": "PunchObservation", "protocol_version": 2,
                                "match_id": attempt["match_id"],
                                "stream_id": attempt["stream_id"],
                                "attack_id": attack_id, "observer_player": player,
                                "observation": observation, "client_timestamp": 123,
                            }
                            if observation == "TARGET_TRACKED":
                                response["target_age_ms"] = 0
                            await attacker.send(json.dumps(response))
                            event_one = await receive_type(one, "GameEvent")
                            event_two = await receive_type(two, "GameEvent")
                            state_one = await receive_type(one, "MatchState")
                            state_two = await receive_type(two, "MatchState")
                            self.assertEqual(event_one, event_two)
                            self.assertEqual(state_one, state_two)
                            self.assertEqual(event_one["type"], "GameEvent")
                            self.assertEqual(event_one["attack_id"], attack_id)
                            self.assertEqual(event_one["outcome"], expected)
                            self.assertEqual(state_one["type"], "MatchState")
                            self.assertEqual(state_one[f"player_{target}"]["health"],
                                             hub.health[target])
                            self.assertEqual(state_one[f"player_{player}"]["stamina"],
                                             hub.engine.players[player].stamina)
                            self.assertEqual(round(before - hub.health[target], 2),
                                             event_one["damage"])
                            await task

                            # Retrying the same classified event cannot send
                            # another attempt or apply damage a second time.
                            seq = hub.event_seq
                            self.assertEqual(await send_ai_demo(
                                hub, player - 1, event, DEFAULT_ACTION_MAP, 0.6,
                                response_timeout_ms=1000, attack_id=attack_id), event_one)
                            self.assertEqual(hub.event_seq, seq)
                            self.assertEqual(hub.health[target],
                                             state_one[f"player_{target}"]["health"])
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(one.recv(), 0.03)
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(two.recv(), 0.03)
                            clock.advance(1.1)

                        self.assertEqual(len(hub.attacks), 5)
                        await two.close()
                        paused = await receive_type(one, "MatchState")
                        self.assertEqual(paused["state"], "PAUSED")
                        remaining = paused["round_time"]
                        clock.advance(10)
                        await hub.broadcast_state()
                        paused_later = await receive_type(one, "MatchState")
                        self.assertEqual(paused_later["round_time"], remaining)
                        self.assertIsNone(await hub.request_punch(
                            1, "JAB", 1.0, 1.0, attack_id="paused-attack"))
                        self.assertNotIn("paused-attack", hub.attacks)
                        await receive_type(one, "MatchState")
                        async with websockets.connect(url, ssl=client_tls) as rejoined:
                            await rejoined.send(hello(2))
                            self.assertEqual(json.loads(await rejoined.recv())["player_id"], 2)
                            resumed = json.loads(await rejoined.recv())
                            self.assertEqual(resumed["state"], "FIGHTING")
                            self.assertEqual(resumed, await receive_type(one, "MatchState"))
                            self.assertEqual(resumed["round_time"], remaining)

    async def test_unmapped_and_sustained_events_do_not_request_punch(self):
        hub = PhoneHub()
        for event in (FakeAiEvent("unknown", 0.0, 0.9),
                      FakeAiEvent("l_hook", 0.0, 0.9, edge="start")):
            self.assertIsNone(await send_ai_demo(
                hub, 0, event, DEFAULT_ACTION_MAP, 0.6, attack_id="unused-1"))
        self.assertEqual(hub.attacks, {})

    async def test_fake_defender_guard_option_uses_authoritative_guard(self):
        clock = FakeClock()
        engine = GameEngine(clock=clock)
        engine.start()
        hub = PhoneHub(engine=engine)
        args = SimpleNamespace(
            fake_player=1, fake_action="l_hook", fake_punch=None,
            fake_confidence=0.9,
            fake_count=1, fake_interval=0, demo_intensity=0.6,
            response_timeout_ms=100, fake_retry=False,
            fake_defender_guard=True,
        )
        await run_fake(args, hub, DEFAULT_ACTION_MAP, AttackIds("guard-option"))
        self.assertEqual(len(hub.guard_actions), 1)
        self.assertEqual(engine.players[2].stamina, 92.0)
        self.assertTrue(engine.snapshot()["player_2"]["is_blocking"])
        self.assertEqual(len(hub.attacks), 1)

    async def test_fake_punch_can_exercise_uppercut_without_model_label(self):
        engine = GameEngine(clock=FakeClock())
        engine.start()
        hub = PhoneHub(engine=engine)
        args = SimpleNamespace(
            fake_player=1, fake_action="unused", fake_punch="LEFT_UPPERCUT",
            fake_confidence=0.9, fake_count=1, fake_interval=0,
            demo_intensity=1.0, response_timeout_ms=100,
            fake_retry=False, fake_defender_guard=False,
        )
        await run_fake(args, hub, {"FAKE_PUNCH": "LEFT_UPPERCUT"},
                       AttackIds("uppercut-option"))
        self.assertEqual(next(iter(hub.attacks.values())).punch, "LEFT_UPPERCUT")
        self.assertEqual(engine.players[1].stamina, 78.0)


if __name__ == "__main__":
    unittest.main()
