import math
import unittest
from unittest.mock import Mock

from fuzzy_snr import FuzzyController, get_max_mcs_for_snr, infer_delta


class FuzzySnrTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.controller = FuzzyController(self.api)

    def poll(self, *samples):
        self.api.request.return_value = {"ue_list": [{"cells": list(samples)}]}
        self.controller.poll()

    def sample(self, **overrides):
        return dict(dict(cell_id=1, cqi=15, dl_mcs=10, snr=0), **overrides)

    def test_rule_direction_and_coverage(self):
        for snr in [-20, 0, 5, 10, 15, 20, 30, 40]:
            for cqi in range(16):
                with self.subTest(snr=snr, cqi=cqi):
                    self.assertTrue(-4 <= infer_delta(snr, cqi) <= 2)
        self.assertLess(infer_delta(-10, 15), 0)
        self.assertGreater(infer_delta(30, 15), 0)

    def test_invalid_inputs_are_not_clipped(self):
        for snr, cqi in [(-21, 15), (math.nan, 2), (40.1, 15), (10, None)]:
            with self.assertRaises(ValueError):
                infer_delta(snr, cqi)

    def test_oai_snr_table_maps_thresholds_to_mcs(self):
        self.assertEqual(get_max_mcs_for_snr(-1.0), 0)
        self.assertEqual(get_max_mcs_for_snr(-0.4), 1)
        self.assertEqual(get_max_mcs_for_snr(24.5), 28)
        self.assertEqual(get_max_mcs_for_snr(24.4), 27)

    def test_oai_snr_table_applies_mimo_offset(self):
        self.assertEqual(get_max_mcs_for_snr(2.9, layers=2), 0)
        self.assertEqual(get_max_mcs_for_snr(3.6, layers=2), 1)
        self.assertEqual(get_max_mcs_for_snr(31.5, layers=4), 28)

    def test_oai_snr_table_rejects_invalid_layers(self):
        with self.assertRaises(ValueError):
            get_max_mcs_for_snr(10, layers=3)

    def test_missing_metric_blocks_entire_cell(self):
        missing = self.sample()
        del missing["snr"]
        self.poll(self.sample(), missing)
        self.api.request.assert_called_once_with("ue_get", stats=True)

    def test_worst_snr_controls_cell(self):
        self.poll(self.sample(snr=10), self.sample(snr=-5))
        self.api.request.assert_called_with("config_set", cells={"1": {"pdsch_mcs": 0}})
        self.assertEqual(self.api.request.call_count, 2)

    def test_recovery_requires_three_high_snr_samples(self):
        for _ in range(2):
            self.poll(self.sample(snr=30))
        self.assertEqual(self.api.request.call_count, 2)
        self.poll(self.sample(snr=30))
        self.api.request.assert_called_with("config_set", cells={"1": {"pdsch_mcs": 11}})


if __name__ == "__main__":
    unittest.main()
