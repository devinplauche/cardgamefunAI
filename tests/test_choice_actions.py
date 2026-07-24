"""Tests for deferred sacrifice/discard choices and the v3 action space.

The engine resolved these inline via _find_worst_idx, which made them
unreachable to any agent. Deferring them is only safe if the deferred path
with auto-resolution is byte-identical to the old inline one - otherwise
enabling it silently changes the heuristics, MCTS, and every recorded
baseline.
"""

import random
import unittest

from hero_engine import (GOLD, DAGGER, RUBY, SHORTSWORD, HRMarket, HRPlayer,
                         apply_choice, auto_resolve_choices, choice_candidates,
                         load_hero_cards, play_card)
from hero_rl_env_v3 import CHOICE_BASE, CHOICE_SLOTS, N_ACTIONS, HeroRealmsChoiceEnv, distinct_candidates

CARDS = load_hero_cards("data/hero_realms_cards.json")
CHOICE_CARDS = ["Dark Reward", "Death Touch", "Life Drain", "The Rot", "Elven Gift"]
BY_NAME = {n: next(c for c in CARDS if c.name == n) for n in CHOICE_CARDS}
POOL = [GOLD, DAGGER, SHORTSWORD, RUBY]


def _build(seed, card):
    rng = random.Random(seed)
    p, o = HRPlayer("P"), HRPlayer("O")
    p.hand = [rng.choice(POOL) for _ in range(4)] + [card]
    p.discard = [rng.choice(POOL) for _ in range(3)]
    p.deck = [rng.choice(POOL) for _ in range(8)]
    o.hand = [rng.choice(POOL) for _ in range(5)]
    return p, o


class TestDeferredEqualsInline(unittest.TestCase):
    """The property that makes deferral safe to ship."""

    def _snapshot(self, p):
        return ([c.name for c in p.hand], [c.name for c in p.banish],
                sorted(c.name for c in p.discard), p.gold, p.combat)

    def test_auto_resolution_matches_the_old_inline_behaviour(self):
        mismatches = []
        for name in CHOICE_CARDS:
            for seed in range(30):
                a, oa = _build(seed, BY_NAME[name])
                b, ob = _build(seed, BY_NAME[name])
                play_card(a, BY_NAME[name], HRMarket(CARDS, random.Random(seed)), opponent=oa)
                b.defer_choices = True
                play_card(b, BY_NAME[name], HRMarket(CARDS, random.Random(seed)), opponent=ob)
                auto_resolve_choices(b, ob)
                if self._snapshot(a) != self._snapshot(b):
                    mismatches.append((name, seed))
        self.assertEqual(mismatches, [], f"deferred path diverged: {mismatches[:5]}")

    def test_deferral_actually_enqueues_something(self):
        """Guards against the equivalence test passing vacuously because the
        effects never fired - which is exactly how it first passed."""
        enqueued = 0
        for name in CHOICE_CARDS:
            for seed in range(10):
                p, o = _build(seed, BY_NAME[name])
                p.defer_choices = True
                play_card(p, BY_NAME[name], HRMarket(CARDS, random.Random(seed)), opponent=o)
                enqueued += bool(p.pending_choices)
        self.assertGreater(enqueued, 0)

    def test_default_player_does_not_defer(self):
        self.assertFalse(HRPlayer("X").defer_choices)


class TestApplyChoice(unittest.TestCase):
    def test_sacrifice_banishes_from_hand(self):
        p = HRPlayer("P")
        p.hand = [GOLD, DAGGER]
        choice = {"kind": "sacrifice", "count": 1, "zone": "hand"}
        p.pending_choices = [choice]
        apply_choice(p, choice, 1)
        self.assertEqual([c.name for c in p.banish], ["Dagger"])
        self.assertEqual([c.name for c in p.hand], ["Gold"])
        self.assertEqual(p.pending_choices, [], "a spent choice must be dequeued")

    def test_discard_moves_to_discard_pile_not_banish(self):
        p = HRPlayer("P")
        p.hand = [GOLD, DAGGER]
        choice = {"kind": "discard", "count": 1, "zone": "hand"}
        p.pending_choices = [choice]
        apply_choice(p, choice, 0)
        self.assertEqual([c.name for c in p.discard], ["Gold"])
        self.assertEqual(p.banish, [])

    def test_multi_count_choice_stays_until_exhausted(self):
        p = HRPlayer("P")
        p.hand = [GOLD, DAGGER, RUBY]
        choice = {"kind": "discard", "count": 2, "zone": "hand"}
        p.pending_choices = [choice]
        apply_choice(p, choice, 0)
        self.assertEqual(len(p.pending_choices), 1)
        self.assertEqual(choice["count"], 1)
        apply_choice(p, choice, 0)
        self.assertEqual(p.pending_choices, [])

    def test_out_of_range_index_is_rejected(self):
        p = HRPlayer("P")
        p.hand = [GOLD]
        choice = {"kind": "discard", "count": 1, "zone": "hand"}
        self.assertIsNone(apply_choice(p, choice, 5))
        self.assertEqual(len(p.hand), 1)


class TestChoiceEnv(unittest.TestCase):
    def test_action_space_extends_v2_without_renumbering_it(self):
        self.assertEqual(CHOICE_BASE, 30)
        self.assertEqual(N_ACTIONS, 40)

    def test_heuristic_opponent_does_not_defer(self):
        """Nothing answers a heuristic opponent's choices, so deferring them
        deletes its sacrifices and discards at the next _start_turn - Elven
        Gift would draw without discarding. That silently changes the
        opponent and breaks comparability with the v2 baselines."""
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=0)
        self.assertTrue(env.me.defer_choices)
        self.assertFalse(env.foe.defer_choices)

    def test_opponent_choices_never_go_unanswered_during_a_game(self):
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=1)
        for _ in range(200):
            table = env._action_table()
            _, _, done, trunc, _ = env.step(max(table, key=lambda k: table[k].get("priority", 0)))
            self.assertFalse(env.foe.pending_choices,
                             "heuristic opponent left a choice unresolved")
            if done or trunc:
                break

    def test_defer_opponent_flag_enables_symmetric_deferral(self):
        """Self-play needs both seats deferring, since a policy can answer."""
        class Symmetric(HeroRealmsChoiceEnv):
            defer_opponent = True

        env = Symmetric(opponent_profile="balanced")
        env.reset(seed=0)
        self.assertTrue(env.me.defer_choices)
        self.assertTrue(env.foe.defer_choices)

    def test_pending_choice_blocks_all_other_actions(self):
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=0)
        env.me.hand = [GOLD, DAGGER]
        env.me.pending_choices = [{"kind": "sacrifice", "count": 1, "zone": "hand"}]
        table = env._action_table()
        self.assertTrue(table)
        self.assertTrue(all(k >= CHOICE_BASE for k in table),
                        "a pending choice must be answered before anything else")

    def test_candidates_are_deduplicated_by_card(self):
        """Sacrificing one Gold is the same decision as sacrificing another."""
        p = HRPlayer("P")
        p.hand = [GOLD, GOLD, GOLD, DAGGER]
        choice = {"kind": "sacrifice", "count": 1, "zone": "hand"}
        self.assertEqual(len(distinct_candidates(p, choice)), 2)

    def test_candidate_order_is_stable_under_shuffling(self):
        choice = {"kind": "sacrifice", "count": 1, "zone": "hand"}
        base = None
        for seed in range(5):
            p = HRPlayer("P")
            hand = [GOLD, DAGGER, RUBY, SHORTSWORD]
            random.Random(seed).shuffle(hand)
            p.hand = hand
            names = [c.name for c in distinct_candidates(p, choice)]
            base = base or names
            self.assertEqual(names, base, "slot meaning must not depend on hand order")

    def test_candidates_are_capped_at_the_slot_count(self):
        p = HRPlayer("P")
        p.hand = [c for c in CARDS[:40]]
        choice = {"kind": "sacrifice", "count": 1, "zone": "hand"}
        self.assertLessEqual(len(distinct_candidates(p, choice)), CHOICE_SLOTS)

    def test_choices_actually_occur_during_play(self):
        env = HeroRealmsChoiceEnv(opponent_profile="random")
        seen = 0
        for ep in range(25):
            env.reset(seed=ep)
            done = trunc = False
            while not (done or trunc):
                table = env._action_table()
                if any(k >= CHOICE_BASE for k in table):
                    seen += 1
                _, _, done, trunc, _ = env.step(max(table, key=lambda k: table[k].get("priority", 0)))
        self.assertGreater(seen, 0, "no sacrifice/discard decision ever surfaced")

    def test_games_still_terminate(self):
        env = HeroRealmsChoiceEnv(opponent_profile="random")
        for ep in range(5):
            env.reset(seed=ep)
            done = trunc = False
            while not (done or trunc):
                table = env._action_table()
                _, _, done, trunc, _ = env.step(random.choice(list(table)))
            self.assertTrue(done)

    def test_masks_never_offer_an_unmapped_action(self):
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=2)
        for _ in range(60):
            table = env._action_table()
            mask = env.action_masks()
            for idx in range(N_ACTIONS):
                if mask[idx]:
                    self.assertIn(idx, table)
            _, _, done, trunc, _ = env.step(max(table, key=lambda k: table[k].get("priority", 0)))
            if done or trunc:
                break


if __name__ == "__main__":
    unittest.main()
