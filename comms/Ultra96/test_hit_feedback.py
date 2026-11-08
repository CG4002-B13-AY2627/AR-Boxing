"""Attacker-only haptics, final-result deduplication and ESP session routing."""

import asyncio
import importlib
import unittest
from unittest.mock import patch

import protocol as P
from game_engine import GameEngine
from hit_feedback import HIT_DURATION_MS, HitFeedback, PUNCH_NODES, run_haptic_keys
from visualizer_protocol import PhoneHub


class FakeWriter:
    def __init__(self, error=None, stalled=False):
        self.frames = []
        self.error = error
        self.stalled = stalled
        self.closing = False

    def is_closing(self):
        return self.closing

    def write(self, frame):
        if self.error is not None:
            raise self.error
        self.frames.append(frame)

    async def drain(self):
        if self.stalled:
            await asyncio.Future()


class HitFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.feedback = HitFeedback()
        self.one, self.two = FakeWriter(), FakeWriter()
        self.feedback.writers = {1: self.one, 2: self.two}
        self.engine = GameEngine(god_mode=True)
        self.engine.start()
        self.hub = PhoneHub(engine=self.engine, on_hit=self.feedback.send_hit)
        self.serial = 0

    async def resolve(self, player=1, punch="JAB", observation="TARGET_TRACKED",
                      timeout=False, interrupt=False):
        self.serial += 1
        attack_id = f"haptic-{self.serial}"
        # Keep tests independent of animation/stamina timing.
        self.engine.players[player].busy_until = 0
        self.engine.players[player].stamina = 100
        task = asyncio.create_task(self.hub.request_punch(
            player, punch, 0.9, 1.0, response_timeout_ms=100, attack_id=attack_id))
        try:
            while attack_id not in self.hub.pending:
                await asyncio.sleep(0)
            if interrupt:
                self.engine.pause()
                self.engine.resume()
            if not timeout:
                self.hub.pending[attack_id].observation_future.set_result(observation)
            return await asyncio.wait_for(task, 2)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_all_six_punches_route_only_to_the_attacker_and_correct_hand(self):
        for player in (1, 2):
            for punch, node in PUNCH_NODES.items():
                with self.subTest(player=player, punch=punch):
                    self.one.frames.clear()
                    self.two.frames.clear()
                    event = await self.resolve(player, punch)
                    self.assertEqual(event["outcome"], "HIT")
                    self.assertEqual(self.feedback.writers[player].frames,
                                     [P.actuate(node, 1, HIT_DURATION_MS)])
                    self.assertEqual(self.feedback.writers[3 - player].frames, [])

    async def test_cached_attack_result_does_not_vibrate_again_or_charge_again(self):
        event = await self.resolve()
        stamina = self.engine.players[1].stamina
        cached = await self.hub.request_punch(1, "JAB", 0.9, 1.0,
                                            response_timeout_ms=100,
                                            attack_id=event["attack_id"])
        self.assertEqual(cached, event)
        self.assertEqual(self.engine.players[1].stamina, stamina)
        self.assertEqual(len(self.one.frames), 1)

    async def test_block_miss_timeout_and_interrupted_attack_do_not_vibrate(self):
        self.assertTrue(self.engine.start_guard(2))
        self.assertEqual((await self.resolve())["outcome"], "BLOCK")
        self.engine.end_guard(2)
        self.assertEqual((await self.resolve(observation="TARGET_NOT_TRACKED"))["outcome"], "MISS")
        self.assertEqual((await self.resolve(timeout=True))["outcome"], "MISS")
        self.assertEqual((await self.resolve(interrupt=True))["outcome"], "MISS")
        self.assertEqual(self.one.frames + self.two.frames, [])

    async def test_rejected_punch_does_not_vibrate(self):
        self.engine.pause()
        self.assertIsNone(await self.hub.request_punch(1, "JAB", 0.9, 1.0,
                                                      attack_id="paused"))
        self.assertEqual(self.one.frames + self.two.frames, [])

    async def test_hit_at_god_mode_hp_floor_still_vibrates(self):
        self.engine.players[2].health = 1
        event = await self.resolve()
        self.assertEqual((event["outcome"], event["damage"]), ("HIT", 0))
        self.assertEqual(len(self.one.frames), 1)

    async def test_offline_or_closing_gateway_does_not_replay_after_reconnection(self):
        for closing in (False, True):
            with self.subTest(closing=closing):
                self.one.frames.clear()
                self.feedback.writers.clear()
                if closing:
                    self.one.closing = True
                    self.feedback.writers[1] = self.one
                event = await self.resolve()
                self.assertEqual(event["outcome"], "HIT")
                self.one.closing = False
                self.feedback.writers[1] = self.one
                await self.hub.request_punch(1, "JAB", 0.9, 1.0,
                                             response_timeout_ms=100,
                                             attack_id=event["attack_id"])
                self.assertEqual(self.one.frames, [])

    async def test_failed_or_stalled_feedback_preserves_the_final_game_result(self):
        for writer in (FakeWriter(error=ConnectionResetError("disconnected")),
                       FakeWriter(stalled=True)):
            with self.subTest(stalled=writer.stalled):
                self.feedback.writers[1] = writer
                before = self.engine.players[2].health
                event = await self.resolve()
                self.assertEqual((event["outcome"], event["damage"]), ("HIT", 5))
                self.assertEqual(self.engine.players[2].health, before - 5)
                self.assertTrue(self.hub.attacks[event["attack_id"]].result_future.done())


class GatewayRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_entry_points_register_and_remove_the_right_player_connection(self):
        for module in ("esp_ai_live_dashboard", "esp_ai_live"):
            with self.subTest(entry_point=module):
                gateway = importlib.import_module(module).GatewayServer(None)
                tasks = set()

                def accept(reader, writer):
                    task = asyncio.create_task(gateway.handle(reader, writer))
                    tasks.add(task)

                server = await asyncio.start_server(accept, "127.0.0.1", 0)
                connections = []
                try:
                    port = server.sockets[0].getsockname()[1]
                    for player in (1, 2):
                        reader, writer = await asyncio.open_connection("127.0.0.1", port)
                        connections.append((reader, writer))
                        writer.write(P.build(P.HANDSHAKE, bytes([player, 2, 4])))
                        await writer.drain()
                        self.assertEqual((await asyncio.wait_for(reader.readexactly(9), 2))[1],
                                         P.HANDSHAKE_ACK)
                    self.assertEqual(set(gateway.feedback.writers), {1, 2})
                    event = {"outcome": "HIT", "source_player": 2,
                             "punch": "LEFT_HOOK", "attack_id": "route-p2"}
                    await gateway.feedback.send_hit(event)
                    self.assertEqual(await asyncio.wait_for(connections[1][0].readexactly(7), 2),
                                     P.actuate(1, 1, HIT_DURATION_MS))
                    # The P1 stream only has its own heartbeat response.
                    connections[0][1].write(P.heartbeat(1, 2))
                    await connections[0][1].drain()
                    self.assertEqual((await asyncio.wait_for(connections[0][0].readexactly(5), 2))[1],
                                     P.HEARTBEAT_ACK)
                finally:
                    for _, writer in connections:
                        writer.close()
                    await asyncio.gather(*(writer.wait_closed() for _, writer in connections),
                                         return_exceptions=True)
                    server.close()
                    await server.wait_closed()
                    await asyncio.wait_for(asyncio.gather(*tasks), 3)
                self.assertEqual(gateway.feedback.writers, {})


class HapticKeyboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyboard_selects_player_and_hand_without_phone_or_match(self):
        feedback = HitFeedback()
        feedback.writers = {1: FakeWriter(), 2: FakeWriter()}
        stop = asyncio.Event()

        class ScriptedKeyboard:
            def __init__(self, commands):
                self.commands = commands
                self.closed = False

            def start(self):
                for key in ("l", "2", "r", "l", "1", "r", "?", "q"):
                    self.commands.put_nowait(key)

            def close(self):
                self.closed = True

        instances = []

        def make_keyboard(commands):
            keyboard = ScriptedKeyboard(commands)
            instances.append(keyboard)
            return keyboard

        with patch("ai_to_visualizer_demo.KeyboardInput", side_effect=make_keyboard):
            await asyncio.wait_for(run_haptic_keys(feedback, stop), 2)
        self.assertTrue(stop.is_set())
        self.assertTrue(instances[0].closed)
        self.assertEqual(feedback.writers[1].frames,
                         [P.actuate(1, 1, HIT_DURATION_MS), P.actuate(2, 1, HIT_DURATION_MS)])
        self.assertEqual(feedback.writers[2].frames,
                         [P.actuate(2, 1, HIT_DURATION_MS), P.actuate(1, 1, HIT_DURATION_MS)])

    async def test_offline_and_failed_pulses_allow_the_next_key_and_quit(self):
        feedback = HitFeedback()
        feedback.writers[2] = FakeWriter(error=ConnectionResetError("offline"))
        stop = asyncio.Event()

        class ScriptedKeyboard:
            def __init__(self, commands):
                self.commands = commands

            def start(self):
                for key in ("l", "2", "r", "q"):
                    self.commands.put_nowait(key)

            def close(self):
                pass

        with patch("ai_to_visualizer_demo.KeyboardInput", ScriptedKeyboard):
            await asyncio.wait_for(run_haptic_keys(feedback, stop), 2)
        self.assertTrue(stop.is_set())


if __name__ == "__main__":
    unittest.main()
