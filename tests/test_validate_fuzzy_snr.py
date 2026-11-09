import unittest

from validate_fuzzy_snr import summarize, validate_rows


class ValidateFuzzySnrTests(unittest.TestCase):
    def test_replays_pusch_snr_and_applies_sinr_limit(self):
        rows, skipped = validate_rows([
            {"cell_id": "1", "rnti": "42", "pusch_snr": "24.5", "ul_mcs": "20"},
            {"cell_id": "1", "rnti": "42", "pusch_snr": "-5", "ul_mcs": "10"},
        ], "sample.csv")

        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]["sinr_mcs_limit"], 28)
        self.assertEqual(rows[0]["fuzzy_delta"], 1)
        self.assertEqual(rows[1]["within_sinr_limit"], "false")
        self.assertEqual(rows[0]["source_file"], "sample.csv")

    def test_falls_back_to_snr_and_skips_invalid_rows(self):
        rows, skipped = validate_rows([
            {"snr": "10", "ul_mcs": "8"},
            {"pusch_snr": "", "ul_mcs": "8"},
        ])

        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, 1)

    def test_summary_is_empty_when_no_valid_rows(self):
        self.assertEqual(summarize([], 2), {"validated": 0, "skipped": 2})


if __name__ == "__main__":
    unittest.main()