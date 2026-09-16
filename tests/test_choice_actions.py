"""Tests for deferred sacrifice/discard choices and the v3 action space.

The engine resolved these inline via _find_worst_idx, which made them
unreachable to any agent. Deferring them is only safe if the deferred path
with auto-resolution is byte-identical to the old inline one - otherwise
enabling it silently changes the heuristics, MCTS, and every recorded
baseline.
"""

import random
import unittest

from hero_rl_env_v3 import HeroRealmsChoiceEnv


class TestUnanswerableChoice(unittest.TestCase):
    """A deferred choice with no legal candidate must not block the env.

    A sacrifice with nothing left in hand or discard produced an empty
    _action_table while the game was not over: greedy crashed on max() over an
    empty table, and a policy fell through action_masks' ADVANCE fallback,
    which never clears the choice, so the episode burned steps to max_steps.

    Latent in v3, which V19 and V20 both trained on. It surfaced only when a
    specialist trained against `economic` for every episode instead of the
    4-profile mixture.
    """

    def _env_with_unanswerable_choice(self, zone):
        env = HeroRealmsChoiceEnv(opponent_profile="economic")
        env.reset(seed=0)
        me, _ = env._seats()
        me.hand.clear()
        me.discard.clear()
        me.pending_choices.append({"kind": "sacrifice", "count": 1, "zone": zone})
        return env, me

    def test_unanswerable_choice_is_dropped_not_offered(self):
        for zone in ("hand", "discard"):
            with self.subTest(zone=zone):
                env, me = self._env_with_unanswerable_choice(zone)
                table = env._action_table()
                self.assertTrue(table, "no legal action offered mid-game")
                self.assertEqual(me.pending_choices, [])

    def test_answerable_choice_is_still_offered(self):
        """The fix must not eat choices that do have candidates."""
        env = HeroRealmsChoiceEnv(opponent_profile="economic")
        env.reset(seed=0)
        me, _ = env._seats()
        self.assertTrue(me.hand, "expected a starting hand to sacrifice from")
        me.pending_choices.append({"kind": "sacrifice", "count": 1, "zone": "hand"})
        self.assertIsNotNone(env._pending())
        self.assertEqual(len(me.pending_choices), 1)

    def test_greedy_never_sees_an_empty_action_table(self):
        """The exact crash: max() over an empty table during BC collection."""
        env = HeroRealmsChoiceEnv(opponent_profile="economic")
        for episode in range(40):
            obs, _ = env.reset(seed=episode)
            done = truncated = False
            while not (done or truncated):
                table = env._action_table()
                self.assertTrue(table, "empty action table while the game is live")
                action = max(table, key=lambda k: table[k].get("priority", 0))
                obs, _, done, truncated, _ = env.step(action)

from hero_engine import (GOLD, DAGGER, RUBY, SHORTSWORD, HRMarket, HRPlayer,
                         BoardChampion, apply_choice, auto_resolve_choices,
                         choice_candidates, choice_candidates_zoned,
                         expend_champion, load_hero_cards, play_card)
from hero_rl_env_v2 import N_ACTIONS as V2_ACTIONS
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
        self.assertEqual(CHOICE_BASE, V2_ACTIONS)
        self.assertEqual(N_ACTIONS, V2_ACTIONS + CHOICE_SLOTS)

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

    def test_sacrifice_choice_with_no_junk_is_declined_not_forced(self):
        """'You may sacrifice' with nothing worth sacrificing must not force
        the agent to burn a good card - the engine's inline path and
        auto_resolve_choices both decline it. Tyrannor's 'up to two' is what
        made this live: without the drop, a thinned deck was punished for
        expending it."""
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=0)
        good = next(c for c in CARDS
                    if c.get("gold", 0) > 0 and c.cost >= 2
                    and c.name != "Fire Gem")
        env.me.hand = [good]
        env.me.discard = []
        env.me.pending_choices = [{"kind": "sacrifice", "count": 2,
                                   "zone": "hand_or_discard"}]
        table = env._action_table()
        self.assertEqual(env.me.pending_choices, [],
                         "nothing junk: the choice must be dropped, not offered")
        self.assertTrue(all(k < CHOICE_BASE for k in table),
                        "no choice slots may be offered for a declined effect")
        self.assertEqual(env.me.banish, [])

    def test_sacrifice_choice_with_junk_is_still_offered(self):
        """The decline must not eat choices that do have a junk candidate."""
        env = HeroRealmsChoiceEnv(opponent_profile="balanced")
        env.reset(seed=0)
        env.me.hand = [GOLD, DAGGER]
        env.me.pending_choices = [{"kind": "sacrifice", "count": 2,
                                   "zone": "hand_or_discard"}]
        table = env._action_table()
        self.assertEqual(len(env.me.pending_choices), 1)
        self.assertTrue(any(k >= CHOICE_BASE for k in table))

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


class TestReanimateRecycleChoices(unittest.TestCase):
    """Varrick (reanimate) and Smash and Grab (recycle) used to be engine
    auto-picks. Now the player chooses through the deferred-choice queue;
    the old best-pick survives only as the automated fallback."""

    VARRICK = next(c for c in CARDS if c.name == "Varrick, the Necromancer")
    SMASH = next(c for c in CARDS if c.name == "Smash and Grab")
    ALL_CHAMPS = [c for c in CARDS if c.card_type == "champion"]

    def _varrick_pair(self, seed):
        """Two identical seats; b defers, a resolves inline (the old way)."""
        rng = random.Random(seed)
        discards = [GOLD, DAGGER] + rng.sample(self.ALL_CHAMPS, 3)
        a, oa = HRPlayer("A"), HRPlayer("OA")
        b, ob = HRPlayer("B"), HRPlayer("OB")
        a.discard = list(discards)
        b.discard = list(discards)
        a.board = [BoardChampion(self.VARRICK)]
        b.board = [BoardChampion(self.VARRICK)]
        b.defer_choices = True
        return (a, oa), (b, ob)

    def test_varrick_enqueues_champion_only_choice(self):
        (a, oa), (b, ob) = self._varrick_pair(0)
        self.assertTrue(expend_champion(b, b.board[0], ob))
        self.assertEqual(len(b.pending_choices), 1)
        choice = b.pending_choices[0]
        self.assertEqual(choice["kind"], "reanimate")
        self.assertEqual(choice["source"], "Varrick, the Necromancer")
        cands = choice_candidates(b, choice)
        self.assertEqual(len(cands), 3)
        self.assertTrue(all(c.card_type == "champion" for c in cands),
                        "Gold/Dagger must not be reanimate candidates")

    def test_varrick_apply_choice_puts_picked_champion_on_top(self):
        (a, oa), (b, ob) = self._varrick_pair(1)
        expend_champion(b, b.board[0], ob)
        choice = b.pending_choices[0]
        cands = choice_candidates(b, choice)
        # Take the last candidate, not the engine's best, to prove the
        # player's pick - not the heuristic - decides.
        picked = cands[-1]
        apply_choice(b, choice, len(cands) - 1)
        self.assertIs(b.deck[0], picked)
        self.assertNotIn(picked, b.discard)
        self.assertEqual(b.pending_choices, [])

    def test_varrick_no_champions_no_choice(self):
        p, o = HRPlayer("P"), HRPlayer("O")
        p.defer_choices = True
        p.discard = [GOLD, DAGGER]
        p.board = [BoardChampion(self.VARRICK)]
        expend_champion(p, p.board[0], o)
        self.assertEqual(p.pending_choices, [])

    def test_varrick_auto_resolve_matches_old_inline(self):
        for seed in range(20):
            (a, oa), (b, ob) = self._varrick_pair(seed)
            expend_champion(a, a.board[0], oa)
            expend_champion(b, b.board[0], ob)
            auto_resolve_choices(b, ob)
            self.assertEqual([c.name for c in a.deck],
                             [c.name for c in b.deck])
            self.assertEqual(sorted(c.name for c in a.discard),
                             sorted(c.name for c in b.discard))

    def _smash_pair(self, seed):
        rng = random.Random(seed + 1000)
        discards = [rng.choice(POOL) for _ in range(4)]
        a, oa = HRPlayer("A"), HRPlayer("OA")
        b, ob = HRPlayer("B"), HRPlayer("OB")
        a.hand = [self.SMASH]
        b.hand = [self.SMASH]
        a.discard = list(discards)
        b.discard = list(discards)
        a.deck = [GOLD]
        b.deck = [GOLD]
        b.defer_choices = True
        market = lambda: HRMarket(CARDS, random.Random(seed))
        return (a, oa, market()), (b, ob, market())

    def test_smash_grab_enqueues_recycle_choice(self):
        (a, oa, ma), (b, ob, mb) = self._smash_pair(0)
        play_card(b, self.SMASH, mb, opponent=ob)
        self.assertEqual(len(b.pending_choices), 1)
        choice = b.pending_choices[0]
        self.assertEqual(choice["kind"], "recycle")
        self.assertEqual(choice["source"], "Smash and Grab")
        self.assertEqual(len(choice_candidates(b, choice)), 4)

    def test_smash_grab_apply_choice_recycles_picked_card(self):
        (a, oa, ma), (b, ob, mb) = self._smash_pair(1)
        play_card(b, self.SMASH, mb, opponent=ob)
        choice = b.pending_choices[0]
        cands = choice_candidates(b, choice)
        picked = cands[0]
        n_discard = len(b.discard)
        apply_choice(b, choice, 0)
        self.assertIs(b.deck[0], picked)
        # Identical copies are interchangeable, so assert the pile shrank
        # rather than identity-absence.
        self.assertEqual(len(b.discard), n_discard - 1)
        self.assertEqual(b.pending_choices, [])

    def test_smash_grab_auto_resolve_matches_old_inline(self):
        for seed in range(20):
            (a, oa, ma), (b, ob, mb) = self._smash_pair(seed)
            play_card(a, self.SMASH, ma, opponent=oa)
            play_card(b, self.SMASH, mb, opponent=ob)
            auto_resolve_choices(b, ob)
            self.assertEqual([c.name for c in a.deck],
                             [c.name for c in b.deck])
            self.assertEqual(sorted(c.name for c in a.discard),
                             sorted(c.name for c in b.discard))

    def test_zoned_candidates_do_not_mislabel_discard_zone(self):
        """choice_candidates_zoned used to label the first len(hand)
        candidates 'hand' positionally - for a pure-discard choice every
        candidate must say discard."""
        p = HRPlayer("P")
        p.hand = [GOLD, GOLD]
        p.discard = [DAGGER]
        choice = {"kind": "recycle", "count": 1, "zone": "discard"}
        self.assertEqual(choice_candidates_zoned(p, choice),
                         [(DAGGER, "discard")])


if __name__ == "__main__":
    unittest.main()
