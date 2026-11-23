"""
RailEngine integration test for SafeGuard.

Run from the repository root:
    python -m systems.rail.test_engine

This test creates a synthetic 640x480 video containing a textured rail target
that vibrates vertically at 10 Hz with a 2-pixel amplitude. It then checks:
1. RailEngine can initialize and track the target.
2. Tracking confidence remains usable.
3. The displacement signal contains enough samples.
4. FFT recovers a frequency close to 10 Hz.

This is a controlled software test, not a substitute for testing with real
camera footage or validating physical displacement calibration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from .analyzer import analyze_fft
from .engine import RailEngine


WIDTH = 640
HEIGHT = 480
FPS = 30.0
DURATION_SECONDS = 5.0
TARGET_FREQUENCY_HZ = 10.0
TARGET_AMPLITUDE_PX = 2.0

RAIL_ROI = (250, 180, 80, 60)


def make_scene() -> tuple[np.ndarray, np.ndarray]:
    """Create a static background and a distinctive textured rail patch."""
    rng = np.random.default_rng(20261110)

    # A textured background gives the matcher realistic image structure.
    background = rng.integers(
        35, 190, size=(HEIGHT, WIDTH), dtype=np.uint8
    )
    background = cv2.GaussianBlur(background, (3, 3), 0)

    # The target has a different texture and several stable features.
    patch = rng.integers(25, 230, size=(60, 80), dtype=np.uint8)
    patch = cv2.GaussianBlur(patch, (3, 3), 0)
    cv2.rectangle(patch, (5, 5), (74, 54), 245, 2)
    cv2.line(patch, (8, 30), (72, 30), 10, 2)
    cv2.circle(patch, (40, 30), 12, 230, 2)

    return background, patch


def render_frame(
    background: np.ndarray,
    patch: np.ndarray,
    displacement_y: float,
) -> np.ndarray:
    """Render the target at a potentially sub-pixel vertical displacement."""
    x0, y0, _, _ = RAIL_ROI
    transform = np.array(
        [[1.0, 0.0, float(x0)], [0.0, 1.0, float(y0) + displacement_y]],
        dtype=np.float32,
    )

    warped_patch = cv2.warpAffine(
        patch,
        transform,
        (WIDTH, HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    mask_source = np.full(patch.shape, 255, dtype=np.uint8)
    warped_mask = cv2.warpAffine(
        mask_source,
        transform,
        (WIDTH, HEIGHT),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    frame = background.copy()
    frame[warped_mask > 0] = warped_patch[warped_mask > 0]
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


def main() -> int:
    print("===== RailEngine 整合測試 =====")
    print(f"影像尺寸：{WIDTH} x {HEIGHT}")
    print(f"影格率：{FPS:.1f} FPS")
    print(f"模擬振動：{TARGET_FREQUENCY_HZ:.1f} Hz")
    print(f"模擬振幅：{TARGET_AMPLITUDE_PX:.1f} px")
    print(f"測試時間：{DURATION_SECONDS:.1f} 秒")

    background, patch = make_scene()
    frame_count = int(round(FPS * DURATION_SECONDS))

    first_frame = render_frame(background, patch, 0.0)

    engine = RailEngine(
        fps=FPS,
        direction="y",
        blur_detect=False,
        low_light=False,
        denoise=True,
        shake_compensation=False,
        confidence_threshold=0.30,
        search_margin=40,
        history_size=frame_count + 10,
    )

    try:
        engine.initialize_roi(first_frame, RAIL_ROI)
    except Exception as exc:
        print(f"[失敗] ROI 初始化：{type(exc).__name__}: {exc}")
        return 1

    print("[通過] ROI 初始化")

    statuses: dict[str, int] = {}
    confidences: list[float] = []

    for index in range(frame_count):
        timestamp = index / FPS
        displacement = TARGET_AMPLITUDE_PX * np.sin(
            2.0 * np.pi * TARGET_FREQUENCY_HZ * timestamp
        )
        frame = render_frame(background, patch, displacement)

        try:
            result = engine.process_frame(frame, timestamp=timestamp)
        except Exception as exc:
            print(
                f"[失敗] 第 {index + 1} 幀處理："
                f"{type(exc).__name__}: {exc}"
            )
            return 1

        statuses[result.status] = statuses.get(result.status, 0) + 1
        if result.status == "tracking":
            confidences.append(float(result.confidence))

    signal_data = engine.get_signal("y")
    signal = np.asarray(signal_data["signal"], dtype=float)
    sample_rate = engine.estimate_sample_rate()

    print(f"[結果] 追蹤狀態統計：{statuses}")
    print(f"[結果] 有效位移樣本數：{signal.size}")
    print(
        "[結果] 平均追蹤信心值："
        f"{np.mean(confidences):.4f}" if confidences else
        "[結果] 沒有成功追蹤的影格"
    )

    if signal.size < int(FPS * DURATION_SECONDS * 0.8):
        print("[失敗] 有效位移樣本不足（低於預期影格數的 80%）")
        return 1

    if not confidences or float(np.mean(confidences)) < 0.30:
        print("[失敗] 平均追蹤信心值低於 0.30")
        return 1

    if sample_rate is None or not np.isfinite(sample_rate):
        print("[失敗] 無法估算有效取樣率")
        return 1

    print(f"[通過] 位移追蹤樣本數：{signal.size}")
    print(f"[通過] 有效取樣率估算：{sample_rate:.3f} Hz")

    # Remove the DC component before calculating basic signal statistics.
    centered_signal = signal - np.mean(signal)
    measured_rms = float(np.sqrt(np.mean(centered_signal ** 2)))
    print(f"[結果] 位移訊號 RMS：{measured_rms:.4f} px")

    try:
        fft_result = analyze_fft(signal, sample_rate)
    except Exception as exc:
        print(f"[失敗] FFT 分析：{type(exc).__name__}: {exc}")
        return 1

    measured_frequency = float(fft_result["frequency"])
    measured_amplitude = float(fft_result["amplitude"])
    measured_phase = float(fft_result["phase"])

    print(f"[結果] 預期頻率：{TARGET_FREQUENCY_HZ:.3f} Hz")
    print(f"[結果] FFT 頻率：{measured_frequency:.3f} Hz")
    print(f"[結果] FFT 振幅：{measured_amplitude:.4f} px")
    print(f"[結果] FFT 相位：{measured_phase:.2f}°")

    # Frequency tolerance accounts for finite record length and tracking noise.
    if abs(measured_frequency - TARGET_FREQUENCY_HZ) > 0.5:
        print("[失敗] FFT 頻率與預期值相差超過 0.5 Hz")
        return 1

    print("[通過] FFT 頻率辨識")
    print("RailEngine 整合測試通過！")
    print(
        "注意：本測試驗證的是合成影像中的像素位移；"
        "實際設備仍需使用真實影片測試及進行像素/物理單位校正。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
