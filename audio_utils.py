"""
Shared audio utilities for Stohrer Sax Shop Companion.

Contains the AudioRingBuffer class used by both tuner_engine.py and
toner_engine.py. Pure math/threading — no tkinter or sounddevice dependency.

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
        return stream, fallback


def open_input_stream(sd, device, preferred_rate, **kwargs):
    """sd.InputStream(...) with sample-rate fallback. Returns (stream, rate)."""
    return _open_with_fallback(sd, "input", device, preferred_rate, **kwargs)


def open_output_stream(sd, device, preferred_rate, **kwargs):
    """sd.OutputStream(...) with sample-rate fallback. Returns (stream, rate)."""
    return _open_with_fallback(sd, "output", device, preferred_rate, **kwargs)
