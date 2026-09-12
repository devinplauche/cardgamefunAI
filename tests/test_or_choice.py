"""Regression tests for or_choice resolution in expend_champion.

Two decision-quality bugs, distinct from the buy-time valuation bug found in
the same review: these affect actual gameplay resolution (what happens when
an or_choice champion is expended in a real game), not just how the AI
estimates a card's worth before buying it.
"""

import unittest

from hero_engine import BoardChampion, HRCard, HRPlayer


def _champion_with_or_choice(**effects):
    or_choice = effects.pop("or_choice")
    card = HRCard(id="test_champ", name="Test Champion", cost=3, faction="",
                  card_type="champion", health=6, effects={**effects, "or_choice": or_choice})
    return BoardChampion(card)


def _guard_champion(health: int):
    card = HRCard(id="test_guard", name="Test Guard", cost=2, faction="",
                  card_type="champion", guard=1, health=health, effects={})
    bc = BoardChampion(card)
    bc.current_health = health
    return bc


class TestCombatBranchAgainstGuards(unittest.TestCase):
    """A live guard used to veto the combat branch outright, regardless of
    whether the champion's combat could actually kill it."""

    def test_takes_combat_when_it_can_kill_the_weakest_guard(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(combat=5, health=4, or_choice=["combat", "health"])
        player = HRPlayer("P")
        player.hp = 50  # healing would be wasted, so this also isolates the guard check
        player.board.append(bc)
        opponent = HRPlayer("O")
        opponent.board.append(_guard_champion(health=3))  # killable

        expend_champion(player, bc, opponent=opponent)

        self.assertEqual(player.combat, 5, "combat that can kill the guard should still be taken")
        self.assertEqual(player.hp, 50)

    def test_still_avoids_combat_it_cannot_kill_the_guard_with(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(combat=2, health=4, or_choice=["combat", "health"])
        player = HRPlayer("P")
        player.hp = 20  # low, so healing is both useful and unwasted
        player.board.append(bc)
        opponent = HRPlayer("O")
        opponent.board.append(_guard_champion(health=8))  # not killable with 2 combat

        expend_champion(player, bc, opponent=opponent)

        self.assertEqual(player.combat, 0, "combat that cannot kill the guard should still be vetoed")
        self.assertEqual(player.hp, 24)


class TestHealthBranchScoring(unittest.TestCase):
    """There is no health cap (physical health cards are double-sided to
    track above 50), so a heal always lands in full and the bot scores it
    at face value instead of discounting a would-be overflow."""

    def test_takes_full_heal_over_smaller_gold(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(gold=2, health=6, or_choice=["gold", "health"])
        player = HRPlayer("P")
        player.hp = 49  # the full 6-point heal lands: 49 -> 55
        player.gold = 5  # >= 3, so gold gets no low-gold urgency bonus either
        player.board.append(bc)

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.hp, 55, "uncapped heal should beat the smaller gold branch")
        self.assertEqual(player.gold, 5, "gold was not the chosen branch, so it must not change")

    def test_still_takes_a_heal_that_is_not_overflowing(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(gold=2, health=6, or_choice=["gold", "health"])
        player = HRPlayer("P")
        player.hp = 30  # the full 6 points would land
        player.gold = 5
        player.board.append(bc)

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.hp, 36)
        self.assertEqual(player.gold, 5, "gold should not have been taken instead")

    def test_per_champion_health_scores_full_value(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(gold=1, per_champion_health=3, or_choice=["gold", "per_champion_health"])
        player = HRPlayer("P")
        player.hp = 49  # 1 champion x 3 = 3 heal -> 52
        player.gold = 5
        player.board.append(bc)

        expend_champion(player, bc, opponent=None)

        self.assertEqual(player.hp, 52, "uncapped per-champion heal should beat the gold branch")
        self.assertEqual(player.gold, 5, "gold was not the chosen branch, so it must not change")


class TestGuaranteedLethalBranch(unittest.TestCase):
    def test_combat_lethal_overrides_low_gold_urgency(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(combat=2, gold=1,
                                      or_choice=["combat", "gold"])
        player = HRPlayer("P")
        player.gold = 0
        player.board.append(bc)
        opponent = HRPlayer("O")
        opponent.hp = 2

        expend_champion(player, bc, opponent=opponent)

        self.assertEqual(player.combat, 2)
        self.assertEqual(player.gold, 0)

    def test_combat_lethal_overrides_emergency_healing(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(combat=3, health=5,
                                      or_choice=["combat", "health"])
        player = HRPlayer("P")
        player.hp = 10
        player.board.append(bc)
        opponent = HRPlayer("O")
        opponent.hp = 3

        expend_champion(player, bc, opponent=opponent)

        self.assertEqual(player.combat, 3)
        self.assertEqual(player.hp, 10)

    def test_exhausted_living_guard_still_blocks_face_lethal(self):
        from hero_engine import expend_champion

        bc = _champion_with_or_choice(combat=2, gold=1,
                                      or_choice=["combat", "gold"])
        player = HRPlayer("P")
        player.gold = 0
        player.board.append(bc)
        opponent = HRPlayer("O")
        opponent.hp = 2
        guard = _guard_champion(health=8)
        guard.exhausted = True
        opponent.board.append(guard)

        expend_champion(player, bc, opponent=opponent)

        self.assertEqual(player.combat, 0)
        self.assertEqual(player.gold, 1)


if __name__ == "__main__":
    unittest.main()
