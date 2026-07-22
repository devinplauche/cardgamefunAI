"""Regression tests for the MCTS bot's search loop and session cloning.

All three guard bugs found while building hero_mcts_bench.py:
  1. legal_actions() offered attack_target at 0 combat, which the action
     handler then rejected -> ValueError mid-game.
  2. The MCTS tree cached actions across stochastic redraws, so a cached
     action could be illegal in a later sample -> ValueError mid-search.
  3. clone() deep-copied history/log (full state snapshots) on every search
     iteration, capping MCTS at ~9 iterations per decision.
"""

import random
import unittest

from web.bot import apply_action, choose_bot_action, _heuristic_rollout_action
from web.session import create_session


def _drive(session, steps=400, algorithm="heuristic", budget_ms=10):
    while session.winner is None and steps > 0:
        if session.active_player == "bot":
            action = choose_bot_action(session, budget_ms=budget_ms, algorithm=algorithm)
        else:
            action = _heuristic_rollout_action(session)
        apply_action(session, action)
        steps -= 1
    return session


class TestLegalActions(unittest.TestCase):
    def test_no_attack_actions_without_combat(self):
        random.seed(11)
        session = create_session(seed=11)
        for _ in range(300):
            if session.winner:
                break
            if session.phase == "combat" and session._current().combat <= 0:
                kinds = {a["type"] for a in session.legal_actions()}
                self.assertNotIn("attack_target", kinds)
            apply_action(session, _heuristic_rollout_action(session))

    def test_every_offered_action_is_applicable(self):
        """Whatever legal_actions() lists must not raise when applied."""
        for seed in (3, 21):
            random.seed(seed)
            session = create_session(seed=seed)
            for _ in range(150):
                if session.winner:
                    break
                for action in session.legal_actions():
                    probe = session.clone()
                    try:
                        apply_action(probe, action)
                    except ValueError as exc:
                        self.fail(f"legal action {action['type']} raised: {exc}")
                apply_action(session, _heuristic_rollout_action(session))


class TestClone(unittest.TestCase):
    def test_clone_drops_presentation_state(self):
        session = create_session(seed=5)
        _drive(session, steps=40)
        self.assertTrue(session.history)
        clone = session.clone()
        self.assertEqual(clone.history, [])
        self.assertEqual(clone.log, [])
        self.assertFalse(clone.record_history)

    def test_clone_preserves_original_history(self):
        session = create_session(seed=5)
        _drive(session, steps=40)
        before = len(session.history)
        session.clone()
        self.assertEqual(len(session.history), before)
        self.assertTrue(session.record_history)

    def test_clone_does_not_accumulate_history_during_simulation(self):
        session = create_session(seed=5)
        clone = session.clone()
        _drive(clone, steps=60)
        self.assertEqual(clone.history, [])

    def test_clone_is_independent_of_original(self):
        session = create_session(seed=5)
        clone = session.clone()
        clone.bot.hp = 1
        self.assertEqual(session.bot.hp, 50)


class TestMctsSearch(unittest.TestCase):
    def test_mcts_completes_games_without_raising(self):
        for seed in (1, 2, 3):
            random.seed(seed)
            session = create_session(seed=seed, algorithm="mcts", budget_ms=15)
            _drive(session, steps=400, algorithm="mcts", budget_ms=15)

    def test_mcts_returns_a_currently_legal_action(self):
        random.seed(9)
        session = create_session(seed=9, algorithm="mcts", budget_ms=15)
        for _ in range(60):
            if session.winner:
                break
            if session.active_player == "bot":
                action = choose_bot_action(session, budget_ms=15, algorithm="mcts")
                offered = {a["type"] for a in session.legal_actions()}
                self.assertIn(action["type"], offered)
                apply_action(session, action)
            else:
                apply_action(session, _heuristic_rollout_action(session))


class TestRootSelection(unittest.TestCase):
    """Final action selection must come from the root's own statistics.

    It used to track the best single rollout reward from any node at any depth
    and map it back to a root child by (type, label). "advance_phase" /
    "Next Phase" exists in every phase, so a pass from deep inside a rollout
    matched the root's pass and overrode the search: attacking scored 112.58
    over 59 visits, passing -10.58 over 1 visit, and the bot passed.
    """

    def _combat_state(self, seed, minimum=4):
        random.seed(seed)
        session = create_session(seed=seed, algorithm="mcts", budget_ms=30)
        for _ in range(900):
            if session.winner:
                return None
            if (session.active_player == "bot" and session.phase == "combat"
                    and session.bot.combat >= minimum):
                return session
            apply_action(session, _heuristic_rollout_action(session))
        return None

    def test_attacks_instead_of_passing_with_combat_in_hand(self):
        checked = 0
        for seed in (21, 6, 14):
            session = self._combat_state(seed)
            if session is None:
                continue
            guards = [c for c in session.player.board if c.guard and c.alive]
            if guards:
                continue
            action = choose_bot_action(session, budget_ms=60, algorithm="mcts")
            self.assertEqual(
                action["type"], "attack_target",
                f"passed up {session.bot.combat} combat against an open opponent",
            )
            checked += 1
        self.assertGreater(checked, 0, "no open combat state reached")

    def test_chosen_action_is_the_most_visited_root_child(self):
        session = self._combat_state(21)
        if session is None:
            self.skipTest("no combat state reached")
        result = choose_bot_action(session, budget_ms=60, algorithm="mcts")
        top = result["candidates"][0]
        self.assertEqual(result["type"], top["type"])
        self.assertEqual(result.get("label"), top.get("label"))

    def test_candidates_are_ranked_by_visits(self):
        session = self._combat_state(21)
        if session is None:
            self.skipTest("no combat state reached")
        result = choose_bot_action(session, budget_ms=60, algorithm="mcts")
        visits = [c["visits"] for c in result["candidates"]]
        self.assertEqual(visits, sorted(visits, reverse=True))


class TestEvaluateState(unittest.TestCase):
    """`_card_value` existed but was never called, so evaluate_state had no
    deck-quality term: spending gold was pure loss and passing always won."""

    def _state_with_gold(self, seed, minimum=3):
        random.seed(seed)
        session = create_session(seed=seed)
        for _ in range(400):
            if session.winner:
                return None
            if session.active_player == "bot" and session.phase == "buy" and session.bot.gold >= minimum:
                return session
            apply_action(session, _heuristic_rollout_action(session))
        return None

    def test_buying_scores_better_than_passing(self):
        # Contract of the *shaped* evaluator. The search-priced evaluate_state
        # deliberately does not price a purchase at the leaf; TestSearchPricedEval
        # covers that the rollout does it instead.
        from web.bot import evaluate_state_shaped as evaluate_state

        checked = 0
        for seed in (4, 12, 25, 33):
            session = self._state_with_gold(seed)
            if session is None:
                continue
            base = evaluate_state(session)
            passed = session.clone()
            passed.advance_phase()
            for idx, card in enumerate(session.market.row_cards()):
                if card is None or card.cost > session.bot.gold:
                    continue
                bought = session.clone()
                bought.buy_card_action(idx)
                self.assertGreater(
                    evaluate_state(bought), evaluate_state(passed),
                    f"buying {card.name} scored no better than passing",
                )
                checked += 1
            self.assertAlmostEqual(evaluate_state(passed), base, places=6)
        self.assertGreater(checked, 0, "no purchasable state reached")

    def test_quality_ignores_where_a_card_sits(self):
        from web.bot import _deck_quality

        session = create_session(seed=8)
        before = _deck_quality(session.bot)
        # Moving a card hand -> discard must not change what the player draws from.
        card = session.bot.hand.pop()
        session.bot.discard.append(card)
        self.assertAlmostEqual(_deck_quality(session.bot), before, places=6)

    def test_acquiring_a_strong_card_raises_quality(self):
        from web.bot import _deck_quality

        session = create_session(seed=8)
        before = _deck_quality(session.bot)
        session.bot.discard.append(session.market.row_cards()[0])
        self.assertGreater(_deck_quality(session.bot), before)

    def test_hoarding_junk_lowers_quality(self):
        """A deck of a thousand Gold must not outscore a lean strong deck."""
        from hero_engine import GOLD
        from web.bot import _deck_quality

        session = create_session(seed=8)
        before = _deck_quality(session.bot)
        for _ in range(50):
            session.bot.discard.append(GOLD)
        self.assertLess(_deck_quality(session.bot), before)

    def test_thinning_a_gold_raises_quality(self):
        """Banishing a weak card is a gain, which a total-value model got wrong."""
        from web.bot import _deck_quality

        session = create_session(seed=8)
        pool = session.bot.deck + session.bot.hand + session.bot.discard
        self.assertTrue(any(c.id == "gold" for c in pool))
        before = _deck_quality(session.bot)
        for bucket in (session.bot.deck, session.bot.hand, session.bot.discard):
            gold = next((c for c in bucket if c.id == "gold"), None)
            if gold is not None:
                bucket.remove(gold)
                break
        self.assertGreater(_deck_quality(session.bot), before)


if __name__ == "__main__":
    unittest.main()


class TestSearchPricedEval(unittest.TestCase):
    """Search-priced evaluation asserts no exchange rate between resources.

    The leaf scores only the win condition; what gold, combat, draw and board
    development are worth is whatever the rollout converts them into. That is
    only sound if the rollout runs long enough to see a purchase come back
    around, so the horizon is part of this contract.
    """

    def test_leaf_prices_only_the_win_condition(self):
        from web.bot import evaluate_state

        session = create_session(seed=8)
        base = evaluate_state(session)
        # Piling on gold, combat and cards must not move the leaf score.
        session.bot.gold += 25
        session.bot.combat += 25
        session.bot.discard.extend(session.market.row_cards()[:3])
        self.assertAlmostEqual(evaluate_state(session), base, places=6)

    def test_leaf_tracks_health_difference(self):
        from web.bot import evaluate_state

        session = create_session(seed=8)
        base = evaluate_state(session)
        session.player.hp -= 10
        self.assertGreater(evaluate_state(session), base)

    def test_terminal_positions_dominate(self):
        from web.bot import WIN_SCORE, evaluate_state

        session = create_session(seed=8)
        session.player.hp = 0
        session._check_winner()
        self.assertEqual(evaluate_state(session), WIN_SCORE)

        session = create_session(seed=8)
        session.bot.hp = 0
        session._check_winner()
        self.assertEqual(evaluate_state(session), -WIN_SCORE)

    def test_rollout_simulates_the_opponent_turn(self):
        """It used to stop at the bot's end of turn, so it never saw a purchase
        get drawn, nor itself being hit."""
        from web.bot import _rollout

        session = create_session(seed=8)
        start = session.turn_number
        clone = session.clone()
        _rollout(clone)
        self.assertGreater(clone.turn_number, start)

    def test_rollout_respects_its_turn_horizon(self):
        from web.bot import _rollout

        session = create_session(seed=8)
        clone = session.clone()
        start = clone.turn_number
        _rollout(clone, turn_limit=2)
        if clone.winner is None:
            self.assertLessEqual(clone.turn_number - start, 2)

    def test_bot_still_buys_without_a_deck_term(self):
        """Purchases have to survive on rollout evidence alone."""
        import web.bot as bot_module

        previous = bot_module.EVAL_MODE
        bot_module.EVAL_MODE = "search"
        try:
            random.seed(21)
            session = create_session(seed=21, algorithm="mcts", budget_ms=30)
            owned = len(session.bot.deck) + len(session.bot.hand) + len(session.bot.discard)
            for _ in range(400):
                if session.winner:
                    break
                if session.active_player == "bot":
                    apply_action(session, choose_bot_action(session, budget_ms=30, algorithm="mcts"))
                else:
                    apply_action(session, _heuristic_rollout_action(session))
            final = len(session.bot.deck) + len(session.bot.hand) + len(session.bot.discard)
            self.assertGreater(final, owned, "bot never bought a card")
        finally:
            bot_module.EVAL_MODE = previous
