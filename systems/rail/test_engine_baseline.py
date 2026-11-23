import csv
import tempfile
import unittest
from collections import deque
from pathlib import Path
from threading import RLock

import numpy as np

from .baseline import compute_baseline
from .engine import RailEngine
from .baseline import FrequencyBaseline


def make_engine_with_signal(signal, sample_rate):
    """Create a lightweight RailEngine instance with buffered test samples."""
    engine = RailEngine.__new__(RailEngine)
    engine.direction = "y"
    engine.fps = float(sample_rate)
    engine._lock = RLock()
    engine.displacement_x = deque([0.0] * len(signal))
    engine.displacement_y = deque(np.asarray(signal, dtype=float).tolist())
    engine.timestamps = deque(
        (np.arange(len(signal), dtype=float) / sample_rate).tolist()
    )
    engine._baseline_helper = FrequencyBaseline()
    engine._baselines = {}
    engine._last_analysis = None
    engine.roi = (10, 10, 20, 20)
    return engine


class TestEngineBaselineIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.samples_csv = self.root / "normal_samples.csv"
        self.baseline_csv = self.root / "normal_baseline.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_engine_fft_and_baseline_classification(self):
        fs = 100.0
        t = np.arange(1000) / fs
        signal = 2.0 * np.sin(2 * np.pi * 10.0 * t)
        engine = make_engine_with_signal(signal, fs)

        # Train a narrow baseline around 10 Hz.
        with self.samples_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["label", "peak_freq_hz"])
            writer.writeheader()
            for frequency in (9.9, 10.0, 10.1):
                writer.writerow({"label": "normal", "peak_freq_hz": frequency})

        engine.build_baseline(self.samples_csv, self.baseline_csv)
        result = engine.analyze_signal()

        self.assertAlmostEqual(result["frequency"], 10.0, places=6)
        self.assertEqual(result["baseline_status"], "normal")
        self.assertFalse(result["is_abnormal"])
        self.assertIsNotNone(result["normal_range_hz"])

    def test_insufficient_baseline_does_not_claim_normal(self):
        fs = 100.0
        t = np.arange(1000) / fs
        engine = make_engine_with_signal(np.sin(2 * np.pi * 10 * t), fs)
        engine._baselines = {
            "normal": {
                "label": "normal",
                "count": 1,
                "freq_lo_3sigma": None,
                "freq_hi_3sigma": None,
                "sufficient_samples": False,
            }
        }

        result = engine.analyze_signal()
        self.assertEqual(result["baseline_status"], "insufficient_data")
        self.assertIsNone(result["is_abnormal"])

    def test_record_normal_sample_writes_fft_fields(self):
        fs = 100.0
        t = np.arange(1000) / fs
        engine = make_engine_with_signal(1.5 * np.sin(2 * np.pi * 8 * t), fs)

        row = engine.record_normal_sample(self.samples_csv)
        self.assertAlmostEqual(float(row["peak_freq_hz"]), 8.0, places=6)

        with self.samples_csv.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 1)
        self.assertIn("disp_rms_px", rows[0])
        self.assertIn("snr_db", rows[0])

    def test_classify_frequency_without_loaded_baseline(self):
        engine = make_engine_with_signal([0, 1, 0, -1] * 10, 30.0)
        self.assertEqual(
            engine.classify_frequency(10.0),
            "insufficient_data",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
