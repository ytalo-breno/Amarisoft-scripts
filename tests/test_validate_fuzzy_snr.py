import csv
import os
import tempfile
import unittest

from validate_fuzzy_snr import summarize, validate_file, validate_rows, write_validation


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

    def test_validates_and_writes_each_file_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = os.path.join(directory, "metrics.csv")
            output_path = os.path.join(directory, "metrics_validation.csv")
            with open(input_path, "w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["pusch_snr", "ul_mcs"])
                writer.writeheader()
                writer.writerow({"pusch_snr": "10", "ul_mcs": "8"})

            rows, summary = validate_file(input_path)
            write_validation(output_path, rows)

            self.assertEqual(summary["validated"], 1)
            with open(output_path, newline="", encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)


if __name__ == "__main__":
    unittest.main()