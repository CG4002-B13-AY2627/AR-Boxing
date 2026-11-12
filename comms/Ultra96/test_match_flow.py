"""Match flow driven by phone PlayerCommands (CG4002-Viz docs/protocol.md).

LOBBY -all READY-> CALIBRATING -all CALIBRATED-> COUNTDOWN -timer-> FIGHTING
FIGHTING -PAUSE or disconnect-> PAUSED -all RESUME-> COUNTDOWN
FIGHTING -KO or time-> ROUND_END -> MATCH_END
"""

import asyncio
import itertools
import json
import os
import unittest
from pathlib import Path

import websockets

from game_engine import ROUND_SECONDS, GameEngine
from visualizer_protocol import PhoneHub, decode_command


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def contract_validators():
    """Validators from the canonical CG4002-Viz contracts, or {} when unavailable."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return {}
    default = Path(__file__).resolve().parents[3] / "CG4002-Viz" / "contracts"
    contracts = Path(os.environ.get("CG4002_CONTRACTS_DIR", default))
    validators = {}
    for name in ("server-welcome", "match-state", "player-command", "game-event"):
        path = contracts / f"{name}.schema.json"
        if path.is_file():
            validators[name] = Draft202012Validator(json.loads(path.read_text(encoding="utf8")))
    return validators


def joined(players=(1, 2), required=2, clock=None):
    engine = GameEngine(clock=clock or FakeClock(), required_players=required)
    for player in players:
        engine.set_connected(player, True)
    return engine


def to_fighting(engine, players=(1, 2)):
    for player in players:
        engine.command(player, "READY")
    for player in players:
        engine.command(player, "CALIBRATED")
    engine.clock.advance(engine.countdown_seconds)
    engine.advance()
    return engine


class EngineMatchFlowTests(unittest.TestCase):
    def test_everyone_ready_moves_lobby_to_calibrating_and_clears_flags(self):
        engine = joined()
        self.assertTrue(engine.command(1, "READY"))
        self.assertEqual(engine.phase, "LOBBY")
        self.assertTrue(engine.snapshot()["player_1"]["ready"])
        engine.command(2, "READY")
        self.assertEqual(engine.phase, "CALIBRATING")
        snapshot = engine.snapshot()
        self.assertFalse(snapshot["player_1"]["ready"] or snapshot["player_2"]["ready"])

    def test_one_required_player_can_start_alone(self):
        engine = joined(players=(1,), required=1)
        engine.command(1, "READY")
        self.assertEqual(engine.phase, "CALIBRATING")

    def test_two_required_players_wait_for_the_second_phone(self):
        engine = joined(players=(1,), required=2)
        engine.command(1, "READY")
        self.assertEqual(engine.phase, "LOBBY")
        engine.set_connected(2, True)
        engine.command(2, "READY")
        self.assertEqual(engine.phase, "CALIBRATING")

    def test_unready_takes_the_flag_back(self):
        engine = joined()
        engine.command(1, "READY")
        self.assertTrue(engine.command(1, "UNREADY"))
        engine.command(2, "READY")
        self.assertEqual(engine.phase, "LOBBY")

    def test_countdown_then_fighting_without_running_the_round_clock(self):
        engine = joined()
        for player in (1, 2):
            engine.command(player, "READY")
        engine.command(1, "CALIBRATED")
        engine.command(2, "CALIBRATED")
        self.assertEqual(engine.phase, "COUNTDOWN")
        self.assertEqual(engine.snapshot()["phase_remaining_ms"], 3000)
        engine.clock.advance(1.25)
        self.assertEqual(engine.snapshot()["phase_remaining_ms"], 1750)
        engine.clock.advance(1.75)
        engine.advance()
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.round_time, ROUND_SECONDS)
        self.assertEqual(engine.snapshot()["phase_remaining_ms"], 0)

    def test_pause_freezes_the_clock_and_resume_needs_everyone(self):
        engine = to_fighting(joined())
        engine.clock.advance(10)
        self.assertTrue(engine.command(2, "PAUSE"))
        self.assertEqual(engine.phase, "PAUSED")
        self.assertEqual(engine.round_time, ROUND_SECONDS - 10)
        engine.clock.advance(30)
        engine.advance()
        self.assertEqual(engine.round_time, ROUND_SECONDS - 10)
        engine.command(1, "RESUME")
        self.assertEqual(engine.phase, "PAUSED")
        engine.command(2, "RESUME")
        self.assertEqual(engine.phase, "COUNTDOWN")
        engine.clock.advance(3)
        engine.advance()
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.round_time, ROUND_SECONDS - 10)

    def test_disconnect_pauses_fighting_and_countdown_and_drops_ready(self):
        engine = to_fighting(joined())
        engine.set_connected(2, False)
        self.assertEqual(engine.phase, "PAUSED")
        self.assertFalse(engine.snapshot()["player_2"]["connected"])
        engine.command(1, "RESUME")
        self.assertEqual(engine.phase, "PAUSED", "needs the second phone back")
        engine.set_connected(2, True)
        self.assertEqual(engine.phase, "PAUSED", "reconnecting never resumes by itself")
        engine.command(2, "RESUME")
        self.assertEqual(engine.phase, "COUNTDOWN")
        engine.set_connected(1, False)
        self.assertEqual(engine.phase, "PAUSED")

    def test_disconnect_in_lobby_drops_the_ready_flag(self):
        engine = joined()
        engine.command(1, "READY")
        engine.set_connected(1, False)
        engine.set_connected(1, True)
        engine.command(2, "READY")
        self.assertEqual(engine.phase, "LOBBY")

    def test_commands_that_mean_nothing_now_are_ignored(self):
        engine = joined()
        self.assertFalse(engine.command(1, "CALIBRATED"))
        self.assertFalse(engine.command(1, "PAUSE"))
        self.assertFalse(engine.command(1, "RESUME"))
        self.assertFalse(engine.command(1, "SURRENDER"))
        engine.set_connected(2, False)
        self.assertFalse(engine.command(2, "READY"), "disconnected players can't vote")
        self.assertEqual(engine.phase, "LOBBY")

    def test_knockout_ends_the_match_with_the_server_result(self):
        engine = to_fighting(joined())
        engine.players[2].health = 1.0
        engine.try_attack(1, "JAB")
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, True), ("HIT", 1.0))
        self.assertEqual(engine.phase, "ROUND_END")
        self.assertEqual(engine.snapshot()["phase_remaining_ms"], 2000)
        self.assertEqual(engine.snapshot()["match_result"], "PENDING")
        engine.clock.advance(2)
        engine.advance()
        self.assertEqual(engine.phase, "MATCH_END")
        self.assertEqual(engine.snapshot()["match_result"], "P1_WIN")
        self.assertFalse(engine.command(1, "READY"), "MATCH_END is final")

    def test_time_out_with_equal_health_is_a_draw(self):
        engine = to_fighting(joined())
        engine.clock.advance(ROUND_SECONDS)
        engine.advance()
        engine.clock.advance(2)
        engine.advance()
        self.assertEqual(engine.snapshot()["match_result"], "DRAW")

    def test_every_phase_snapshot_matches_the_contract(self):
        validators = contract_validators()
        if "match-state" not in validators:
            self.skipTest("jsonschema or CG4002-Viz contracts unavailable")
        hub = PhoneHub(engine=joined())
        engine = hub.engine
        seen = []

        def check():
            validators["match-state"].validate(hub.state())
            seen.append(engine.phase)

        check()
        for player in (1, 2):
            engine.command(player, "READY")
        check()
        for player in (1, 2):
            engine.command(player, "CALIBRATED")
        check()
        engine.clock.advance(3)
        engine.advance()
        check()
        engine.command(1, "PAUSE")
        check()
        engine.players[2].health = 0.5
        for player in (1, 2):
            engine.command(player, "RESUME")
        engine.clock.advance(3)
        engine.advance()
        engine.try_attack(1, "JAB")
        engine.resolve_punch(1, "JAB", 1.0, True)
        check()
        engine.clock.advance(2)
        engine.advance()
        check()
        self.assertEqual(seen, ["LOBBY", "CALIBRATING", "COUNTDOWN", "FIGHTING",
                                "PAUSED", "ROUND_END", "MATCH_END"])


class CommandDecodeTests(unittest.TestCase):
    def command(self, **changes):
        value = {
            "type": "PlayerCommand", "protocol_version": 2,
            "match_id": "match-demo-001", "stream_id": "ultra96-abc",
            "player_id": 1, "command_id": "p1-cmd-0001", "command": "READY",
            "timestamp": 12345,
        }
        value.update(changes)
        return json.dumps(value)

    def test_canonical_command_decodes_and_matches_the_contract(self):
        self.assertIsNotNone(decode_command(self.command()))
        validators = contract_validators()
        if "player-command" in validators:
            validators["player-command"].validate(json.loads(self.command()))

    def test_noncanonical_commands_are_rejected(self):
        for raw in (
            self.command(command="SURRENDER"),
            self.command(player_id=3),
            self.command(protocol_version=1),
            self.command(timestamp=-1),
            self.command(command_id="bad id"),
            self.command(extra=True),
            "not json",
            "[]",
        ):
            self.assertIsNone(decode_command(raw), raw)


def hello(player, client=None):
    return json.dumps({"type": "ClientHello", "protocol_version": 2,
                       "client_id": client or f"phone-{player}", "player_id": player})


class Phone:
    """Minimal test phone: hello, welcome, then commands and state reads."""

    ids = itertools.count(1)

    def __init__(self, socket, player):
        self.socket = socket
        self.player = player
        self.welcome = None

    async def join(self):
        await self.socket.send(hello(self.player))
        self.welcome = json.loads(await asyncio.wait_for(self.socket.recv(), 3))
        return self.welcome

    async def send(self, command, command_id=None, **changes):
        message = {
            "type": "PlayerCommand", "protocol_version": 2,
            "match_id": self.welcome["match_id"], "stream_id": self.welcome["stream_id"],
            "player_id": self.player,
            "command_id": command_id or f"p{self.player}-cmd-{next(self.ids):04d}",
            "command": command, "timestamp": 1,
        }
        message.update(changes)
        await self.socket.send(json.dumps(message))

    async def state_where(self, predicate, seconds=3):
        """Read until a MatchState satisfies predicate (events are skipped)."""
        async def read():
            while True:
                message = json.loads(await self.socket.recv())
                if message["type"] == "MatchState" and predicate(message):
                    return message
        return await asyncio.wait_for(read(), seconds)


class SocketMatchFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.hub = PhoneHub(engine=GameEngine(clock=self.clock))
        self.server = await websockets.serve(self.hub.handle, "127.0.0.1", 0)
        self.url = "ws://127.0.0.1:" + str(self.server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def phone(self, player):
        socket = await websockets.connect(self.url)
        phone = Phone(socket, player)
        await phone.join()
        return phone

    async def test_welcome_advertises_commands_and_matches_the_contract(self):
        one = await self.phone(1)
        try:
            self.assertIs(one.welcome["supports_player_commands"], True)
            validators = contract_validators()
            if "server-welcome" in validators:
                validators["server-welcome"].validate(one.welcome)
            state = await one.state_where(lambda s: True)
            self.assertEqual(state["state"], "LOBBY")
            self.assertTrue(state["player_1"]["connected"])
            self.assertFalse(state["player_2"]["connected"])
        finally:
            await one.socket.close()

    async def test_phones_drive_lobby_to_fighting(self):
        one, two = await self.phone(1), await self.phone(2)
        try:
            await one.state_where(lambda s: s["player_2"]["connected"])
            await one.send("READY")
            await two.send("READY")
            await one.state_where(lambda s: s["state"] == "CALIBRATING")
            await one.send("CALIBRATED")
            await two.send("CALIBRATED")
            countdown = await two.state_where(lambda s: s["state"] == "COUNTDOWN")
            self.assertEqual(countdown["phase_remaining_ms"], 3000)
            self.clock.advance(3)
            await self.hub.broadcast_state()
            await one.state_where(lambda s: s["state"] == "FIGHTING")
        finally:
            await one.socket.close()
            await two.socket.close()

    async def test_bad_or_foreign_input_is_ignored_and_the_socket_stays(self):
        one, two = await self.phone(1), await self.phone(2)
        try:
            await one.socket.send("not json")
            await one.socket.send(json.dumps({"type": "Mystery"}))
            await one.send("READY", player_id=2)           # someone else's slot
            await one.send("READY", stream_id="old-stream")  # stale stream
            await one.send("SURRENDER")
            await one.send("READY")                          # the one valid command
            state = await one.state_where(lambda s: s["player_1"]["ready"])
            self.assertFalse(state["player_2"]["ready"])
            self.assertEqual(state["state"], "LOBBY")
        finally:
            await one.socket.close()
            await two.socket.close()

    async def test_a_repeated_command_id_is_a_retry(self):
        one, two = await self.phone(1), await self.phone(2)
        try:
            await one.send("READY", command_id="p1-cmd-same")
            await one.state_where(lambda s: s["player_1"]["ready"])
            await one.send("UNREADY", command_id="p1-cmd-same")
            await one.send("READY", command_id="p1-cmd-marker")  # no change, still a state
            await asyncio.sleep(0.1)
            self.assertTrue(self.hub.engine.players[1].ready)
        finally:
            await one.socket.close()
            await two.socket.close()

    async def test_a_phone_leaving_mid_fight_pauses_the_other(self):
        one, two = await self.phone(1), await self.phone(2)
        try:
            for command in ("READY", "CALIBRATED"):
                await one.send(command)
                await two.send(command)
                await one.state_where(lambda s: s["state"] in ("CALIBRATING", "COUNTDOWN"))
            await one.state_where(lambda s: s["state"] == "COUNTDOWN")
            self.clock.advance(3)
            await self.hub.broadcast_state()
            await one.state_where(lambda s: s["state"] == "FIGHTING")
            await two.socket.close()
            paused = await one.state_where(lambda s: s["state"] == "PAUSED")
            self.assertFalse(paused["player_2"]["connected"])
        finally:
            await one.socket.close()


if __name__ == "__main__":
    unittest.main()
