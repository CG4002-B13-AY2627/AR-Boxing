"""Hub robustness: bounded sends, free-slot reclaim, punches across a pause."""

import asyncio
import json
import time
import unittest

import websockets

import visualizer_protocol
from game_engine import GameEngine
from visualizer_protocol import PhoneHub


class RecordingSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


class StalledSocket:
    """A phone whose network buffer is full: send() never finishes."""

    class Transport:
        aborted = False

        def abort(self):
            self.aborted = True

    def __init__(self):
        self.transport = self.Transport()

    async def send(self, payload):
        await asyncio.Event().wait()


def hello(player, client):
    return json.dumps({"type": "ClientHello", "protocol_version": 2,
                       "client_id": client, "player_id": player})


class BoundedSendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = visualizer_protocol.SEND_TIMEOUT_SECONDS
        visualizer_protocol.SEND_TIMEOUT_SECONDS = 0.05

    async def asyncTearDown(self):
        visualizer_protocol.SEND_TIMEOUT_SECONDS = self.saved

    async def test_a_stalled_phone_is_dropped_without_delaying_the_other(self):
        hub = PhoneHub()
        stalled, good = StalledSocket(), RecordingSocket()
        hub.ready = {1: stalled, 2: good}
        started = time.monotonic()
        await hub.broadcast(hub.state())
        await hub.broadcast(hub.state())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual([m["seq"] for m in good.sent], [1, 2])
        self.assertTrue(stalled.transport.aborted)

    async def test_state_stream_runs_at_the_contract_rate(self):
        self.assertAlmostEqual(visualizer_protocol.STATE_INTERVAL_SECONDS, 0.1)


class SlotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hub = PhoneHub()
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        self.url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def join(self, player, client):
        socket = await websockets.connect(self.url)
        await socket.send(hello(player, client))
        return socket, json.loads(await asyncio.wait_for(socket.recv(), 3))

    async def test_a_live_slot_rejects_anyone_else(self):
        one, _ = await self.join(1, "phone-a")
        try:
            intruder, _ = None, None
            intruder = await websockets.connect(self.url)
            await intruder.send(hello(1, "phone-b"))
            with self.assertRaises(websockets.exceptions.ConnectionClosed) as closed:
                await asyncio.wait_for(intruder.recv(), 3)
            self.assertEqual(closed.exception.rcvd.code, 1008)
        finally:
            await one.close()

    async def test_a_free_slot_can_be_taken_by_a_reinstalled_app(self):
        one, _ = await self.join(1, "phone-before-reinstall")
        await one.close()
        for _ in range(50):              # wait for the server to release the slot
            if 1 not in self.hub.active:
                break
            await asyncio.sleep(0.02)
        again, welcome = await self.join(1, "phone-after-reinstall")
        try:
            self.assertEqual(welcome["type"], "ServerWelcome")
            self.assertEqual(welcome["player_id"], 1)
        finally:
            await again.close()


class PauseEpochTests(unittest.IsolatedAsyncioTestCase):
    async def punch_with_pause(self, pause_in_between):
        engine = GameEngine()
        engine.start()
        hub = PhoneHub(engine=engine)
        task = asyncio.create_task(hub.request_punch(1, "JAB", 0.9, 1.0,
                                                     response_timeout_ms=2000))
        while not hub.pending:
            await asyncio.sleep(0.01)
        record = next(iter(hub.pending.values()))
        if pause_in_between:
            engine.pause()
            engine.resume()
        record.observation_future.set_result("TARGET_TRACKED")
        return await asyncio.wait_for(task, 3)

    async def test_a_punch_lands_when_nothing_interrupts_it(self):
        event = await self.punch_with_pause(False)
        self.assertEqual((event["outcome"], event["damage"]), ("HIT", 5.0))

    async def test_a_punch_from_before_a_pause_misses_after_it(self):
        event = await self.punch_with_pause(True)
        self.assertEqual((event["outcome"], event["damage"]), ("MISS", 0.0))


if __name__ == "__main__":
    unittest.main()
