"""Restarting a match: "Play again" at MATCH_END and "Restart match" while PAUSED."""

import asyncio
import json
import unittest

import websockets

import visualizer_protocol
from game_engine import GameEngine
from test_match_flow import FakeClock, Phone, contract_validators, joined, to_fighting
from visualizer_protocol import PhoneHub


def to_match_end(engine):
    to_fighting(engine)
    engine.players[2].health = 40.0
    engine.clock.advance(90)
    engine.advance()
    engine.clock.advance(2)
    engine.advance()
    assert engine.phase == "MATCH_END", engine.phase
    return engine


class EngineRestartTests(unittest.TestCase):
    def test_match_end_waits_for_every_connected_player(self):
        engine = to_match_end(joined())
        self.assertEqual(engine.snapshot()["match_result"], "P1_WIN")
        self.assertTrue(engine.command(1, "RESTART"))
        self.assertEqual(engine.phase, "MATCH_END", "P2 is still reading the result")
        self.assertTrue(engine.snapshot()["player_1"]["ready"], "phones show 'Waiting for P2'")
        self.assertFalse(engine.command(1, "RESTART"), "Play again counts once")
        self.assertTrue(engine.command(2, "RESTART"))
        self.assertEqual(engine.phase, "LOBBY")
        self.assertEqual(engine.match_number, 2)

    def test_a_fresh_match_has_full_health_time_and_no_result(self):
        engine = to_match_end(joined())
        engine.players[1].stamina = 3.0
        engine.command(1, "RESTART")
        engine.command(2, "RESTART")
        state = engine.snapshot()
        self.assertEqual((state["player_1"]["health"], state["player_2"]["health"]), (100.0, 100.0))
        self.assertEqual(state["player_1"]["stamina"], 100.0)
        self.assertEqual(state["round_time"], 90.0)
        self.assertEqual(state["match_result"], "PENDING")
        self.assertEqual(state["active_items"], [])
        self.assertTrue(state["player_1"]["connected"] and state["player_2"]["connected"])
        self.assertFalse(state["player_1"]["ready"] or state["player_2"]["ready"])

    def test_the_next_match_plays_normally(self):
        engine = to_match_end(joined())
        engine.command(1, "RESTART")
        engine.command(2, "RESTART")
        to_fighting(engine)
        self.assertEqual(engine.phase, "FIGHTING")
        engine.clock.advance(10)
        engine.advance()
        self.assertEqual(engine.round_time, 80.0)

    def test_a_player_leaving_the_result_does_not_block_the_other(self):
        engine = to_match_end(joined())
        engine.command(1, "RESTART")
        engine.set_connected(2, False)            # P2 pressed Title or dropped
        self.assertEqual(engine.phase, "LOBBY")
        engine.set_connected(2, True)
        self.assertEqual(engine.phase, "LOBBY", "the leaver comes back to the lobby")

    def test_everyone_leaving_the_result_resets(self):
        engine = to_match_end(joined())
        engine.set_connected(1, False)
        self.assertEqual(engine.phase, "MATCH_END", "P2 is still looking at the result")
        engine.set_connected(2, False)
        self.assertEqual(engine.phase, "LOBBY")

    def test_either_player_restarts_from_pause_at_once(self):
        engine = to_fighting(joined())
        engine.players[1].health = 30.0
        engine.command(2, "PAUSE")
        self.assertTrue(engine.command(1, "RESTART"))
        self.assertEqual(engine.phase, "LOBBY")
        self.assertEqual(engine.players[1].health, 100.0)

    def test_restart_while_the_opponent_is_away(self):
        engine = to_fighting(joined())
        engine.set_connected(2, False)            # paused by the drop
        self.assertTrue(engine.command(1, "RESTART"))
        self.assertEqual(engine.phase, "LOBBY")
        self.assertFalse(engine.players[2].connected)

    def test_restart_is_ignored_everywhere_else(self):
        engine = joined()
        self.assertFalse(engine.command(1, "RESTART"), "LOBBY")
        engine.command(1, "READY")
        engine.command(2, "READY")
        self.assertFalse(engine.command(1, "RESTART"), "CALIBRATING")
        engine.command(1, "CALIBRATED")
        engine.command(2, "CALIBRATED")
        self.assertFalse(engine.command(1, "RESTART"), "COUNTDOWN")
        engine.clock.advance(3)
        engine.advance()
        self.assertFalse(engine.command(1, "RESTART"), "FIGHTING: pause first")
        engine.players[2].health = 0.1
        engine.try_attack(1, "JAB")
        engine.resolve_punch(1, "JAB", 1.0, True)
        self.assertEqual(engine.phase, "ROUND_END")
        self.assertFalse(engine.command(1, "RESTART"), "ROUND_END")
        self.assertEqual(engine.match_number, 1)

    def test_item_ids_never_repeat_across_matches(self):
        engine = to_fighting(joined())
        first = engine.spawn_health(1).item_id
        engine.command(1, "PAUSE")
        engine.command(1, "RESTART")
        to_fighting(engine)
        self.assertNotEqual(engine.spawn_health(1).item_id, first)

    def test_one_player_mode_restarts_alone(self):
        engine = to_match_end(joined(players=(1,), required=1))
        engine.command(1, "RESTART")
        self.assertEqual(engine.phase, "LOBBY")

    def test_snapshots_after_a_restart_match_the_contract(self):
        validators = contract_validators()
        if "match-state" not in validators:
            self.skipTest("jsonschema or CG4002-Viz contracts unavailable")
        hub = PhoneHub(engine=to_match_end(joined()))
        hub.engine.command(1, "RESTART")
        validators["match-state"].validate(hub.state())   # ready in MATCH_END
        hub.engine.command(2, "RESTART")
        validators["match-state"].validate(hub.state())


class HubRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_pending_punch_misses_and_ledgers_are_pruned(self):
        engine = to_fighting(joined())
        hub = PhoneHub(engine=engine)
        await hub.request_guard(2, True, guard_id="old-guard")
        task = asyncio.create_task(hub.request_punch(1, "JAB", 0.9, 1.0,
                                                     response_timeout_ms=2000, attack_id="old"))
        while not hub.pending:
            await asyncio.sleep(0.01)
        record = hub.pending["old"]
        engine.command(1, "PAUSE")
        match = engine.match_number
        engine.command(1, "RESTART")
        await hub._after_reset_locked(match)
        self.assertEqual(hub.guard_actions, {})
        self.assertIn("old", hub.attacks, "still pending, so kept until it resolves")
        record.observation_future.set_result("TARGET_TRACKED")
        event = await asyncio.wait_for(task, 3)
        self.assertEqual((event["outcome"], event["damage"]), ("MISS", 0.0))
        self.assertEqual(engine.players[2].health, 100.0)

    async def test_a_pending_pickup_check_is_cancelled_by_the_reset(self):
        engine = to_fighting(joined())
        hub = PhoneHub(engine=engine)
        server = await websockets.serve(hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
        try:
            one = Phone(await websockets.connect(url), 1)
            await one.join()
            await hub.spawn_health(1)
            await hub.request_pickup(1, "act-1")
            await hub.operator_pause()
            await one.send("RESTART")

            async def result():
                while True:
                    message = json.loads(await one.socket.recv())
                    if message["type"] == "PickupResult":
                        return message
            cancelled = await asyncio.wait_for(result(), 3)
            self.assertEqual(cancelled["reason"], "MATCH_NOT_ACTIVE")
            lobby = await one.state_where(lambda s: s["state"] == "LOBBY")
            self.assertEqual(lobby["active_items"], [])
            self.assertEqual(hub.pickups, {})
            await one.socket.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_play_again_over_sockets_keeps_the_stream(self):
        clock = FakeClock()
        hub = PhoneHub(engine=GameEngine(clock=clock))
        server = await websockets.serve(hub.handle, "127.0.0.1", 0)
        url = "ws://127.0.0.1:" + str(server.sockets[0].getsockname()[1])
        try:
            one = Phone(await websockets.connect(url), 1)
            two = Phone(await websockets.connect(url), 2)
            await one.join()
            await two.join()
            to_match_end(hub.engine)
            await hub.broadcast_state()
            ended = await one.state_where(lambda s: s["state"] == "MATCH_END")
            await one.send("RESTART")
            waiting = await two.state_where(lambda s: s["player_1"]["ready"])
            self.assertEqual(waiting["state"], "MATCH_END")
            await two.send("RESTART")
            lobby = await one.state_where(lambda s: s["state"] == "LOBBY")
            self.assertEqual(lobby["stream_id"], ended["stream_id"])
            self.assertEqual(lobby["match_id"], ended["match_id"])
            self.assertGreater(lobby["seq"], ended["seq"], "phones keep their sequence gates")
            self.assertEqual(lobby["player_2"]["health"], 100.0)
            await one.socket.close()
            await two.socket.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_operator_reset_and_auto_start(self):
        engine = to_match_end(joined(players=(1,), required=1))
        hub = PhoneHub(engine=engine, required_players=1, auto_start=True)
        hub.ready[1] = object()       # a phone is connected
        sent = []
        visualizer_protocol_send = visualizer_protocol.send_bounded

        async def record(socket, payload):
            sent.append(json.loads(payload))
            return True
        visualizer_protocol.send_bounded = record
        try:
            await hub.operator_reset()
        finally:
            visualizer_protocol.send_bounded = visualizer_protocol_send
        self.assertEqual(engine.phase, "FIGHTING", "auto-start goes straight into the next fight")
        self.assertEqual(engine.match_number, 2)
        self.assertEqual(sent[-1]["state"], "FIGHTING")


if __name__ == "__main__":
    unittest.main()
