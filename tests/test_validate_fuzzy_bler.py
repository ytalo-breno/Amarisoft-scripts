import unittest

from validate_fuzzy_bler import summarize, validate_rows


class ValidateFuzzyBlerTests(unittest.TestCase):
    def test_uses_cqi_to_limit_proposed_downlink_mcs(self):
        rows, skipped = validate_rows([
            {"cell_id": "1", "rnti": "42", "cqi": "3", "dl_bler": "0.2", "dl_mcs": "10"},
        ], "sample.csv")

        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]["cqi_mcs_limit"], 3)
        self.assertEqual(rows[0]["proposed_mcs"], 3)
        self.assertEqual(rows[0]["within_cqi_limit"], "false")

    def test_calculates_bler_from_counter_window(self):
        rows, skipped = validate_rows([
            {"cell_id": "1", "rnti": "42", "cqi": "10", "dl_mcs": "10", "dl_tx": "100", "dl_err": "5"},
            {"cell_id": "1", "rnti": "42", "cqi": "10", "dl_mcs": "10", "dl_tx": "200", "dl_err": "15"},
        ])

        self.assertEqual(skipped, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bler_source"], "dl_err/dl_tx")
        self.assertEqual(rows[0]["bler"], "0.1")

    def test_summary_is_empty_when_no_valid_rows(self):
        self.assertEqual(summarize([], 2), {"validated": 0, "skipped": 2})


if __name__ == "__main__":
    unittest.main()