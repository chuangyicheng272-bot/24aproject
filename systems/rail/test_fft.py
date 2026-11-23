
import numpy as np
from systems.rail.analyzer import analyze_fft

sample_rate = 1000
duration = 2.0
time = np.arange(0, duration, 1 / sample_rate)

expected_frequency = 10
expected_amplitude = 2
expected_phase = 30

signal = expected_amplitude * np.cos(
    2 * np.pi * expected_frequency * time
    + np.deg2rad(expected_phase)
)

result = analyze_fft(signal, sample_rate)

print("===== FFT 基準測試 =====")
print(f"預期頻率：{expected_frequency} Hz")
print(f"實際頻率：{result['frequency']:.4f} Hz")
print(f"預期振幅：{expected_amplitude}")
print(f"實際振幅：{result['amplitude']:.4f}")
print(f"預期相位：{expected_phase}°")
print(f"實際相位：{result['phase']:.4f}°")

assert abs(result["frequency"] - expected_frequency) < 0.01
assert abs(result["amplitude"] - expected_amplitude) < 0.05
assert abs(result["phase"] - expected_phase) < 2

print("FFT 基準測試通過！")
