"""
Rail vibration tracking engine for SafeGuard.

This module deliberately contains no Tkinter or Flask dependencies.
It consumes image frames and emits displacement samples that can be
passed to systems.rail.analyzer.analyze_fft().

Expected companion-module interfaces:
- ImagePreprocessor(...).process(frame) -> dict with gray, gray_raw,
  is_blurry, gamma, mean_brightness
- locate_template(gray, anchor, template, search_margin, clahe)
- BackgroundTracker(clahe, search_margin=0), with initialize(),
  track(), calculate_compensated_displacement(), and reset()
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from threading import RLock
from time import monotonic
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .analyzer import analyze_fft
from .background import BackgroundTracker
from .baseline import (
    FrequencyBaseline,
    append_normal_sample,
    classify_frequency,
    compute_baseline as compute_frequency_baseline,
    load_baseline as load_frequency_baseline,
)
from .preprocessing import ImagePreprocessor
from .tracker import locate_template


ROI = Tuple[int, int, int, int]


@dataclass
class RailFrameResult:
    """Result for one processed frame."""

    timestamp: float
    status: str
    is_blurry: bool
    confidence: float
    x_px: Optional[float]
    y_px: Optional[float]
    dx_px: Optional[float]
    dy_px: Optional[float]
    background_confidence: float
    shake_compensation: bool
    gamma: float
    mean_brightness: float
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RailEngine:
    """
    Stateful rail ROI tracker.

    ROI format is (x, y, width, height). Coordinates and displacement are
    measured in pixels. Physical units require a separate calibration step.
    """

    def __init__(
        self,
        fps: float = 30.0,
        direction: str = "y",
        blur_detect: bool = True,
        low_light: bool = False,
        denoise: bool = True,
        shake_compensation: bool = True,
        confidence_threshold: float = 0.35,
        background_confidence_threshold: float = 0.20,
        search_margin: int = 40,
        history_size: int = 4096,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        if direction not in ("x", "y", "xy"):
            raise ValueError("direction must be 'x', 'y', or 'xy'")

        self.fps = float(fps)
        self.direction = direction
        self.confidence_threshold = float(confidence_threshold)
        self.background_confidence_threshold = float(
            background_confidence_threshold
        )
        self.search_margin = max(0, int(search_margin))
        self.shake_compensation_enabled = bool(shake_compensation)

        self.preprocessor = ImagePreprocessor(
            blur_detect=blur_detect,
            low_light=low_light,
            denoise=denoise,
        )
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.background = BackgroundTracker(
            self.clahe, search_margin=self.search_margin
        )

        self.roi: Optional[ROI] = None
        self.template: Optional[np.ndarray] = None
        self.template_offset: Tuple[float, float] = (0.0, 0.0)
        self.found_x: Optional[float] = None
        self.found_y: Optional[float] = None
        self.confidence = 0.0

        self.displacement_x: Deque[float] = deque(maxlen=history_size)
        self.displacement_y: Deque[float] = deque(maxlen=history_size)
        self.timestamps: Deque[float] = deque(maxlen=history_size)
        self.confidence_history: Deque[float] = deque(maxlen=10)

        self.track_lost_frames = 0
        self.recovery_search_after = 45
        self.recovery_reset_after = 120
        self.last_result: Optional[RailFrameResult] = None
        self._start_time: Optional[float] = None
        self._lock = RLock()

        # Frequency-analysis and normal-baseline state.
        self._baseline_helper = FrequencyBaseline()
        self._baselines: Dict[str, Dict[str, Any]] = {}
        self._last_analysis: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # ROI and state management
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_roi(roi: Sequence[int], frame_shape: Sequence[int]) -> ROI:
        if len(roi) != 4:
            raise ValueError("ROI must be (x, y, width, height)")
        x, y, w, h = (int(v) for v in roi)
        frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
        if w < 8 or h < 8:
            raise ValueError("ROI width and height must each be at least 8 px")
        if x < 0 or y < 0 or x + w > frame_w or y + h > frame_h:
            raise ValueError("ROI is outside the frame")
        return x, y, w, h

    def initialize_roi(
        self,
        frame: np.ndarray,
        roi: Sequence[int],
        background_roi: Optional[Sequence[int]] = None,
    ) -> None:
        """Initialize rail template and optionally a stationary background ROI."""
        if frame is None or not isinstance(frame, np.ndarray):
            raise ValueError("frame must be a valid image")
        processed = self.preprocessor.process(frame)
        gray = processed["gray"]
        if gray is None:
            raise ValueError("Cannot initialize ROI from a blurry frame")

        x, y, w, h = self._validate_roi(roi, gray.shape)
        template = gray[y:y + h, x:x + w].copy()
        if template.size == 0:
            raise ValueError("ROI produced an empty template")

        with self._lock:
            self.reset()
            self.roi = (x, y, w, h)
            self.template = template
            self.template_offset = (float(x), float(y))
            self.found_x = float(x)
            self.found_y = float(y)
            self.confidence = 1.0
            self._start_time = monotonic()

            if background_roi is not None:
                bx, by, bw, bh = self._validate_roi(background_roi, gray.shape)
                self.background.initialize(gray, (bx, by, bw, bh))

    def initialize_background(self, frame: np.ndarray, roi: Sequence[int]) -> None:
        """Initialize/reinitialize the background reference ROI."""
        processed = self.preprocessor.process(frame)
        gray = processed["gray"]
        if gray is None:
            raise ValueError("Cannot initialize background from a blurry frame")
        bg_roi = self._validate_roi(roi, gray.shape)
        self.background.initialize(gray, bg_roi)

    def reset(self) -> None:
        """Clear tracking/session state while retaining engine configuration."""
        with self._lock:
            self.roi = None
            self.template = None
            self.template_offset = (0.0, 0.0)
            self.found_x = None
            self.found_y = None
            self.confidence = 0.0
            self.displacement_x.clear()
            self.displacement_y.clear()
            self.timestamps.clear()
            self.confidence_history.clear()
            self.track_lost_frames = 0
            self.last_result = None
            self._start_time = None
            self.background.reset()
            self._baseline_helper.reset_session_range()
            self._last_analysis = None

    # ------------------------------------------------------------------
    # Automatic ROI selection
    # ------------------------------------------------------------------

    def auto_detect_roi(
        self,
        frames: Iterable[np.ndarray],
        include_background: bool = True,
        padding: int = 8,
    ) -> Dict[str, Optional[ROI]]:
        """
        Detect a moving rail ROI from a short frame sequence.

        This follows the legacy strategy: temporal standard deviation,
        95th-percentile motion mask, morphology, largest connected component.
        """
        gray_frames: List[np.ndarray] = []
        for frame in frames:
            if frame is None:
                continue
            result = self.preprocessor.process(frame)
            gray = result["gray"]
            if gray is not None:
                gray_frames.append(gray)

        if len(gray_frames) < 10:
            raise ValueError("Automatic ROI detection requires at least 10 clear frames")

        shapes = {img.shape for img in gray_frames}
        if len(shapes) != 1:
            raise ValueError("All frames must have the same dimensions")

        stack = np.stack(gray_frames).astype(np.float32)
        motion_map = stack.std(axis=0)
        mean_gray = stack.mean(axis=0).astype(np.uint8)

        max_motion = float(motion_map.max())
        if max_motion < 1.5:
            raise RuntimeError("Insufficient motion to identify a rail ROI")

        threshold = float(np.percentile(motion_map, 95))
        mask = (motion_map >= threshold).astype(np.uint8) * 255
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            raise RuntimeError("No moving component found for rail ROI")

        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h, area = stats[component]
        if area <= 0:
            raise RuntimeError("Detected motion region is empty")

        frame_h, frame_w = mean_gray.shape
        pad = max(0, int(padding))
        x0 = max(0, int(x) - pad)
        y0 = max(0, int(y) - pad)
        x1 = min(frame_w, int(x + w) + pad)
        y1 = min(frame_h, int(y + h) + pad)
        rail_roi = (x0, y0, x1 - x0, y1 - y0)

        background_roi: Optional[ROI] = None
        if include_background:
            candidate = BackgroundTracker.pick_background_roi(
                mean_gray, motion_map, rail_roi
            )
            if candidate is not None:
                background_roi = tuple(int(v) for v in candidate)

        return {
            "rail_roi": rail_roi,
            "background_roi": background_roi,
        }

    # ------------------------------------------------------------------
    # Per-frame tracking
    # ------------------------------------------------------------------

    def _track_background(self, gray: np.ndarray) -> None:
        if self.background is None:
            return

        def locate_func(image, anchor, template, margin):
            return locate_template(
                image, anchor, template, margin, self.clahe
            )

        self.background.track(gray, locate_func)

    def _background_is_usable(self) -> bool:
        return (
            self.shake_compensation_enabled
            and getattr(self.background, "bg_template", None) is not None
            and float(getattr(self.background, "bg_confidence", 0.0))
            >= self.background_confidence_threshold
        )

    def _recover_tracking(self, gray: np.ndarray) -> str:
        """Attempt whole-frame template reacquisition after 45 lost frames."""
        if self.template is None or self.roi is None:
            return "roi_not_initialized"

        if self.track_lost_frames == self.recovery_search_after:
            h, w = gray.shape
            anchor = (0, 0, w, h)
            found_x, found_y, confidence = locate_template(
                gray,
                anchor,
                self.template,
                max(w, h),
                self.clahe,
            )
            if (
                found_x is not None
                and found_y is not None
                and confidence >= 0.4
            ):
                self.found_x = float(found_x)
                self.found_y = float(found_y)
                self.template_offset = (float(found_x), float(found_y))
                self.confidence = float(confidence)
                self.track_lost_frames = 0
                self.confidence_history.clear()
                if hasattr(self.background, "comp_baseline"):
                    self.background.comp_baseline = None
                return "recovered"

        if self.track_lost_frames >= self.recovery_reset_after:
            return "recovery_required"
        return "tracking_lost"

    def process_frame(
        self,
        frame: np.ndarray,
        timestamp: Optional[float] = None,
    ) -> RailFrameResult:
        """
        Process one frame.

        timestamp is seconds on a monotonic clock. If omitted, monotonic()
        is used. The caller should pass capture timestamps when available.
        """
        if frame is None or not isinstance(frame, np.ndarray):
            raise ValueError("frame must be a valid image")

        ts = float(monotonic() if timestamp is None else timestamp)
        processed = self.preprocessor.process(frame)
        gray = processed["gray"]

        with self._lock:
            if self.roi is None or self.template is None:
                raise RuntimeError("Call initialize_roi() before process_frame()")

            if gray is None:
                result = RailFrameResult(
                    timestamp=ts,
                    status="blurry",
                    is_blurry=True,
                    confidence=self.confidence,
                    x_px=self.found_x,
                    y_px=self.found_y,
                    dx_px=None,
                    dy_px=None,
                    background_confidence=float(
                        getattr(self.background, "bg_confidence", 0.0)
                    ),
                    shake_compensation=False,
                    gamma=float(processed.get("gamma", 1.0)),
                    mean_brightness=float(
                        processed.get("mean_brightness", 0.0)
                    ),
                    message="Blur detected; displacement sample skipped",
                )
                self.last_result = result
                return result

            self._track_background(gray)

            x, y, w, h = self.roi
            margin = max(self.search_margin, int(max(w, h) // 2))
            found_x, found_y, confidence = locate_template(
                gray,
                (int(round(self.found_x or x)),
                 int(round(self.found_y or y)), w, h),
                self.template,
                margin,
                self.clahe,
            )

            if found_x is None or found_y is None:
                confidence = 0.0

            self.confidence = float(confidence)
            self.confidence_history.append(self.confidence)
            smoothed_confidence = float(np.mean(self.confidence_history))

            if (
                found_x is None
                or found_y is None
                or smoothed_confidence < self.confidence_threshold
            ):
                self.track_lost_frames += 1
                recovery = self._recover_tracking(gray)
                result = RailFrameResult(
                    timestamp=ts,
                    status=recovery,
                    is_blurry=False,
                    confidence=self.confidence,
                    x_px=self.found_x,
                    y_px=self.found_y,
                    dx_px=None,
                    dy_px=None,
                    background_confidence=float(
                        getattr(self.background, "bg_confidence", 0.0)
                    ),
                    shake_compensation=False,
                    gamma=float(processed.get("gamma", 1.0)),
                    mean_brightness=float(
                        processed.get("mean_brightness", 0.0)
                    ),
                    message="Rail template confidence below threshold",
                )
                self.last_result = result
                return result

            self.track_lost_frames = 0
            self.found_x = float(found_x)
            self.found_y = float(found_y)

            shake_active = self._background_is_usable()
            if shake_active:
                dx, dy = self.background.calculate_compensated_displacement(
                    self.found_x, self.found_y
                )
            else:
                dx = self.found_x - self.template_offset[0]
                dy = self.found_y - self.template_offset[1]

            dx = float(dx)
            dy = float(dy)
            self.timestamps.append(ts)
            self.displacement_x.append(dx)
            self.displacement_y.append(dy)

            result = RailFrameResult(
                timestamp=ts,
                status="tracking",
                is_blurry=False,
                confidence=self.confidence,
                x_px=self.found_x,
                y_px=self.found_y,
                dx_px=dx,
                dy_px=dy,
                background_confidence=float(
                    getattr(self.background, "bg_confidence", 0.0)
                ),
                shake_compensation=shake_active,
                gamma=float(processed.get("gamma", 1.0)),
                mean_brightness=float(
                    processed.get("mean_brightness", 0.0)
                ),
                message="",
            )
            self.last_result = result
            return result

    # ------------------------------------------------------------------
    # Data access for FFT/API
    # ------------------------------------------------------------------

    def get_signal(self, direction: Optional[str] = None) -> Dict[str, Any]:
        """Return a consistent snapshot of displacement and timestamps."""
        selected = self.direction if direction is None else direction
        if selected not in ("x", "y", "xy"):
            raise ValueError("direction must be 'x', 'y', or 'xy'")

        with self._lock:
            x_values = np.asarray(self.displacement_x, dtype=float)
            y_values = np.asarray(self.displacement_y, dtype=float)
            times = np.asarray(self.timestamps, dtype=float)

        if selected == "x":
            signal = x_values
        elif selected == "y":
            signal = y_values
        else:
            signal = np.sqrt(x_values ** 2 + y_values ** 2)

        return {
            "direction": selected,
            "timestamps": times.tolist(),
            "signal": signal.tolist(),
            "sample_count": int(signal.size),
        }

    def estimate_sample_rate(self) -> Optional[float]:
        """Estimate effective sample rate from actual monotonic timestamps."""
        with self._lock:
            times = np.asarray(self.timestamps, dtype=float)
        if times.size < 3:
            return None
        intervals = np.diff(times)
        intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
        if intervals.size == 0:
            return None
        return float(1.0 / np.median(intervals))

    def analyze_signal(
        self,
        direction: Optional[str] = None,
        band_low_hz: Optional[float] = None,
        band_high_hz: Optional[float] = None,
        baseline_label: str = "normal",
    ) -> Dict[str, Any]:
        """
        Run FFT on the currently buffered displacement signal.

        The FFT assumes uniformly spaced samples. This method uses the
        effective sample rate estimated from timestamps; callers should
        ensure capture timestamps are regular before relying on the result.
        """
        signal_data = self.get_signal(direction)
        signal = signal_data["signal"]
        sample_rate = self.estimate_sample_rate()

        if sample_rate is None:
            raise RuntimeError(
                "At least three valid timestamped samples are required "
                "to estimate the sample rate."
            )
        if len(signal) < 4:
            raise RuntimeError("At least four displacement samples are required.")

        analysis = analyze_fft(
            signal,
            sample_rate,
            band_low_hz=band_low_hz,
            band_high_hz=band_high_hz,
        )

        peak_frequency = float(analysis["frequency"])
        session_min, session_max = self._baseline_helper.update_session_range(
            peak_frequency
        )

        analysis.update({
            "direction": signal_data["direction"],
            "sample_rate_hz": float(sample_rate),
            "sample_count": int(signal_data["sample_count"]),
            "session_freq_min_hz": session_min,
            "session_freq_max_hz": session_max,
            "baseline_label": baseline_label,
        })

        baseline = self._baselines.get(baseline_label)
        baseline_status = classify_frequency(peak_frequency, baseline)
        analysis["baseline_status"] = baseline_status
        analysis["is_abnormal"] = (
            True if baseline_status == "abnormal"
            else False if baseline_status == "normal"
            else None
        )
        if baseline:
            analysis["normal_range_hz"] = [
                baseline.get("freq_lo_3sigma"),
                baseline.get("freq_hi_3sigma"),
            ]
        else:
            analysis["normal_range_hz"] = None

        self._last_analysis = analysis
        return dict(analysis)

    def record_normal_sample(
        self,
        sample_csv,
        label: str = "normal",
        direction: Optional[str] = None,
        **metadata,
    ) -> Dict[str, Any]:
        """
        Analyze the current signal and append its peak result to the sample CSV.

        Optional metadata keys follow append_normal_sample(), such as mode,
        roi, background_shake_std, and timestamp.
        """
        analysis = self.analyze_signal(
            direction=direction,
            baseline_label=label,
        )
        peaks = analysis.get("top_peaks", [])

        row = append_normal_sample(
            sample_csv,
            peak_freq_hz=analysis["frequency"],
            label=label,
            mode=metadata.pop("mode", "camera"),
            fps=metadata.pop("fps", self.fps),
            roi=metadata.pop("roi", self.roi),
            direction=analysis["direction"],
            peak_amp=analysis.get("amplitude"),
            snr_db=analysis.get("snr_db"),
            peak2_freq_hz=peaks[1]["frequency"] if len(peaks) > 1 else None,
            peak2_amp=peaks[1]["amplitude"] if len(peaks) > 1 else None,
            peak3_freq_hz=peaks[2]["frequency"] if len(peaks) > 2 else None,
            peak3_amp=peaks[2]["amplitude"] if len(peaks) > 2 else None,
            waveform=analysis.get("waveform"),
            phase=analysis.get("phase"),
            disp_rms_px=analysis.get("rms"),
            session_freq_min_hz=analysis.get("session_freq_min_hz"),
            session_freq_max_hz=analysis.get("session_freq_max_hz"),
            **metadata,
        )
        return row

    def build_baseline(
        self,
        sample_csv,
        output_csv=None,
        min_samples: int = 2,
    ) -> List[Dict[str, Any]]:
        """Build per-label normal ranges from recorded sample data."""
        rows = compute_frequency_baseline(
            sample_csv,
            output_csv=output_csv,
            min_samples=min_samples,
        )
        self._baselines = {row["label"]: row for row in rows}
        return rows

    def load_baselines(self, baseline_csv) -> Dict[str, Dict[str, Any]]:
        """Load previously calculated per-label normal ranges."""
        self._baselines = load_frequency_baseline(baseline_csv)
        return dict(self._baselines)

    def classify_frequency(
        self,
        frequency_hz: float,
        label: str = "normal",
    ) -> str:
        """Classify one frequency against a loaded baseline label."""
        return classify_frequency(frequency_hz, self._baselines.get(label))

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            result = self.last_result.to_dict() if self.last_result else None
            return {
                "initialized": self.roi is not None and self.template is not None,
                "roi": list(self.roi) if self.roi else None,
                "fps_configured": self.fps,
                "direction": self.direction,
                "sample_count": len(self.timestamps),
                "track_lost_frames": self.track_lost_frames,
                "confidence": self.confidence,
                "shake_compensation_enabled": self.shake_compensation_enabled,
                "session_freq_min_hz": self._baseline_helper.session_min,
                "session_freq_max_hz": self._baseline_helper.session_max,
                "baseline_labels": sorted(self._baselines.keys()),
                "last_result": result,
            }
