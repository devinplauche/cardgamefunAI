"""Regression tests for champion damage and stun handling.

Two rules bugs found by auditing the engine against the printed rules rather
than assuming it was right:

  "Damage to Champions does not carry over between turns."
  "Once stunned, a Champion is placed in its owner's discard pile."

The engine set current_health once in BoardChampion.__init__ and never reset
it, so chip damage accumulated permanently across turns; and every combat
site filtered dead champions off the board with a list comprehension, so the
card left the game entirely instead of returning to its owner's discard.
"""

import unittest

from hero_engine import (
    BoardChampion,
    HRPlayer,
    load_hero_cards,
    remove_stunned_champions,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")
GUARD = next(c for c in CARDS if c.card_type == "champion" and c.guard > 0 and c.health >= 4)
CHAMP = next(c for c in CARDS if c.card_type == "champion" and c.health >= 3)


class TestStunnedChampionsGoToDiscard(unittest.TestCase):
    def test_stunned_champion_lands_in_its_owners_discard(self):
        player = HRPlayer("P")
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 0

        moved = remove_stunned_champions(player)

        self.assertEqual(player.board, [])
        self.assertEqual(player.discard, [GUARD])
        self.assertEqual(moved, [GUARD])

    def test_living_champions_are_untouched(self):
        player = HRPlayer("P")
        alive = BoardChampion(GUARD)
        dead = BoardChampion(CHAMP)
        dead.current_health = 0
        player.board.extend([alive, dead])

        remove_stunned_champions(player)

        self.assertEqual([bc.card for bc in player.board], [GUARD])
        self.assertEqual(player.discard, [CHAMP])

    def test_no_stunned_champions_is_a_noop(self):
        player = HRPlayer("P")
        player.board.append(BoardChampion(GUARD))
        self.assertEqual(remove_stunned_champions(player), [])
        self.assertEqual(player.discard, [])

    def test_a_stunned_champion_can_be_drawn_again(self):
        """The whole point of going to discard rather than out of the game."""
        player = HRPlayer("P")
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 0
        remove_stunned_champions(player)

        player.deck = []
        drawn = player.draw(1)  # forces a reshuffle of the discard pile
        self.assertEqual(drawn, [GUARD])

    def test_combat_through_the_ai_routes_stunned_champions_to_discard(self):
        from hero_ai import attack_weakest

        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        champion = BoardChampion(GUARD)
        defender.board.append(champion)
        attacker.combat = GUARD.health + 5

        attack_weakest(attacker, defender, [champion])

        self.assertEqual(defender.board, [])
        self.assertIn(GUARD, defender.discard)

    def test_combat_through_the_session_routes_stunned_champions_to_discard(self):
        from web.session import create_session

        session = create_session(seed=7)
        champion = BoardChampion(GUARD)
        session.player.board.append(champion)
        session.active_player = "bot"
        session.phase = "combat"
        session.bot.combat = GUARD.health

        session.attack_target_action("champion", GUARD.id)

        self.assertEqual(session.player.board, [])
        self.assertIn(GUARD, session.player.discard)


class TestChampionDamageDoesNotCarryOver(unittest.TestCase):
    def test_damage_resets_at_the_start_of_the_owners_turn(self):
        from web.session import create_session

        session = create_session(seed=4)
        champion = BoardChampion(GUARD)
        session.bot.board.append(champion)
        champion.current_health = 1

        session._start_turn(session.bot)

        self.assertEqual(champion.current_health, GUARD.health)

    def test_damage_persists_within_a_single_turn(self):
        """Only *between* turns does damage clear - a guard chipped twice in
        one turn must still be chipped."""
        from web.session import create_session

        session = create_session(seed=7)
        champion = BoardChampion(GUARD)
        session.player.board.append(champion)
        session.active_player = "bot"
        session.phase = "combat"
        session.bot.combat = 1

        session.attack_target_action("champion", GUARD.id)

        self.assertEqual(champion.current_health, GUARD.health - 1)
        self.assertTrue(champion.alive)

    def test_engine_turn_loop_also_resets_damage(self):
        """hero_engine.HRGame.take_turn drives RL training and the benchmark
        AIs, so it needs the same reset as the web session."""
        from hero_ai import BalancedAI
        from hero_engine import HRGame

        player = HRPlayer("P")
        opponent = HRPlayer("O")
        player.setup_starting_deck()
        opponent.setup_starting_deck()
        player.draw(5)
        champion = BoardChampion(GUARD)
        player.board.append(champion)
        champion.current_health = 1

        game = HRGame(player, opponent, list(CARDS))
        ai = BalancedAI()
        game.take_turn(player, opponent, ai.buy, ai.play, ai.attack)

        self.assertEqual(champion.current_health, GUARD.health)


if __name__ == "__main__":
    unittest.main()
