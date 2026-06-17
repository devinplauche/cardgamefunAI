import unittest

from src.card_file import SIMULATION_SHOP_CARDS
from src.simulation import CATALOG, generate_report


class TestSimulationReport(unittest.TestCase):
    def test_catalog_includes_expected_low_cost_base_cards(self):
        names = {card.name for card in CATALOG}
        self.assertIn("Profit", names)
        self.assertIn("Spark", names)

    def test_catalog_is_sourced_from_card_file(self):
        catalog_entries = [
            {
                "name": card.name,
                "cost": card.cost,
                "damage": card.damage,
                "bonus_resources": card.bonus_resources,
            }
            for card in CATALOG
        ]
        self.assertEqual(catalog_entries, list(SIMULATION_SHOP_CARDS))

    def test_generate_report_has_expected_fields(self):
        report = generate_report(num_games=25, seed=1, top_n=2)

        self.assertEqual(report["num_games"], 25)
        self.assertIn("average_game_length", report)
        self.assertIn("most_purchased_cards", report)
        self.assertIn("all_purchase_counts", report)

        self.assertGreater(report["average_game_length"], 0)
        self.assertLessEqual(len(report["most_purchased_cards"]), 2)
        self.assertGreater(len(report["all_purchase_counts"]), 0)
        self.assertIn("Profit", report["all_purchase_counts"])
        self.assertIn("Spark", report["all_purchase_counts"])

    def test_generate_report_rejects_non_positive_game_count(self):
        with self.assertRaises(ValueError):
            generate_report(num_games=0)
        with self.assertRaises(ValueError):
            generate_report(num_games=-5)


if __name__ == "__main__":
    unittest.main()
