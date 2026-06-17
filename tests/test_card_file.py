import unittest

from src.card_file import BASE_GAME_SOURCE_URL, BASE_STARTER_DECK_CARDS


class TestCardFile(unittest.TestCase):
    def test_base_game_source_url_is_set(self):
        self.assertEqual(BASE_GAME_SOURCE_URL, "https://www.herorealms.com/base-game/")

    def test_base_starter_deck_matches_expected_base_cards(self):
        expected = {
            "Gold": {"damage": 0, "bonus_resources": 1, "count": 7},
            "Dagger": {"damage": 1, "bonus_resources": 0, "count": 1},
            "Short Sword": {"damage": 2, "bonus_resources": 0, "count": 1},
            "Ruby": {"damage": 0, "bonus_resources": 2, "count": 1},
        }
        self.assertEqual(len(BASE_STARTER_DECK_CARDS), len(expected))
        for card in BASE_STARTER_DECK_CARDS:
            self.assertIn(card["name"], expected)
            self.assertEqual(card, {"name": card["name"], **expected[card["name"]]})


if __name__ == "__main__":
    unittest.main()
