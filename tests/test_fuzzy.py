import math
import unittest
from unittest.mock import Mock

from fuzzy_bler import APIError, FuzzyController, infer_delta


class FuzzyTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.controller = FuzzyController(self.api)

    def poll(self, *samples):
        self.api.request.return_value = {"ue_list": [{"cells": list(samples)}]}
        self.controller.poll()

    def sample(self, **overrides):
        return dict(dict(cell_id=1, cqi=15, dl_mcs=10, dl_bler=0.2), **overrides)

    def test_rule_coverage(self):
        # Extremos, picos e interseções das funções, incluindo a lacuna original.
        for bler in [0, .03, .05, .10, .15, .20, .30, .40, 1]:
            for cqi in range(16):
                with self.subTest(bler=bler, cqi=cqi):
                    self.assertTrue(-4 <= infer_delta(bler, cqi) <= 2)
        self.assertLess(infer_delta(.20, 15), 0)

    def test_invalid_inputs_are_not_clipped(self):
        for bler, cqi in [(-1, 15), (math.nan, 2), (.1, 16), (.1, None)]:
            with self.assertRaises(ValueError):
                infer_delta(bler, cqi)

    def test_missing_metric_blocks_entire_cell(self):
        missing = self.sample()
        del missing['dl_bler']
        self.poll(self.sample(), missing)
        self.api.request.assert_called_once_with('ue_get', stats=True)

    def test_one_integer_command_with_worst_cqi(self):
        self.poll(self.sample(dl_mcs=10.7), self.sample(cqi=3))
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 2}})
        self.assertEqual(self.api.request.call_count, 2)

    def test_zero_mcs_never_increases_at_high_bler(self):
        self.poll(self.sample(dl_mcs=0))
        self.api.request.assert_called_once_with('ue_get', stats=True)

    def test_recovery_requires_three_samples(self):
        for _ in range(2):
            self.poll(self.sample(dl_bler=0))
        self.assertEqual(self.api.request.call_count, 2)
        self.poll(self.sample(dl_bler=0))
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 11}})

    def test_target_bler_cannot_increase_mcs(self):
        self.poll(self.sample(dl_bler=.10))
        for call in self.api.request.call_args_list:
            if call.args[0] == 'config_set':
                self.assertLessEqual(call.kwargs['cells']['1']['pdsch_mcs'], 10)

    def test_disconnected_cells_clear_history(self):
        self.poll(self.sample(dl_bler=0))
        self.poll()
        self.assertEqual(self.controller.stable, {})

    def test_api_error_is_propagated(self):
        self.api.request.side_effect = [
            {'ue_list': [{'cells': [self.sample()]}]}, APIError('rejected')]
        with self.assertRaises(APIError):
            self.controller.poll()


if __name__ == '__main__':
    unittest.main()
