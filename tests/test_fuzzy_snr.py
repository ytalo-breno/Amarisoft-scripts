import math
import unittest
from unittest.mock import Mock

from fuzzy_snr import FuzzyController, get_max_mcs_for_snr, get_target_mcs, infer_delta


class FuzzySnrTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.controller = FuzzyController(self.api)

    def poll(self, *samples):
        self.api.request.return_value = {"ue_list": [{"cells": list(samples)}]}
        self.controller.poll()

    def sample(self, **overrides):
        return dict(dict(cell_id=1, ul_mcs=10, pusch_snr=0), **overrides)

    def test_rule_direction_and_coverage(self):
        for snr in [-20, 0, 5, 10, 15, 20, 30, 40]:
            with self.subTest(snr=snr):
                self.assertTrue(-2 <= infer_delta(snr, 10) <= 2)
        self.assertLess(infer_delta(-10, 10), 0)
        self.assertGreater(infer_delta(30, 10), 0)

    def test_invalid_inputs_are_not_clipped(self):
        for snr in [-21, math.nan, 40.1, None]:
            with self.assertRaises(ValueError):
                infer_delta(snr, 10)

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
        del missing["pusch_snr"]
        self.poll(self.sample(), missing)
        self.api.request.assert_called_once_with("ue_get", stats=True)

    def test_cqi_is_not_required(self):
        for _ in range(3):
            self.poll(self.sample())
        self.api.request.assert_called_with("config_set", cells={"1": {"pusch_mcs": 9}})

    def test_worst_snr_controls_cell(self):
        for _ in range(3):
            self.poll(self.sample(pusch_snr=10), self.sample(pusch_snr=-5))
        self.api.request.assert_called_with("config_set", cells={"1": {"pusch_mcs": 9}})
        self.assertEqual(self.api.request.call_count, 4)

    def test_recovery_requires_three_high_snr_samples(self):
        for _ in range(2):
            self.poll(self.sample(pusch_snr=30))
        self.assertEqual(self.api.request.call_count, 2)
        self.poll(self.sample(pusch_snr=30))
        self.api.request.assert_called_with("config_set", cells={"1": {"pusch_mcs": 11}})

    def test_constant_moderate_snr_keeps_mcs_ten(self):
        for _ in range(30):
            self.poll(self.sample(pusch_snr=10, ul_mcs=10))
        self.assertEqual(self.api.request.call_count, 30)
        self.assertEqual(get_target_mcs(10), 10)

    def test_closed_loop_converges_from_zero_and_high_mcs(self):
        for initial in (0, 28):
            with self.subTest(initial=initial):
                current = initial
                commands = []

                def request(command, **kwargs):
                    nonlocal current
                    if command == 'ue_get':
                        return {'ue_list': [{'cells': [self.sample(pusch_snr=10, ul_mcs=current)]}]}
                    current = kwargs['cells']['1']['pusch_mcs']
                    commands.append(current)
                    return {}

                api = Mock()
                api.request.side_effect = request
                controller = FuzzyController(api)
                for _ in range(100):
                    controller.poll()
                self.assertTrue(9 <= current <= 11)
                count = len(commands)
                for _ in range(20):
                    controller.poll()
                self.assertEqual(len(commands), count)

    def test_isolated_drop_does_not_change_mcs(self):
        self.poll(self.sample(pusch_snr=-5))
        self.poll(self.sample(pusch_snr=10))
        self.poll(self.sample(pusch_snr=-5))
        self.assertEqual(self.api.request.call_count, 3)

    def test_reversal_restarts_confirmation(self):
        for _ in range(2):
            self.poll(self.sample(pusch_snr=-5))
        for _ in range(2):
            self.poll(self.sample(pusch_snr=30))
        self.assertEqual(self.api.request.call_count, 4)
        self.poll(self.sample(pusch_snr=30))
        self.api.request.assert_called_with('config_set', cells={'1': {'pusch_mcs': 11}})

    def test_invalid_sample_resets_confirmation(self):
        for _ in range(2):
            self.poll(self.sample(pusch_snr=-5))
        self.poll(self.sample(pusch_snr=None))
        self.poll(self.sample(pusch_snr=-5))
        self.assertEqual(self.api.request.call_count, 4)

    def test_maximum_is_respected_and_margin_is_configurable(self):
        self.assertEqual(get_target_mcs(30, max_mcs=10), 10)
        self.assertEqual(get_target_mcs(10, snr_margin_db=0), 12)
        self.assertEqual(infer_delta(30, 10, max_mcs=10), 0)
        self.assertLess(infer_delta(30, 11, max_mcs=10), 0)


if __name__ == "__main__":
    unittest.main()
