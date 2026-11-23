import numpy as np

from .analyzer import analyze_fft


def run_test():
    sample_rate = 1000.0
    duration = 5.0
    t = np.arange(int(sample_rate * duration)) / sample_rate

    # 基準訊號：10 Hz、振幅 2 px、相位 30 度。
    signal = 2.0 * np.sin(2.0 * np.pi * 10.0 * t + np.deg2rad(30.0))
    result = analyze_fft(signal, sample_rate)

    print("===== Rail FFT 擴充功能測試 =====")
    print(f"主頻率：{result['frequency']:.4f} Hz")
    print(f"主振幅：{result['amplitude']:.4f} px")
    print(f"主相位：{result['phase']:.2f}°")
    print(f"RMS：{result['rms']:.4f} px")
    print(f"SNR：{result['snr_db']}")
    print(f"波形分類：{result['waveform']}")
    print(f"Top peaks：{result['top_peaks']}")

    assert abs(result["frequency"] - 10.0) <= 0.2
    assert abs(result["amplitude"] - 2.0) <= 0.03
    assert abs(result["rms"] - (2.0 / np.sqrt(2.0))) <= 0.01
    assert len(result["top_peaks"]) >= 1
    print("[通過] 基本 FFT、振幅、RMS、Top peaks")

    # 頻帶限制：只搜尋 15–25 Hz，應辨識 20 Hz。
    mixed = (
        2.0 * np.sin(2.0 * np.pi * 10.0 * t)
        + 0.8 * np.sin(2.0 * np.pi * 20.0 * t)
    )
    band_result = analyze_fft(
        mixed, sample_rate, band_low_hz=15.0, band_high_hz=25.0
    )
    print(f"頻帶限制後主頻率：{band_result['frequency']:.4f} Hz")
    assert abs(band_result["frequency"] - 20.0) <= 0.2
    print("[通過] Band-pass 頻帶搜尋")

    # 含第三諧波的訊號，確認波形分類流程可執行。
    harmonic = (
        np.sin(2.0 * np.pi * 10.0 * t)
        + 0.5 * np.sin(2.0 * np.pi * 30.0 * t)
    )
    harmonic_result = analyze_fft(harmonic, sample_rate)
    assert harmonic_result["waveform"] in {
        "sine", "square", "triangle", "other/mixed", "cannot_classify", "--"
    }
    print(f"[通過] 波形分類流程：{harmonic_result['waveform']}")

    print("Rail FFT 擴充功能測試通過！")


if __name__ == "__main__":
    run_test()
