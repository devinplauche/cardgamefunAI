"""Tests for the enemy-board-denial term in evaluate_state.

The term exists because the ROLLOUT_TURNS=4 horizon cannot convert a denied
enemy economy champion into HP, so pure HP-diff is indifferent to killing a
gold engine (measured: MCTS clears Broelyn 0% of the time, the greedy fallback
100%). DENY_BOARD_WEIGHT prices that recurring value. It must default to 0.0
and leave the original eval byte-identical when off.
"""

import unittest

import web.bot as bot
from hero_engine import BoardChampion, load_hero_cards
from web.bot import evaluate_state
from web.session import create_session

CARDS = load_hero_cards("data/hero_realms_cards.json")


def _champ(name):
    return next(c for c in CARDS if c.name == name)


class TestDefaultIsUnchanged(unittest.TestCase):
    def test_weight_defaults_to_zero(self):
        self.assertEqual(bot.DENY_BOARD_WEIGHT, 0.0)

    def test_eval_is_pure_hp_diff_when_off(self):
        s = create_session(seed=1)
        s.bot.hp, s.player.hp = 40, 25
        s.player.board = [BoardChampion(_champ("Broelyn, Loreweaver"))]
        # With the term off, a standing enemy champion must not move the score.
        self.assertEqual(evaluate_state(s), (40 - 25) * 10.0)


class TestTermBehaviour(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, bot, "DENY_BOARD_WEIGHT", 0.0)

    def test_enemy_economy_champion_lowers_the_score(self):
        s = create_session(seed=1)
        s.bot.hp = s.player.hp = 30
        base = evaluate_state(s)
        s.player.board = [BoardChampion(_champ("Broelyn, Loreweaver"))]  # 2 gold/turn
        bot.DENY_BOARD_WEIGHT = 20.0
        self.assertLess(evaluate_state(s), base,
                        "a live enemy economy champion should be a standing negative")

    def test_own_champion_raises_the_score_symmetrically(self):
        s = create_session(seed=1)
        s.bot.hp = s.player.hp = 30
        champ = _champ("Broelyn, Loreweaver")
        bot.DENY_BOARD_WEIGHT = 20.0
        s.bot.board = [BoardChampion(champ)]
        own = evaluate_state(s)
        s.bot.board = []
        s.player.board = [BoardChampion(champ)]
        enemy = evaluate_state(s)
        self.assertAlmostEqual(own - (30 - 30) * 10.0, (30 - 30) * 10.0 - enemy, places=5)

    def test_dead_champion_contributes_nothing(self):
        s = create_session(seed=1)
        s.bot.hp = s.player.hp = 30
        bot.DENY_BOARD_WEIGHT = 20.0
        bc = BoardChampion(_champ("Broelyn, Loreweaver"))
        bc.current_health = 0  # stunned/dead this frame
        s.player.board = [bc]
        self.assertEqual(evaluate_state(s), (30 - 30) * 10.0)

    def test_combat_champion_valued_too(self):
        from web.bot import _champ_recurring_value
        cron = BoardChampion(_champ("Cron, the Berserker"))   # 5 combat
        tithe = BoardChampion(_champ("Tithe Priest"))         # 1 gold
        self.assertGreater(_champ_recurring_value(cron), _champ_recurring_value(tithe))

    def test_winner_short_circuits_before_the_term(self):
        s = create_session(seed=1)
        s.winner = "bot"
        bot.DENY_BOARD_WEIGHT = 20.0
        s.player.board = [BoardChampion(_champ("Broelyn, Loreweaver"))]
        self.assertEqual(evaluate_state(s), bot.WIN_SCORE)


if __name__ == "__main__":
    unittest.main()
