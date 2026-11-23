import math
import unittest
from unittest.mock import Mock

from fuzzy_bler import APIError, FuzzyController, get_max_mcs_for_cqi, infer_mcs


class FuzzyTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.controller = FuzzyController(self.api)

    def poll(self, *samples):
        self.api.request.return_value = {'ue_list': [{'cells': list(samples)}]}
        self.controller.poll()

    def sample(self, **overrides):
        return dict(dict(cell_id=1, cqi=15), **overrides)

    def test_rule_coverage_and_monotonicity(self):
        outputs = [infer_mcs(index / 4) for index in range(61)]
        self.assertEqual(outputs, sorted(outputs))
        for index in range(16):
            self.assertEqual(infer_mcs(index), get_max_mcs_for_cqi(index))

    def test_invalid_cqi_is_not_clipped(self):
        for cqi in [-1, math.nan, math.inf, 16, None, True, '10']:
            with self.subTest(cqi=cqi), self.assertRaises(ValueError):
                infer_mcs(cqi)

    def test_bler_counters_and_observed_mcs_do_not_determine_target(self):
        for fields in [{}, {'dl_bler': 1, 'dl_tx': 0, 'dl_err': 99},
                       {'dl_bler': 0, 'dl_mcs': 0}, {'dl_bler': math.nan, 'dl_mcs': 28}]:
            self.api.reset_mock()
            self.poll(self.sample(**fields))
            self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 27}})

    def test_missing_cqi_blocks_entire_cell(self):
        self.poll(self.sample(), {'cell_id': 1})
        self.api.request.assert_called_once_with('ue_get', stats=True)

    def test_one_command_per_cell_uses_worst_cqi(self):
        self.poll(self.sample(), self.sample(cqi=3))
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 3}})
        self.assertEqual(self.api.request.call_count, 2)

    def test_cqi_zero_sets_minimum(self):
        self.poll(self.sample(cqi=0))
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 0}})

    def test_max_mcs_limit(self):
        self.controller = FuzzyController(self.api, max_mcs=12)
        self.poll(self.sample())
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 12}})

    def test_matching_observation_avoids_command(self):
        self.poll(self.sample(dl_mcs=27))
        self.api.request.assert_called_once_with('ue_get', stats=True)

    def test_fractional_observation_does_not_hide_change(self):
        self.poll(self.sample(dl_mcs=27.4))
        self.api.request.assert_called_with('config_set', cells={'1': {'pdsch_mcs': 27}})

    def test_disconnected_cell_needs_no_history(self):
        self.poll()
        self.api.request.assert_called_once_with('ue_get', stats=True)

    def test_api_error_is_propagated(self):
        self.api.request.side_effect = [
            {'ue_list': [{'cells': [self.sample()]}]}, APIError('rejected')]
        with self.assertRaises(APIError):
            self.controller.poll()
