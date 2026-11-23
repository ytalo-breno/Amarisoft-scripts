import unittest

from validate_fuzzy_bler import summarize, validate_rows


class ValidateFuzzyBlerTests(unittest.TestCase):
    def test_cqi_defines_target_without_bler_or_counters(self):
        rows, skipped = validate_rows([
            {'cell_id': '1', 'rnti': '42', 'cqi': '3', 'dl_mcs': '10'},
        ], 'sample.csv')
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]['cqi_mcs_limit'], 3)
        self.assertEqual(rows[0]['proposed_mcs'], 3)
        self.assertEqual(rows[0]['within_cqi_limit'], 'false')

    def test_bler_and_counters_do_not_change_target(self):
        rows, skipped = validate_rows([
            {'cqi': '10', 'dl_mcs': '10', 'dl_bler': '0'},
            {'cqi': '10', 'dl_mcs': '28', 'dl_bler': '1', 'dl_err': '99'},
        ])
        self.assertEqual(skipped, 0)
        self.assertEqual([row['proposed_mcs'] for row in rows], [17, 17])

    def test_invalid_cqi_is_skipped(self):
        rows, skipped = validate_rows([{'cqi': 'nan', 'dl_mcs': '10'}])
        self.assertEqual(rows, [])
        self.assertEqual(skipped, 1)

    def test_summary_is_empty_when_no_valid_rows(self):
        self.assertEqual(summarize([], 2), {'validated': 0, 'skipped': 2})
