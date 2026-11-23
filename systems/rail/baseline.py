"""
Rail vibration normal-baseline utilities.

The calculation follows the legacy frequency_legacy.py logic:
- Group recorded peak frequencies by label.
- Compute mean and sample standard deviation (ddof=1).
- Set the normal interval to mean +/- 3 * standard deviation.
- Compute mean SNR and mean displacement RMS when those columns exist.

A baseline with fewer than two frequency samples is marked insufficient.
Its standard deviation and interval are not treated as reliable.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


SAMPLE_COLUMNS = [
    "timestamp",
    "label",
    "mode",
    "fps",
    "roi",
    "direction",
    "peak_freq_hz",
    "peak_amp",
    "snr_db",
    "peak2_freq_hz",
    "peak2_amp",
    "peak3_freq_hz",
    "peak3_amp",
    "waveform",
    "phase",
    "disp_rms_px",
    "background_shake_std",
    "session_freq_min_hz",
    "session_freq_max_hz",
]

BASELINE_COLUMNS = [
    "label",
    "count",
    "freq_mean_hz",
    "freq_std_hz",
    "freq_lo_3sigma",
    "freq_hi_3sigma",
    "snr_mean_db",
    "disp_rms_mean_px",
    "sufficient_samples",
]


def _finite_float(value, field_name: str, *, allow_none: bool = False):
    if value is None or value == "":
        if allow_none:
            return None
        raise ValueError(f"{field_name} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite.")
    return number


def append_normal_sample(
    csv_path,
    *,
    peak_freq_hz,
    label="normal",
    mode="camera",
    fps=None,
    roi=None,
    direction=None,
    peak_amp=None,
    snr_db=None,
    peak2_freq_hz=None,
    peak2_amp=None,
    peak3_freq_hz=None,
    peak3_amp=None,
    waveform=None,
    phase=None,
    disp_rms_px=None,
    background_shake_std=None,
    session_freq_min_hz=None,
    session_freq_max_hz=None,
    timestamp=None,
):
    """Append one measured sample to the legacy-compatible sample CSV."""
    frequency = _finite_float(peak_freq_hz, "peak_freq_hz")
    if frequency <= 0:
        raise ValueError("peak_freq_hz must be greater than zero.")
    if not str(label).strip():
        raise ValueError("label must not be empty.")

    row = {
        "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
        "label": str(label).strip(),
        "mode": mode or "",
        "fps": fps if fps is not None else "",
        "roi": roi if roi is not None else "",
        "direction": direction if direction is not None else "",
        "peak_freq_hz": frequency,
        "peak_amp": peak_amp if peak_amp is not None else "",
        "snr_db": snr_db if snr_db is not None else "",
        "peak2_freq_hz": peak2_freq_hz if peak2_freq_hz is not None else "",
        "peak2_amp": peak2_amp if peak2_amp is not None else "",
        "peak3_freq_hz": peak3_freq_hz if peak3_freq_hz is not None else "",
        "peak3_amp": peak3_amp if peak3_amp is not None else "",
        "waveform": waveform if waveform is not None else "",
        "phase": phase if phase is not None else "",
        "disp_rms_px": disp_rms_px if disp_rms_px is not None else "",
        "background_shake_std": (
            background_shake_std if background_shake_std is not None else ""
        ),
        "session_freq_min_hz": (
            session_freq_min_hz if session_freq_min_hz is not None else ""
        ),
        "session_freq_max_hz": (
            session_freq_max_hz if session_freq_max_hz is not None else ""
        ),
    }

    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=SAMPLE_COLUMNS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
    return row


def _mean(values):
    return sum(values) / len(values) if values else None


def _sample_std(values):
    if len(values) < 2:
        return None
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def compute_baseline(sample_csv, output_csv=None, min_samples=2):
    """
    Compute per-label mean, sample standard deviation and +/-3 sigma limits.

    Returns a list of dictionaries. For fewer than min_samples valid frequency
    samples, interval fields are None and sufficient_samples is False.
    """
    if min_samples < 2:
        raise ValueError("min_samples must be at least 2.")

    path = Path(sample_csv)
    if not path.exists():
        raise FileNotFoundError(f"Sample CSV not found: {path}")

    grouped = {}
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError("Sample CSV must contain a 'label' column.")
        if "peak_freq_hz" not in reader.fieldnames:
            raise ValueError("Sample CSV must contain a 'peak_freq_hz' column.")

        for row in reader:
            label = (row.get("label") or "normal").strip() or "normal"
            try:
                frequency = _finite_float(row.get("peak_freq_hz"), "peak_freq_hz")
            except ValueError:
                continue
            if frequency <= 0:
                continue

            item = grouped.setdefault(label, {"freq": [], "snr": [], "rms": []})
            item["freq"].append(frequency)

            for source_key, target_key in (
                ("snr_db", "snr"),
                ("disp_rms_px", "rms"),
            ):
                try:
                    value = _finite_float(row.get(source_key), source_key)
                except ValueError:
                    continue
                item[target_key].append(value)

    results = []
    for label, values in grouped.items():
        frequencies = values["freq"]
        count = len(frequencies)
        mean_freq = _mean(frequencies)
        std_freq = _sample_std(frequencies)
        sufficient = count >= min_samples and std_freq is not None

        results.append({
            "label": label,
            "count": count,
            "freq_mean_hz": mean_freq,
            "freq_std_hz": std_freq,
            "freq_lo_3sigma": mean_freq - 3.0 * std_freq if sufficient else None,
            "freq_hi_3sigma": mean_freq + 3.0 * std_freq if sufficient else None,
            "snr_mean_db": _mean(values["snr"]),
            "disp_rms_mean_px": _mean(values["rms"]),
            "sufficient_samples": sufficient,
        })

    if output_csv is not None:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=BASELINE_COLUMNS)
            writer.writeheader()
            for result in results:
                writer.writerow({
                    key: (
                        "true" if value is True else
                        "false" if value is False else
                        "" if value is None else value
                    )
                    for key, value in result.items()
                })

    return results


def load_baseline(baseline_csv):
    """Load baseline rows and convert numeric fields to Python floats."""
    path = Path(baseline_csv)
    if not path.exists():
        raise FileNotFoundError(f"Baseline CSV not found: {path}")

    rows = {}
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            label = row.get("label", "").strip()
            if not label:
                continue

            def number(key):
                try:
                    return _finite_float(row.get(key), key, allow_none=True)
                except ValueError:
                    return None

            rows[label] = {
                "label": label,
                "count": int(row.get("count") or 0),
                "freq_mean_hz": number("freq_mean_hz"),
                "freq_std_hz": number("freq_std_hz"),
                "freq_lo_3sigma": number("freq_lo_3sigma"),
                "freq_hi_3sigma": number("freq_hi_3sigma"),
                "snr_mean_db": number("snr_mean_db"),
                "disp_rms_mean_px": number("disp_rms_mean_px"),
                "sufficient_samples": (
                    str(row.get("sufficient_samples", "")).lower() == "true"
                ),
            }
    return rows


def classify_frequency(frequency_hz, baseline):
    """
    Classify a measured frequency against one baseline dictionary.

    Returns 'insufficient_data', 'invalid_frequency', 'normal', or 'abnormal'.
    The interval is inclusive: values exactly on either 3-sigma boundary
    are considered normal.
    """
    try:
        frequency = _finite_float(frequency_hz, "frequency_hz")
    except ValueError:
        return "invalid_frequency"

    if frequency <= 0:
        return "invalid_frequency"

    if not baseline or not baseline.get("sufficient_samples"):
        return "insufficient_data"

    low = baseline.get("freq_lo_3sigma")
    high = baseline.get("freq_hi_3sigma")
    if low is None or high is None:
        return "insufficient_data"

    # Small floating-point tolerance keeps mathematically exact 3-sigma
    # boundary values from being misclassified due to binary rounding.
    tolerance = 1e-12 * max(1.0, abs(low), abs(high), abs(frequency))
    return (
        "normal"
        if low - tolerance <= frequency <= high + tolerance
        else "abnormal"
    )


class FrequencyBaseline:
    """Small in-memory helper for session range and CSV baseline operations."""

    def __init__(self):
        self.session_min = None
        self.session_max = None

    def update_session_range(self, frequency_hz):
        frequency = _finite_float(frequency_hz, "frequency_hz")
        if frequency <= 0:
            return self.session_min, self.session_max
        self.session_min = (
            frequency if self.session_min is None
            else min(self.session_min, frequency)
        )
        self.session_max = (
            frequency if self.session_max is None
            else max(self.session_max, frequency)
        )
        return self.session_min, self.session_max

    def reset_session_range(self):
        self.session_min = None
        self.session_max = None
