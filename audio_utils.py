"""
Shared audio utilities (ported from Stohrer Sax Shop Companion).

Contains the AudioRingBuffer class, the Hann peak-frequency estimator and
the sample-rate-fallback stream openers used by both audio engines. Pure
math/threading — no tkinter dependency; sounddevice is passed in.

Requires: numpy, threading (stdlib)
"""

import logging
import threading

try:
    import numpy as np
except ImportError:
    np = None


class AudioRingBuffer:
    """Thread-safe ring buffer for audio samples."""

    def __init__(self, size):
        self.buffer = np.zeros(size, dtype=np.float32)
        self.write_pos = 0
        self.lock = threading.Lock()
        self.has_data = False
        self.write_count = 0         # Increments on each write
        self.last_read_count = 0     # write_count at last read

    def write(self, data):
        """Write audio data. Called from audio callback thread."""
        n = len(data)
        with self.lock:
            if n >= len(self.buffer):
                self.buffer[:] = data[-len(self.buffer):]
                self.write_pos = 0
            else:
                end = self.write_pos + n
                if end <= len(self.buffer):
                    self.buffer[self.write_pos:end] = data
                else:
                    first = len(self.buffer) - self.write_pos
                    self.buffer[self.write_pos:] = data[:first]
                    self.buffer[:n - first] = data[first:]
                self.write_pos = (self.write_pos + n) % len(self.buffer)
            self.has_data = True
            self.write_count += 1

    def read(self):
        """Read the full buffer in chronological order. Returns None if no data."""
        with self.lock:
            if not self.has_data:
                return None
            self.last_read_count = self.write_count
            return np.roll(self.buffer, -self.write_pos).copy()

    def is_stale(self):
        """True if no new data has been written since last read."""
        with self.lock:
            return self.write_count == self.last_read_count

    def clear(self):
        """Zero out the buffer."""
        with self.lock:
            self.buffer[:] = 0
            self.write_pos = 0
            self.has_data = False
            self.write_count = 0
            self.last_read_count = 0


def hann_peak_freq(mags, k, bin_freq):
    """Frequency (Hz) of a Hann-windowed spectral peak at bin k.

    A parabola through three linear magnitudes is the wrong shape for a
    Hann main lobe and lands up to ~0.05 bin off — on the tuner's 10.77 Hz
    bins that is 0.54 Hz, which at A1 (55 Hz) is 17 cents and at A2 is
    8 cents (measured 2026-10-06: an exactly in-tune A1–A6 sweep read up
    to 15.3 c off, worst at B1). For a Hann window the ratio of the larger
    neighbour to the peak fixes the offset exactly:
    |X[k+1]| / |X[k]| = (1 + d) / (2 - d), so d = (2a - 1) / (a + 1).
    Rejected alternative, measured in SSC: a 4x zero-padded FFT is equally
    accurate at four times the cost.

    The formula needs k to be the lobe's maximum, but callers pick k from
    a fixed window (the engine looks at the 3 bins round the reference
    pitch), which misses the top when a high note is well off pitch: B5
    26 c flat peaks at bin 90 while the window offers 91-93. So climb to
    the local maximum first, at most 2 bins (the Hann main lobe's
    half-width), so the climb can't leave this peak's lobe.

    Only the frequency comes from here; callers read levels as before.

    Args:
        mags: |rfft| of the Hann-windowed frame
        k: bin at or near the peak, 0 < k < len(mags) - 1
        bin_freq: bin width in Hz
    """
    for _ in range(2):
        if k > 1 and mags[k - 1] > mags[k]:
            k -= 1
        elif k < len(mags) - 2 and mags[k + 1] > mags[k]:
            k += 1
        else:
            break
    peak = float(mags[k])
    if peak <= 0:
        return k * bin_freq
    left, right = float(mags[k - 1]), float(mags[k + 1])
    if right >= left:
        a = right / peak
        d = (2.0 * a - 1.0) / (a + 1.0)
    else:
        a = left / peak
        d = -(2.0 * a - 1.0) / (a + 1.0)
    d = max(-0.5, min(0.5, d))
    return (k + d) * bin_freq


# ============================================
# STREAM OPENING WITH SAMPLE-RATE FALLBACK
# ============================================

_log = logging.getLogger(__name__)


def _device_default_rate(sd, device, kind):
    """Return the device's default sample rate (int) or None.

    ``kind`` is "input" or "output". ``device`` may be None (system
    default), an index, or a name — anything sounddevice accepts.
    """
    try:
        info = sd.query_devices(device, kind)
        rate = info.get("default_samplerate")
        return int(round(rate)) if rate else None
    except Exception:
        return None


def _open_with_fallback(sd, kind, device, preferred_rate, **kwargs):
    """Open an Input/OutputStream at ``preferred_rate``; if the device
    refuses that rate, retry at the device's own default rate.

    Windows (MME/WASAPI shared) and PulseAudio resample transparently, so
    the first attempt nearly always succeeds there. CoreAudio does not:
    a Bluetooth mic at 16/24 kHz, or an interface pinned to 48 kHz in
    Audio MIDI Setup, raises "Invalid sample rate" for a 44.1 kHz
    request. Callers must use the returned rate for all frequency math.

    Returns (stream, rate). Raises the *original* exception when the
    fallback rate is unavailable or fails too.
    """
    cls = sd.InputStream if kind == "input" else sd.OutputStream
    try:
        stream = cls(samplerate=preferred_rate, device=device, **kwargs)
        _log_open(kind, device, int(preferred_rate), stream)
        return stream, int(preferred_rate)
    except Exception as first_err:
        fallback = _device_default_rate(sd, device, kind)
        if not fallback or fallback == int(preferred_rate):
            raise
        try:
            stream = cls(samplerate=fallback, device=device, **kwargs)
        except Exception:
            raise first_err
        _log.warning(
            "%s device %r refused %d Hz (%s); opened at %d Hz instead",
            kind, device if device is not None else "default",
            int(preferred_rate), first_err, fallback)
        _log_open(kind, device, fallback, stream)
        return stream, fallback


def _log_open(kind, device, rate, stream):
    """One line per stream open with the driver's *reported* latency.

    That figure is the host API's own buffering estimate and stops at the
    driver: a Bluetooth link, its codec and the headset's DSP are invisible
    to it. Help > Test Audio Latency... measures the real round trip.
    Logged at WARNING because the app's root logger records nothing
    lower, and this is the line a field report needs.
    """
    try:
        lat_ms = float(stream.latency) * 1000.0
    except Exception:
        lat_ms = float("nan")
    _log.warning("%s stream open: device %r, %d Hz, reported latency %.0f ms",
                 kind, device if device is not None else "default", rate, lat_ms)


def open_input_stream(sd, device, preferred_rate, **kwargs):
    """sd.InputStream(...) with sample-rate fallback. Returns (stream, rate)."""
    return _open_with_fallback(sd, "input", device, preferred_rate, **kwargs)


def open_output_stream(sd, device, preferred_rate, **kwargs):
    """sd.OutputStream(...) with sample-rate fallback. Returns (stream, rate)."""
    return _open_with_fallback(sd, "output", device, preferred_rate, **kwargs)
