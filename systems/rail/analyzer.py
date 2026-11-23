import numpy as np


def _find_top_peaks(frequencies, amplitudes, n=3, min_sep_bins=3):
    """Return up to n local spectral peaks, separated by min_sep_bins."""
    frequencies = np.asarray(frequencies, dtype=float)
    amplitudes = np.asarray(amplitudes, dtype=float)

    if len(amplitudes) < 3:
        return []

    candidates = [
        i for i in range(1, len(amplitudes) - 1)
        if amplitudes[i] >= amplitudes[i - 1]
        and amplitudes[i] >= amplitudes[i + 1]
    ]

    if not candidates:
        candidates = [int(np.argmax(amplitudes[1:]) + 1)]

    candidates.sort(key=lambda i: amplitudes[i], reverse=True)

    selected = []
    for index in candidates:
        if all(abs(index - chosen) >= min_sep_bins for chosen in selected):
            selected.append(index)
            if len(selected) >= n:
                break

    return [
        {
            "frequency": float(frequencies[i]),
            "amplitude": float(amplitudes[i]),
            "phase": None,
        }
        for i in selected
    ]


def _classify_waveform(frequencies, amplitudes, peak_frequency):
    """Classify a waveform using the legacy harmonic-ratio thresholds."""
    if len(frequencies) == 0 or peak_frequency <= 0:
        return "--"

    nyquist = float(frequencies[-1])
    if 3.0 * peak_frequency > nyquist:
        return "cannot_classify"

    def harmonic_amplitude(target):
        # A harmonic above Nyquist cannot be measured from this recording.
        if target > nyquist:
            return None
        index = int(np.argmin(np.abs(frequencies - target)))
        lo = max(0, index - 1)
        hi = min(len(amplitudes), index + 2)
        if lo >= hi:
            return 0.0
        return float(np.max(amplitudes[lo:hi]))

    h1 = harmonic_amplitude(peak_frequency)
    if h1 is None or h1 <= 0:
        return "--"

    h3_amp = harmonic_amplitude(3.0 * peak_frequency)
    if h3_amp is None:
        return "cannot_classify"
    h3 = h3_amp / h1

    h5_amp = harmonic_amplitude(5.0 * peak_frequency)
    h5 = None if h5_amp is None else h5_amp / h1

    if h3 < 0.07 and (h5 is None or h5 < 0.05):
        return "sine"
    if h3 > 0.22:
        return "square"
    if 0.07 <= h3 <= 0.20:
        return "triangle"
    return "other/mixed"


def analyze_fft(
    signal,
    sample_rate,
    band_low_hz=None,
    band_high_hz=None,
    top_n=3,
    min_sep_bins=3,
):
    """
    Analyze a uniformly sampled displacement signal.

    Band limits affect peak selection and SNR only. The returned spectrum
    remains the full one-sided spectrum.

    Amplitude uses single-sided Hann-window normalization. Its unit is the
    same as the input signal (for example, pixels for pixel displacement).
    """
    signal = np.asarray(signal, dtype=float)

    if signal.ndim != 1 or len(signal) < 4:
        raise ValueError("Signal must be a 1D array with at least 4 samples.")
    if not np.all(np.isfinite(signal)):
        raise ValueError("Signal must contain only finite values.")
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError("Sample rate must be positive.")
    if top_n < 1 or min_sep_bins < 1:
        raise ValueError("top_n and min_sep_bins must be positive integers.")

    signal = signal - np.mean(signal)
    rms = float(np.sqrt(np.mean(signal ** 2)))

    window = np.hanning(len(signal))
    window_sum = float(np.sum(window))
    if window_sum <= 0:
        raise ValueError("Invalid window.")

    spectrum = np.fft.rfft(signal * window)
    frequencies = np.fft.rfftfreq(len(signal), d=1.0 / sample_rate)

    amplitudes = np.abs(spectrum) * (2.0 / window_sum)
    amplitudes[0] /= 2.0
    if len(signal) % 2 == 0:
        amplitudes[-1] /= 2.0

    phases = np.angle(spectrum, deg=True)

    nyquist = sample_rate / 2.0
    low = 0.0 if band_low_hz is None else float(band_low_hz)
    high = nyquist if band_high_hz is None else float(band_high_hz)

    if not np.isfinite(low) or not np.isfinite(high):
        raise ValueError("Band limits must be finite.")
    low = max(0.0, low)
    high = min(nyquist, high)
    if high <= low:
        raise ValueError("band_high_hz must be greater than band_low_hz.")

    band_mask = (frequencies >= low) & (frequencies <= high)
    band_mask[0] = False  # Exclude DC from peak selection and SNR.
    band_indices = np.flatnonzero(band_mask)

    if len(band_indices) == 0:
        peak_index = int(np.argmax(amplitudes[1:]) + 1)
        selected_indices = [peak_index]
        snr_db = None
        snr_valid = False
    else:
        band_amplitudes = amplitudes[band_indices]
        local_peaks = [
            int(i) for i in band_indices
            if i > 0 and i < len(amplitudes) - 1
            and amplitudes[i] >= amplitudes[i - 1]
            and amplitudes[i] >= amplitudes[i + 1]
        ]
        if local_peaks:
            local_peaks.sort(key=lambda i: amplitudes[i], reverse=True)
            selected_indices = []
            for index in local_peaks:
                if all(abs(index - chosen) >= min_sep_bins
                       for chosen in selected_indices):
                    selected_indices.append(index)
                    if len(selected_indices) >= top_n:
                        break
            peak_index = selected_indices[0]
        else:
            peak_index = int(band_indices[np.argmax(band_amplitudes)])
            selected_indices = [peak_index]

        noise_floor = float(np.median(band_amplitudes))
        peak_amplitude = float(amplitudes[peak_index])
        if noise_floor > 0 and peak_amplitude > 0:
            snr_db = float(20.0 * np.log10(peak_amplitude / noise_floor))
            snr_valid = bool(peak_amplitude >= 5.0 * noise_floor)
        else:
            snr_db = None
            snr_valid = False

    top_peaks = []
    for index in selected_indices[:top_n]:
        top_peaks.append({
            "frequency": float(frequencies[index]),
            "amplitude": float(amplitudes[index]),
            "phase": float(phases[index]),
        })

    peak_frequency = float(frequencies[peak_index])
    peak_amplitude = float(amplitudes[peak_index])

    return {
        # Original API keys retained for compatibility.
        "frequency": peak_frequency,
        "amplitude": peak_amplitude,
        "phase": float(phases[peak_index]),
        "frequencies": frequencies.tolist(),
        "amplitudes": amplitudes.tolist(),
        "phases": phases.tolist(),

        # Extended analysis fields.
        "top_peaks": top_peaks,
        "snr_db": snr_db,
        "snr_valid": snr_valid,
        "waveform": _classify_waveform(frequencies, amplitudes, peak_frequency),
        "rms": rms,
        "band_low_hz": low,
        "band_high_hz": high,
    }
