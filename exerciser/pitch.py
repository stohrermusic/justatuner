"""YIN pitch detection algorithm for monophonic audio."""

import numpy as np


def yin_detect(signal, sample_rate, fmin=80, fmax=2000, threshold=0.25):
    """Detect fundamental frequency using the YIN algorithm.

    Args:
        signal: mono audio buffer (numpy array)
        sample_rate: sample rate in Hz
        fmin: minimum detectable frequency
        fmax: maximum detectable frequency
        threshold: YIN confidence threshold (lower = stricter)

    Returns:
        (frequency, confidence) or (None, 0.0) if no pitch detected.
        Confidence is 0.0 to 1.0.
    """
    N = len(signal)
    tau_min = max(2, int(sample_rate / fmax))
    tau_max = min(N // 2, int(sample_rate / fmin))

    if tau_max <= tau_min:
        return None, 0.0

    # Step 1: Difference function (vectorized)
    d = np.zeros(tau_max)
    for tau in range(1, tau_max):
        diff = signal[:N - tau] - signal[tau:N]
        d[tau] = np.dot(diff, diff)

    # Step 2: Cumulative mean normalized difference
    d[0] = 1.0
    running_sum = 0.0
    for tau in range(1, tau_max):
        running_sum += d[tau]
        if running_sum == 0:
            d[tau] = 1.0
        else:
            d[tau] = d[tau] * tau / running_sum

    # Step 3: Absolute threshold - find first dip below threshold
    tau_best = None
    for tau in range(tau_min, tau_max - 1):
        if d[tau] < threshold:
            # Find local minimum
            if d[tau] <= d[tau + 1]:
                tau_best = tau
                break

    if tau_best is None:
        return None, 0.0

    # Step 4: Parabolic interpolation for sub-sample accuracy
    if 0 < tau_best < tau_max - 1:
        alpha = d[tau_best - 1]
        beta = d[tau_best]
        gamma = d[tau_best + 1]
        denom = alpha - 2 * beta + gamma
        if denom != 0:
            peak = 0.5 * (alpha - gamma) / denom
            tau_refined = tau_best + peak
        else:
            tau_refined = float(tau_best)
    else:
        tau_refined = float(tau_best)

    freq = sample_rate / tau_refined
    confidence = 1.0 - d[tau_best]

    return freq, max(0.0, min(1.0, confidence))


def moving_median_filter(values, window=5):
    """Simple moving median filter to smooth pitch readings."""
    if len(values) < window:
        return values[-1] if values else None
    recent = values[-window:]
    return float(np.median(recent))
