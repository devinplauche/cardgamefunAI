import unittest

from src.simulation import generate_report


class TestSimulationReport(unittest.TestCase):
    def test_generate_report_has_expected_fields(self):
        report = generate_report(num_games=25, seed=1, top_n=2)

        self.assertEqual(report["num_games"], 25)
        self.assertIn("average_game_length", report)
        self.assertIn("most_purchased_cards", report)
        self.assertIn("all_purchase_counts", report)

        self.assertGreater(report["average_game_length"], 0)
        self.assertLessEqual(len(report["most_purchased_cards"]), 2)
        self.assertTrue(report["all_purchase_counts"])

    def test_generate_report_rejects_non_positive_game_count(self):
        with self.assertRaises(ValueError):
            generate_report(num_games=0)
        with self.assertRaises(ValueError):
            generate_report(num_games=-5)


if __name__ == "__main__":
    unittest.main()
