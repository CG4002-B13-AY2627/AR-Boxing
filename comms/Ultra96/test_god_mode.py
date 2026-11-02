"""God-mode demo rules with a fake clock; no ESP, FPGA or phones required."""

import unittest

from game_engine import GameEngine
from test_match_flow import FakeClock, to_fighting


class GodModeTests(unittest.TestCase):
    def fighting(self, enabled=True, required=2):
        engine = GameEngine(clock=FakeClock(), round_seconds=5,
                            required_players=required, god_mode=enabled)
        players = tuple(range(1, required + 1))
        for player in players:
            engine.set_connected(player, True)
        return to_fighting(engine, players=players)

    def test_both_players_survive_and_damage_matches_hp_lost(self):
        engine = self.fighting()
        for source in (1, 2):
            target = engine.players[3 - source]
            target.health = 4.0
            self.assertEqual(engine.resolve_punch(source, "LEFT_UPPERCUT", 1, True),
                             ("HIT", 3.0))
            self.assertEqual(target.health, 1.0)
            self.assertEqual(engine.resolve_punch(source, "JAB", 1, True),
                             ("HIT", 0.0))
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.pop_transitions(), [])

    def test_timer_frozen_but_stamina_and_item_clock_keep_running(self):
        engine = self.fighting()
        self.assertTrue(engine.try_attack(1, "LEFT_UPPERCUT"))
        self.assertLess(engine.players[1].stamina, 100)
        self.assertIsNotNone(engine.spawn_health(1))
        engine.clock.advance(120)  # longer than both the round and pickup lifetime
        engine.advance()
        self.assertEqual(engine.round_time, 5)
        self.assertEqual(engine.phase, "FIGHTING")
        self.assertEqual(engine.fight_seconds, 120)
        self.assertEqual(engine.players[1].stamina, 100)
        self.assertEqual(engine.items, {})

    def test_misses_guard_cooldown_and_low_stamina_still_apply(self):
        engine = self.fighting()
        self.assertEqual(engine.resolve_punch(1, "JAB", 1, False), ("MISS", 0))
        self.assertTrue(engine.start_guard(2))
        self.assertEqual(engine.resolve_punch(1, "JAB", 1, True), ("BLOCK", 1.5))
        self.assertTrue(engine.try_attack(1, "JAB"))
        self.assertFalse(engine.try_attack(1, "JAB"))
        engine.players[1].stamina = 0
        engine.clock.advance(0.5)
        self.assertFalse(engine.try_attack(1, "JAB"))

    def test_pickups_heal_a_protected_player(self):
        engine = self.fighting()
        engine.players[1].health = 1
        item = engine.spawn_health(1)
        self.assertEqual(engine.collect_health(1, item.item_id, "AVAILABLE", 0.2),
                         ("ACCEPTED", 25))
        self.assertEqual(engine.players[1].health, 26)

    def test_disconnect_pause_resume_and_reset_keep_the_launch_setting(self):
        engine = self.fighting()
        engine.set_connected(2, False)
        self.assertEqual(engine.phase, "PAUSED")
        before = engine.fight_seconds
        engine.clock.advance(50)
        engine.advance()
        self.assertEqual(engine.fight_seconds, before)
        engine.set_connected(2, True)
        for player in (1, 2):
            self.assertTrue(engine.command(player, "RESUME"))
        self.assertEqual(engine.phase, "COUNTDOWN")
        engine.clock.advance(engine.countdown_seconds)
        engine.advance()
        self.assertEqual(engine.phase, "FIGHTING")
        engine.pause()
        self.assertTrue(engine.command(1, "RESTART"))
        self.assertTrue(engine.god_mode)
        self.assertEqual(engine.phase, "LOBBY")
        self.assertEqual(engine.players[1].health, 100)
        to_fighting(engine)
        engine.clock.advance(100)
        engine.advance()
        self.assertEqual(engine.phase, "FIGHTING")

    def test_single_phone_match_is_protected(self):
        engine = self.fighting(required=1)
        engine.players[2].health = 2
        self.assertEqual(engine.resolve_punch(1, "JAB", 1, True), ("HIT", 1))
        self.assertEqual(engine.phase, "FIGHTING")

    def test_tutorial_refill_stays_separate_and_exit_restores_god_match(self):
        engine = GameEngine(clock=FakeClock(), required_players=1, god_mode=True)
        engine.set_connected(1, True)
        self.assertTrue(engine.command(1, "START_TUTORIAL"))
        self.assertTrue(engine.command(1, "CALIBRATED"))
        engine.players[2].health = 4
        self.assertEqual(engine.resolve_punch(1, "LEFT_UPPERCUT", 1, True), ("HIT", 4))
        self.assertEqual(engine.players[2].health, 100)
        self.assertTrue(engine.command(1, "EXIT_TUTORIAL"))
        self.assertEqual(engine.mode, "MATCH")
        self.assertTrue(engine.god_mode)

    def test_default_full_play_still_ends_by_ko_or_time(self):
        for ending in ("ko", "time"):
            with self.subTest(ending=ending):
                engine = self.fighting(enabled=False)
                if ending == "ko":
                    engine.players[2].health = 4
                    self.assertEqual(engine.resolve_punch(1, "JAB", 1, True), ("HIT", 4))
                    self.assertEqual(engine.players[2].health, 0)
                else:
                    engine.clock.advance(6)
                    engine.advance()
                self.assertEqual(engine.phase, "ROUND_END")
                engine.clock.advance(2)
                engine.advance()
                self.assertEqual(engine.phase, "MATCH_END")


if __name__ == "__main__":
    unittest.main()
