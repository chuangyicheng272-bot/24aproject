import csv
import math
import tempfile
import unittest
from pathlib import Path

from .baseline import (
    FrequencyBaseline,
    append_normal_sample,
    classify_frequency,
    compute_baseline,
    load_baseline,
)


class TestRailBaseline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.samples = self.root / "normal_samples.csv"
        self.baseline_file = self.root / "normal_baseline.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_sample(self, frequency, label="normal", snr=20, rms=1.2):
        append_normal_sample(
            self.samples,
            peak_freq_hz=frequency,
            label=label,
            mode="camera",
            fps=30,
            direction="y",
            snr_db=snr,
            disp_rms_px=rms,
        )

    def test_append_and_legacy_columns(self):
        self.add_sample(10.0)
        with self.samples.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            self.assertEqual(reader.fieldnames[0], "timestamp")
            self.assertIn("peak_freq_hz", reader.fieldnames)
            self.assertIn("disp_rms_px", reader.fieldnames)
            rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["peak_freq_hz"]), 10.0)

    def test_mean_sample_std_and_three_sigma(self):
        for value in (9.8, 10.0, 10.2):
            self.add_sample(value)
        result = compute_baseline(self.samples, self.baseline_file)[0]

        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["freq_mean_hz"], 10.0)
        self.assertAlmostEqual(result["freq_std_hz"], 0.2)
        self.assertAlmostEqual(result["freq_lo_3sigma"], 9.4)
        self.assertAlmostEqual(result["freq_hi_3sigma"], 10.6)
        self.assertTrue(result["sufficient_samples"])
        self.assertTrue(self.baseline_file.exists())

    def test_one_sample_is_insufficient(self):
        self.add_sample(10.0)
        result = compute_baseline(self.samples)[0]
        self.assertEqual(result["count"], 1)
        self.assertIsNone(result["freq_std_hz"])
        self.assertIsNone(result["freq_lo_3sigma"])
        self.assertFalse(result["sufficient_samples"])
        self.assertEqual(classify_frequency(10.0, result), "insufficient_data")

    def test_frequency_classification(self):
        for value in (9.8, 10.0, 10.2):
            self.add_sample(value)
        result = compute_baseline(self.samples)[0]

        self.assertEqual(classify_frequency(10.0, result), "normal")
        self.assertEqual(classify_frequency(9.4, result), "normal")
        self.assertEqual(classify_frequency(10.6, result), "normal")
        self.assertEqual(classify_frequency(9.39, result), "abnormal")
        self.assertEqual(classify_frequency(10.61, result), "abnormal")
        self.assertEqual(classify_frequency(0, result), "invalid_frequency")

    def test_load_baseline(self):
        for value in (9.8, 10.0, 10.2):
            self.add_sample(value)
        compute_baseline(self.samples, self.baseline_file)
        loaded = load_baseline(self.baseline_file)
        self.assertIn("normal", loaded)
        self.assertTrue(loaded["normal"]["sufficient_samples"])
        self.assertAlmostEqual(loaded["normal"]["freq_mean_hz"], 10.0)

    def test_labels_are_grouped_separately(self):
        self.add_sample(10.0, label="normal")
        self.add_sample(10.2, label="normal")
        self.add_sample(15.0, label="maintenance")
        self.add_sample(15.2, label="maintenance")
        results = compute_baseline(self.samples)
        by_label = {row["label"]: row for row in results}
        self.assertEqual(set(by_label), {"normal", "maintenance"})
        self.assertAlmostEqual(by_label["normal"]["freq_mean_hz"], 10.1)
        self.assertAlmostEqual(by_label["maintenance"]["freq_mean_hz"], 15.1)

    def test_session_min_max(self):
        tracker = FrequencyBaseline()
        tracker.update_session_range(10.0)
        tracker.update_session_range(9.5)
        tracker.update_session_range(10.8)
        self.assertAlmostEqual(tracker.session_min, 9.5)
        self.assertAlmostEqual(tracker.session_max, 10.8)
        tracker.reset_session_range()
        self.assertIsNone(tracker.session_min)
        self.assertIsNone(tracker.session_max)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            append_normal_sample(self.samples, peak_freq_hz=0)
        with self.assertRaises(ValueError):
            compute_baseline(self.samples, min_samples=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
