import unittest

from hero_engine import (
    BoardChampion,
    HRCard,
    HRPlayer,
    auto_expend_all,
    expend_champion,
    play_card,
)


class TestDeferredPrepare(unittest.TestCase):
    def test_prepare_readies_the_first_champion_chosen_after_play_phase(self):
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        champion_card = HRCard(
            id="champion",
            name="Champion",
            cost=2,
            faction="Imperial",
            card_type="champion",
            health=3,
            effects={"combat": 2},
        )
        champion = BoardChampion(champion_card)
        player.board.append(champion)
        prepare = HRCard(
            id="prepare",
            name="Prepare",
            cost=1,
            faction="Imperial",
            card_type="action",
            effects={
                "ally_faction": "Imperial",
                "prepare": True,
            },
        )
        player.hand = [prepare]

        self.assertTrue(play_card(
            player, prepare, None, ally_bonus=True, opponent=opponent,
        ))
        self.assertEqual(player.pending_prepares, 1)

        self.assertTrue(expend_champion(player, champion, opponent))
        self.assertFalse(champion.exhausted)
        self.assertEqual(player.pending_prepares, 0)
        self.assertEqual(player.combat, 2)

        self.assertTrue(expend_champion(player, champion, opponent))
        self.assertTrue(champion.exhausted)
        self.assertEqual(player.combat, 4)

    def test_prepare_still_readies_an_already_exhausted_champion_immediately(self):
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        champion_card = HRCard(
            id="champion",
            name="Champion",
            cost=2,
            faction="Imperial",
            card_type="champion",
            health=3,
        )
        champion = BoardChampion(champion_card)
        champion.exhausted = True
        player.board.append(champion)
        prepare = HRCard(
            id="prepare",
            name="Prepare",
            cost=1,
            faction="Imperial",
            card_type="action",
            effects={"ally_faction": "Imperial", "prepare": True},
        )
        player.hand = [prepare]

        self.assertTrue(play_card(
            player, prepare, None, ally_bonus=True, opponent=opponent,
        ))

        self.assertFalse(champion.exhausted)
        self.assertEqual(player.pending_prepares, 0)

    def test_auto_expend_consumes_the_queued_extra_activation(self):
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        champion = BoardChampion(HRCard(
            id="champion",
            name="Champion",
            cost=2,
            faction="Imperial",
            card_type="champion",
            health=3,
            effects={"combat": 2},
        ))
        player.board.append(champion)
        player.pending_prepares = 1

        auto_expend_all(player, opponent)

        self.assertEqual(player.combat, 4)
        self.assertEqual(player.pending_prepares, 0)
        self.assertTrue(champion.exhausted)


if __name__ == "__main__":
    unittest.main()
