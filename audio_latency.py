"""End-to-end audio latency test (Help > Test Audio Latency...).

Plays a few short chirps out of the speakers and listens for them on the
microphone, then reports the round-trip delay: output buffering, DAC,
air, mic, ADC, input buffering. This is the number the audio API cannot
tell us — PortAudio's reported stream latency only covers the host
driver's own buffers, and a Bluetooth headset's radio link, codec and
speech DSP live entirely beyond that, which is exactly where the lag
that makes the strobe wheels feel late comes from.

Both streams are opened as one full-duplex stream (sd.playrec), so the
played and recorded sample clocks share an origin and the lag between
"chirp written at output sample i" and "chirp detected at input sample
j" is the round trip in samples. Uses sounddevice's default latency
setting, the same the engines run with, so the result reflects what the
app actually experiences.

Pure numpy + sounddevice, no tkinter. The caller must stop the running
engine first: macOS may refuse a second open of the same input device.
"""

import logging
import time

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - the app degrades without audio
    sd = None

_log = logging.getLogger(__name__)

# Test signal layout.
CHIRP_S = 0.03          # each chirp lasts 30 ms
CHIRP_F0, CHIRP_F1 = 500.0, 3000.0   # inside the Bluetooth HFP passband
CHIRP_TIMES_S = (0.4, 1.1, 1.8)      # emit times, spaced wider than SEARCH_S
TOTAL_S = 2.5           # record window; last chirp + 0.7 s for the echo
SEARCH_S = 0.6          # look for each chirp this long after emission;
                        # must stay under the chirp spacing or a window
                        # can pick up the *next* chirp
CHIRP_LEVEL = 0.5
# A chirp counts as detected when its correlation peak is this many times
# the median correlation magnitude in the search window.
DETECT_RATIO = 8.0

# Detected chirps must agree with the median within this many ms for the
# result to count; a laptop mic with echo cancellation eating the chirps
# leaves stray correlation peaks that would otherwise pass as a reading.
AGREE_MS = 15.0

# Interpretation thresholds for the UI, round trip in milliseconds.
TIGHT_MS = 80
OK_MS = 150


class LatencyResult:
    """Outcome of one measurement. ``ok`` False means not detected."""

    def __init__(self):
        self.ok = False
        self.message = ""
        self.round_trip_ms = None
        self.per_chirp_ms = []
        self.reported_input_ms = None
        self.reported_output_ms = None
        self.sample_rate = None
        self.input_name = ""
        self.output_name = ""

    def verdict(self):
        """Short human reading of the round-trip figure."""
        if not self.ok:
            return "Not measured"
        ms = self.round_trip_ms
        if ms < TIGHT_MS:
            return "Tight. Wired-class latency; the strobe reacts as you play."
        if ms < OK_MS:
            return "Acceptable. Noticeable but workable for tuning."
        return ("Laggy. The strobe wheels and the drone analysis react late. "
                "This is typical of Bluetooth audio; a wired mic and speakers "
                "or the built-in ones will respond faster.")


def _chirp(sr):
    n = int(CHIRP_S * sr)
    t = np.arange(n) / sr
    # Linear chirp with a Hann envelope so it has no clicks of its own.
    k = (CHIRP_F1 - CHIRP_F0) / CHIRP_S
    phase = 2 * np.pi * (CHIRP_F0 * t + 0.5 * k * t * t)
    return (np.sin(phase) * np.hanning(n)).astype(np.float32)


def _noop_callback(indata, outdata, frames, time_info, status):
    outdata.fill(0)


def _device_name(device, kind):
    try:
        return sd.query_devices(device, kind)["name"]
    except Exception:
        return "system default"


def _matching_output(input_device):
    """Default output device on the same host API as ``input_device``.

    A full-duplex stream needs both ends on one host API; Windows has
    several (MME, WASAPI, WDM-KS) and a mic picked from one of them
    against the MME default speakers fails with "Illegal combination of
    I/O devices". None means the system default output.
    """
    if input_device is None:
        return None
    try:
        hostapi = sd.query_devices(input_device, "input")["hostapi"]
        out = sd.query_hostapis(hostapi)["default_output_device"]
        return out if out is not None and out >= 0 else None
    except Exception:
        return None


def _candidate_rates(input_device, output_device):
    rates = [44100]
    for dev, kind in ((input_device, "input"), (output_device, "output")):
        try:
            r = int(round(sd.query_devices(dev, kind)["default_samplerate"]))
            if r not in rates:
                rates.append(r)
        except Exception:
            pass
    if 48000 not in rates:
        rates.append(48000)
    return rates


def measure(input_device=None, output_device=None):
    """Run the loopback test. Blocks for about TOTAL_S seconds plus open
    time; call from a worker thread. Returns a LatencyResult."""
    res = LatencyResult()
    if sd is None:
        res.message = "sounddevice is not installed."
        return res

    if output_device is None:
        output_device = _matching_output(input_device)
    res.input_name = _device_name(input_device, "input")
    res.output_name = _device_name(output_device, "output")

    recorded = None
    last_err = None
    for sr in _candidate_rates(input_device, output_device):
        try:
            signal = np.zeros(int(TOTAL_S * sr), dtype=np.float32)
            chirp = _chirp(sr)
            for t0 in CHIRP_TIMES_S:
                i = int(t0 * sr)
                signal[i:i + len(chirp)] += CHIRP_LEVEL * chirp
            # Full-duplex: one stream, one clock for both directions.
            stream_kwargs = dict(samplerate=sr, channels=1, dtype="float32",
                                 device=(input_device, output_device))
            # Read the driver's own latency claim from a stream of the
            # same shape first (this also validates the rate cheaply).
            # (A callback is required: WDM-KS rejects blocking streams.)
            with sd.Stream(callback=_noop_callback, **stream_kwargs) as probe:
                lat_in, lat_out = probe.latency
            res.reported_input_ms = lat_in * 1000.0
            res.reported_output_ms = lat_out * 1000.0
            recorded = sd.playrec(signal, blocking=True, **stream_kwargs)
            res.sample_rate = sr
            break
        except Exception as e:
            last_err = e
            recorded = None
    if recorded is None:
        res.message = f"Could not open a full-duplex stream: {last_err}"
        _log.warning("Latency test: %s", res.message)
        return res

    rec = recorded[:, 0].astype(np.float64)
    sr = res.sample_rate
    chirp = _chirp(sr).astype(np.float64)
    lags = []
    for t0 in CHIRP_TIMES_S:
        start = int(t0 * sr)
        end = min(len(rec), start + int(SEARCH_S * sr))
        window = rec[start:end]
        if len(window) <= len(chirp):
            continue
        # Cross-correlate the recording window against the chirp; the
        # peak's offset is the delay from emission to arrival.
        corr = np.correlate(window, chirp, mode="valid")
        mag = np.abs(corr)
        peak = int(np.argmax(mag))
        floor = float(np.median(mag)) + 1e-12
        if mag[peak] / floor >= DETECT_RATIO:
            lags.append(peak / sr * 1000.0)
    res.per_chirp_ms = lags

    if len(lags) >= 2:
        median = float(np.median(lags))
        agreeing = [x for x in lags if abs(x - median) <= AGREE_MS]
        if len(agreeing) < 2:
            _log.warning("Latency test: chirp readings disagree %s ms; not measured",
                         [round(x) for x in lags])
            lags = []
    if len(lags) < 2:
        res.message = (
            "Couldn't hear the test tone on the microphone. Use speakers "
            "rather than headphones, turn the volume up, and keep the room "
            "quiet for a few seconds. Some laptop microphones cancel their "
            "own speaker output (echo cancellation), which hides the tone; "
            "an external mic or external speakers get around that.")
        _log.warning("Latency test: chirps detected %d/%d at %d Hz (in %r, out %r)",
                     len(res.per_chirp_ms), len(CHIRP_TIMES_S), sr,
                     res.input_name, res.output_name)
        return res

    res.round_trip_ms = float(np.median(lags))
    res.ok = True
    res.message = "OK"
    _log.warning(
        "Latency test: round trip %.0f ms (chirps %s) at %d Hz; reported "
        "in %s ms / out %s ms; in %r, out %r",
        res.round_trip_ms, [round(x) for x in lags], sr,
        None if res.reported_input_ms is None else round(res.reported_input_ms),
        None if res.reported_output_ms is None else round(res.reported_output_ms),
        res.input_name, res.output_name)
    return res


if __name__ == "__main__":  # manual check: python audio_latency.py
    logging.basicConfig(level=logging.WARNING)
    t = time.perf_counter()
    r = measure()
    print(f"ok={r.ok} round_trip={r.round_trip_ms} per_chirp={r.per_chirp_ms} "
          f"rate={r.sample_rate} reported_in={r.reported_input_ms} "
          f"reported_out={r.reported_output_ms} in={r.input_name!r} "
          f"out={r.output_name!r} msg={r.message!r} took={time.perf_counter()-t:.1f}s")
    print(r.verdict())
