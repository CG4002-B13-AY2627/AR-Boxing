"""Tutorial mode (CG4002-Viz docs/protocol.md "Tutorial mode").

LOBBY -START_TUTORIAL-> CALIBRATING -CALIBRATED-> FIGHTING, mode TUTORIAL;
no round clock, no KO, and PRACTICE_PUNCH makes the bag punch back.
"""

import unittest

from game_engine import ROUND_SECONDS, PRACTICE_ITEM_BEARING, PRACTICE_WINDUP_SECONDS, GameEngine
from test_match_flow import FakeClock, contract_validators, joined, to_fighting
from visualizer_protocol import PhoneHub


def tutorial_fighting(engine=None):
    engine = engine or joined(players=(1,), required=1)
    assert engine.command(1, "START_TUTORIAL")
    assert engine.command(1, "CALIBRATED")
    assert engine.phase == "FIGHTING", engine.phase
    return engine


class TutorialEngineTests(unittest.TestCase):
    def test_start_skips_ready_and_the_countdown(self):
        engine = joined(players=(1,), required=1)
        self.assertTrue(engine.command(1, "START_TUTORIAL"))
        self.assertEqual((engine.phase, engine.mode), ("CALIBRATING", "TUTORIAL"))
        self.assertEqual(engine.snapshot()["mode"], "TUTORIAL")
        self.assertTrue(engine.command(1, "CALIBRATED"))
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.snapshot()["phase_remaining_ms"], 0)

    def test_only_in_lobby(self):
        engine = to_fighting(joined(players=(1,), required=1), players=(1,))
        self.assertFalse(engine.command(1, "START_TUTORIAL"), "not mid-match")
        self.assertEqual(engine.mode, "MATCH")

    def test_tutorial_commands_mean_nothing_in_a_match(self):
        engine = to_fighting(joined(players=(1,), required=1), players=(1,))
        self.assertFalse(engine.command(1, "PRACTICE_PUNCH"))
        self.assertFalse(engine.command(1, "EXIT_TUTORIAL"))
        self.assertEqual(engine.phase, "FIGHTING")

    def test_the_round_clock_does_not_run(self):
        engine = tutorial_fighting()
        engine.clock.advance(500)
        engine.advance()
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.round_time, ROUND_SECONDS)

    def test_nobody_is_knocked_out(self):
        engine = tutorial_fighting()
        engine.players[2].health = 4.0
        outcome, damage = engine.resolve_punch(1, "LEFT_UPPERCUT", 1.0, tracked=True)
        self.assertEqual((outcome, damage), ("HIT", 4.0))
        self.assertEqual(engine.players[2].health, 100.0, "the bag refills")
        self.assertEqual(engine.phase, "FIGHTING")

    def test_stamina_regenerates_three_times_faster(self):
        from game_engine import STAMINA_REGEN_PER_SECOND, TUTORIAL_REGEN_MULTIPLIER
        self.assertEqual(TUTORIAL_REGEN_MULTIPLIER, 3.0)
        engine = tutorial_fighting()
        engine.players[1].stamina = 40.0
        engine.clock.advance(2.0)
        engine.advance()
        self.assertEqual(engine.players[1].stamina, 40.0 + 2.0 * STAMINA_REGEN_PER_SECOND * 3.0)

        match = to_fighting(joined(players=(1,), required=1), players=(1,))
        match.players[1].stamina = 40.0
        match.clock.advance(2.0)
        match.advance()
        self.assertEqual(match.players[1].stamina, 40.0 + 2.0 * STAMINA_REGEN_PER_SECOND,
                         "a normal match keeps the slow regen")

    def test_untracked_punches_still_miss(self):
        engine = tutorial_fighting()
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, tracked=False), ("MISS", 0.0))
        self.assertEqual(engine.players[2].health, 100.0)

    def test_practice_punch_lands_after_the_windup(self):
        engine = tutorial_fighting()
        self.assertTrue(engine.command(1, "PRACTICE_PUNCH"))
        self.assertFalse(engine.command(1, "PRACTICE_PUNCH"), "one at a time")
        engine.clock.advance(PRACTICE_WINDUP_SECONDS - 0.1)
        engine.advance()
        self.assertEqual(engine.pop_practice_results(), [])
        engine.clock.advance(0.1)
        engine.advance()
        [result] = engine.pop_practice_results()
        self.assertEqual((result["source_player"], result["target_player"]), (2, 1))
        self.assertEqual((result["punch"], result["outcome"], result["damage"]),
                         ("JAB", "HIT", 3.0))
        self.assertEqual(engine.players[1].health, 97.0)
        self.assertTrue(engine.command(1, "PRACTICE_PUNCH"), "free again")

    def test_guarding_when_it_lands_blocks(self):
        engine = tutorial_fighting()
        engine.command(1, "PRACTICE_PUNCH")
        engine.clock.advance(PRACTICE_WINDUP_SECONDS - 0.5)
        self.assertTrue(engine.start_guard(1))
        engine.clock.advance(0.5)
        engine.advance()
        [result] = engine.pop_practice_results()
        self.assertEqual((result["outcome"], result["damage"]), ("BLOCK", 0.75))

    def test_the_bag_cycles_punch_types(self):
        engine = tutorial_fighting()
        punches = []
        for _ in range(4):
            engine.command(1, "PRACTICE_PUNCH")
            engine.clock.advance(PRACTICE_WINDUP_SECONDS)
            engine.advance()
            punches.append(engine.pop_practice_results()[0]["punch"])
        self.assertEqual(punches, ["JAB", "LEFT_HOOK", "LEFT_UPPERCUT", "JAB"])

    def test_pause_cancels_a_pending_practice_punch_and_resume_skips_countdown(self):
        engine = tutorial_fighting()
        engine.command(1, "PRACTICE_PUNCH")
        self.assertTrue(engine.command(1, "PAUSE"))
        self.assertEqual((engine.phase, engine.mode), ("PAUSED", "TUTORIAL"))
        self.assertFalse(engine.command(1, "RESTART"), "exit, don't restart")
        self.assertTrue(engine.command(1, "RESUME"))
        self.assertEqual(engine.phase, "FIGHTING")
        engine.clock.advance(PRACTICE_WINDUP_SECONDS)
        engine.advance()
        self.assertEqual(engine.pop_practice_results(), [])

    def test_exit_returns_to_a_fresh_lobby(self):
        engine = tutorial_fighting()
        engine.players[1].health = 40.0
        engine.command(1, "PRACTICE_PUNCH")
        self.assertTrue(engine.command(1, "EXIT_TUTORIAL"))
        state = engine.snapshot()
        self.assertEqual((state["state"], state["mode"]), ("LOBBY", "MATCH"))
        self.assertEqual(state["player_1"]["health"], 100.0)
        engine.clock.advance(PRACTICE_WINDUP_SECONDS)
        engine.advance()
        self.assertEqual(engine.pop_practice_results(), [])

    def test_the_last_player_leaving_ends_the_tutorial(self):
        engine = tutorial_fighting()
        engine.set_connected(1, False)
        self.assertEqual((engine.phase, engine.mode), ("LOBBY", "MATCH"))


class TwoPlayerTutorialTests(unittest.TestCase):
    """A --players 2 server: each player can do the tutorial in turn."""

    def test_snapshot_names_whose_tutorial_it_is(self):
        engine = tutorial_fighting(joined(required=2))
        self.assertEqual(engine.snapshot()["tutorial_player"], 1)
        engine.command(1, "EXIT_TUTORIAL")
        self.assertNotIn("tutorial_player", engine.snapshot())

    def test_players_take_turns_without_a_restart(self):
        engine = joined(required=2)
        tutorial_fighting(engine)
        self.assertFalse(engine.command(2, "START_TUTORIAL"), "one tutorial at a time")
        self.assertTrue(engine.command(1, "EXIT_TUTORIAL"))
        self.assertEqual((engine.phase, engine.mode), ("LOBBY", "MATCH"))
        self.assertTrue(engine.command(2, "START_TUTORIAL"))
        self.assertEqual(engine.tutorial_player, 2)
        self.assertTrue(engine.command(2, "CALIBRATED"))
        engine.command(2, "PRACTICE_PUNCH")
        engine.clock.advance(PRACTICE_WINDUP_SECONDS)
        engine.advance()
        [result] = engine.pop_practice_results()
        self.assertEqual((result["source_player"], result["target_player"]), (1, 2),
                         "P1's slot is the bag now")
        engine.command(2, "EXIT_TUTORIAL")
        to_fighting(engine)
        self.assertEqual((engine.phase, engine.mode), ("FIGHTING", "MATCH"), "then a normal match")

    def test_the_other_player_can_not_act_during_it(self):
        engine = tutorial_fighting(joined(required=2))
        for command in ("READY", "PAUSE", "PRACTICE_PUNCH", "PRACTICE_ITEM", "EXIT_TUTORIAL"):
            self.assertFalse(engine.command(2, command), command)
        self.assertFalse(engine.try_attack(2, "JAB"), "no punches at the player")
        self.assertFalse(engine.start_guard(2))
        self.assertIsNone(engine.spawn_item(2, "HEALTH"))
        self.assertEqual(engine.phase, "FIGHTING")

    def test_the_other_player_leaving_or_joining_never_pauses_it(self):
        engine = tutorial_fighting(joined(required=2))
        engine.set_connected(2, False)
        self.assertEqual((engine.phase, engine.mode), ("FIGHTING", "TUTORIAL"))
        engine.set_connected(2, True)
        self.assertEqual(engine.phase, "FIGHTING")

    def test_the_tutorial_player_leaving_returns_everyone_to_the_lobby(self):
        engine = tutorial_fighting(joined(required=2))
        engine.set_connected(1, False)
        self.assertEqual((engine.phase, engine.mode), ("LOBBY", "MATCH"))
        self.assertTrue(engine.players[2].connected)
        self.assertTrue(engine.command(2, "START_TUTORIAL"), "the other player can go next")

    def test_a_normal_match_after_the_tutorial_still_ends(self):
        engine = tutorial_fighting()
        engine.command(1, "EXIT_TUTORIAL")
        to_fighting(engine, players=(1,))
        engine.clock.advance(ROUND_SECONDS)
        engine.advance()
        self.assertEqual(engine.phase, "ROUND_END")


class TutorialItemTests(unittest.TestCase):
    def test_practice_item_spawns_an_attack_boost_beside_the_bag(self):
        engine = tutorial_fighting()
        self.assertTrue(engine.command(1, "PRACTICE_ITEM"))
        [item] = engine.snapshot()["active_items"]
        self.assertEqual((item["item_type"], item["owner_player"]), ("ATTACK_MULTIPLIER", 1))
        self.assertEqual(item["bearing_degrees"], PRACTICE_ITEM_BEARING)
        self.assertEqual(item["bearing_degrees"], -65.0, "the player's left, every time")
        self.assertEqual(item["distance_m"], 1.0)
        self.assertFalse(engine.command(1, "PRACTICE_ITEM"), "one item at a time")

    def test_collecting_it_boosts_damage_on_the_bag(self):
        engine = tutorial_fighting()
        engine.command(1, "PRACTICE_ITEM")
        item_id = engine.snapshot()["active_items"][0]["id"]
        self.assertEqual(engine.collect_item(1, item_id, "AVAILABLE", 0.3)[0], "ACCEPTED")
        self.assertEqual(engine.snapshot()["player_1"]["attack_multiplier"], 1.5)
        self.assertEqual(engine.resolve_punch(1, "JAB", 1.0, tracked=True), ("HIT", 4.5))
        self.assertTrue(engine.command(1, "PRACTICE_ITEM"), "the next one can spawn")

    def test_only_while_the_tutorial_fights(self):
        engine = joined(players=(1,), required=1)
        engine.command(1, "START_TUTORIAL")
        self.assertFalse(engine.command(1, "PRACTICE_ITEM"), "not while calibrating")
        match = to_fighting(joined(players=(1,), required=1), players=(1,))
        self.assertFalse(match.command(1, "PRACTICE_ITEM"), "never in a match")
        self.assertEqual(match.snapshot()["active_items"], [])


class TutorialHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_welcome_state_and_bag_punch_match_the_contract(self):
        validators = contract_validators()
        if not validators:
            self.skipTest("jsonschema or CG4002-Viz contracts unavailable")
        hub = PhoneHub(engine=GameEngine(clock=FakeClock()), required_players=1)
        welcome = hub.welcome(1)
        self.assertIs(welcome["supports_tutorial"], True)
        validators["server-welcome"].validate(welcome)
        self.assertIs(PhoneHub(required_players=2).welcome(1)["supports_tutorial"], True)

        sent = []
        hub.ready[1] = object()

        async def record(message):
            sent.append(message)
            return 1

        hub.broadcast = record
        hub.engine.set_connected(1, True)
        tutorial_fighting(hub.engine)
        validators["match-state"].validate(hub.state())
        hub.engine.command(1, "PRACTICE_PUNCH")
        hub.engine.clock.advance(PRACTICE_WINDUP_SECONDS)
        await hub.broadcast_state()
        events = [m for m in sent if m["type"] == "GameEvent"]
        self.assertEqual(len(events), 1)
        validators["game-event"].validate(events[0])
        self.assertEqual((events[0]["event"], events[0]["outcome"]), ("PUNCH", "HIT"))
        validators["match-state"].validate(sent[-1])
        self.assertEqual(sent[-1]["mode"], "TUTORIAL")


if __name__ == "__main__":
    unittest.main()
