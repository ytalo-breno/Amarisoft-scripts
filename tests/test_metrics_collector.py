import unittest

from metrics_collector import rows_from_response


class MetricsCollectorTests(unittest.TestCase):
    def test_creates_one_row_per_cell_and_keeps_raw_metrics(self):
        response = {"ue_list": [{"rnti": 42, "cells": [
            {"cell_id": 1, "cqi": 9, "dl_mcs": 12, "snr": 15.5},
            {"cell_id": 2, "cqi": 7, "dl_mcs": 8},
        ]}]}
        rows = rows_from_response(response, "native", 3, 1.25)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_label"], "native")
        self.assertEqual(rows[0]["rnti"], 42)
        self.assertEqual(rows[0]["dl_mcs"], 12)
        self.assertIn('"snr": 15.5', rows[0]["raw_metrics"])

    def test_rejects_invalid_ue_list(self):
        with self.assertRaises(Exception):
            rows_from_response({}, "native", 0, 0)


if __name__ == "__main__":
    unittest.main()