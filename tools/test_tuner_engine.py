"""Tuner engine gates on synthetic audio — no microphone needed.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on
any failure. Run directly or through tools/run_tests.py.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from audio_utils import hann_peak_freq  # noqa: E402
from tuner.engine import (  # noqa: E402
    AUDIO_AVAILABLE, FFT_SIZE, MIN_OCTAVE, SAMPLE_RATE, TunerEngine,
)

passed = 0
failed = 0


def test(name, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


def make_tone_h2(freq, duration=0.2):
    """Sine plus a -6 dB 2nd harmonic, the way a real note leaks."""
    t = np.arange(int(SAMPLE_RATE * duration)) / SAMPLE_RATE
    s = 0.5 * np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
    return s.astype(np.float32)


# ============================================
# PREREQUISITES
# ============================================
print("\n--- Prerequisites ---")
test("numpy available", np is not None)
try:
    import sounddevice as _sd_probe  # noqa: F401
    _sd_present = True
except Exception:  # noqa: BLE001
    _sd_present = False
test("AUDIO_AVAILABLE matches whether sounddevice is installed", AUDIO_AVAILABLE == _sd_present)


# ============================================
# PITCH READING ACCURACY (2026-10-06)
# ============================================
# A parabola through three linear magnitudes is the wrong shape for a Hann
# peak: with 10.77 Hz bins the ~0.05-bin error is 0.54 Hz, which is 17 c at
# A1 and 8 c at A2. Before the fix an exactly-in-tune A1-A6 sweep read up to
# 15.3 c off (B1), so the strobe turned on a note that was dead on. Peak
# frequency now comes from the Hann closed form (audio_utils.hann_peak_freq).
print("\n--- Pitch reading accuracy ---")

# The estimator itself, on a pure Hann lobe at known sub-bin offsets.
_w = np.hanning(FFT_SIZE)
_t = np.arange(FFT_SIZE) / SAMPLE_RATE
_bin = SAMPLE_RATE / FFT_SIZE
worst_bin = 0.0
for d_true in (-0.45, -0.3, -0.1, 0.0, 0.1, 0.25, 0.4, 0.5):
    k0 = 40
    f = (k0 + d_true) * _bin
    mags = np.abs(np.fft.rfft(np.sin(2 * np.pi * f * _t) * _w))
    got = hann_peak_freq(mags, k0, _bin) / _bin - k0
    worst_bin = max(worst_bin, abs(got - d_true))
test(f"Hann estimator on a pure Hann lobe within 0.01 bin (worst {worst_bin:.4f} bin)",
     worst_bin < 0.01)

# A note that decays during the frame broadens its lobe on both sides. The
# one-neighbour form read a 20 ms decay on bin 40 as +0.105 bin (4.5 c at
# A4, 18 c at A2); the two-neighbour form reads 0.000 (2026-10-06).
worst_decay = 0.0
for tau_s in (0.1, 0.05, 0.02):
    env = np.exp(-_t / tau_s)
    for d_true in (-0.01, 0.0, 0.01):
        f = (40 + d_true) * _bin
        mags = np.abs(np.fft.rfft(np.sin(2 * np.pi * f * _t) * env * _w))
        got = hann_peak_freq(mags, 40, _bin) / _bin - 40
        worst_decay = max(worst_decay, abs(got - d_true))
test(f"Hann estimator on a decaying note (tau 100/50/20 ms) within 0.01 bin (worst {worst_decay:.4f} bin)",
     worst_decay < 0.01)

# Every semitone A1-A6 at 440-tuning, exactly in tune, through the engine.
# Pure sine first: this is the estimator alone (old code: 15.3 c worst).
def _sweep(lo_midi, hi_midi, make):
    worst_c, worst_at = 0.0, ""
    for midi in range(lo_midi, hi_midi + 1):
        f = 440.0 * 2 ** ((midi - 69) / 12)
        r = TunerEngine().analyze_buffer(make(f))
        err = r.cents_errors[midi % 12]
        if abs(err) > abs(worst_c):
            worst_c, worst_at = err, f"midi {midi} ({f:.2f} Hz)"
    return worst_c, worst_at


def make_sine(freq, duration=0.2):
    t = np.arange(int(SAMPLE_RATE * duration)) / SAMPLE_RATE
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


worst_c, worst_at = _sweep(33, 93, make_sine)          # A1 .. A6
test(f"In-tune A1-A6, pure sine: every note within 0.5 c (worst {worst_c:+.3f} c at {worst_at})",
     abs(worst_c) < 0.5)

# With a -6 dB second harmonic the bottom four notes read up to 0.72 c
# (A1): at 55 Hz the harmonic sits only 5 bins up and its Hann sidelobe
# lands on the fundamental's neighbour bins. From C2 up it is under 0.3 c.
# Both numbers measured 2026-10-06; the old parabola read 15.3 c here.
worst_c, worst_at = _sweep(33, 93, make_tone_h2)
test(f"In-tune A1-A6 with -6 dB H2: every note within 1.0 c (worst {worst_c:+.3f} c at {worst_at})",
     abs(worst_c) < 1.0)
worst_c, worst_at = _sweep(36, 93, make_tone_h2)       # C2 .. A6
test(f"In-tune C2-A6 with -6 dB H2: every note within 0.5 c (worst {worst_c:+.3f} c at {worst_at})",
     abs(worst_c) < 0.5)

# Off-pitch notes read the right offset.
OFFSETS = [-20, -10, -5, -2, 0, 2, 5, 10, 20]
worst, worst_at = 0.0, ""
for label, f in [("A2", 110.0), ("A3", 220.0), ("A4", 440.0), ("A5", 880.0)]:
    for off in OFFSETS:
        r = TunerEngine().analyze_buffer(make_tone_h2(f * 2 ** (off / 1200)))
        err = abs(r.cents_errors[9] - off)
        if err > worst:
            worst, worst_at = err, f"{label} {off:+d} c"
test(f"A2-A5 at -20..+20 c: cents_errors within 0.15 c (worst {worst:.3f} c, {worst_at})",
     worst < 0.15)

# The strobe itself: over one 0.1 s frame an in-tune note's wheel and ring
# must not turn by more than 0.15 c worth of drift.
worst_deg, worst_at = 0.0, ""
eng = None
for label, f, octave in [("A2", 110.0, 2), ("A3", 220.0, 3), ("A4", 440.0, 4), ("A5", 880.0, 5)]:
    eng = TunerEngine()
    eng._last_time = time.perf_counter() - 1.0   # dt clamps to 0.1 s
    r = eng.analyze_buffer(make_tone_h2(f))
    for what, ph in [("wheel", r.phase_offsets[9]),
                     ("ring", r.ring_phase_offsets[9][octave - MIN_OCTAVE])]:
        turn = abs((ph + 180.0) % 360.0 - 180.0)
        if turn > worst_deg:
            worst_deg, worst_at = turn, f"{label} {what}"
limit_deg = 0.15 * eng._drift_rates[9] * 0.1
test(f"In-tune A2-A5: strobe turns < {limit_deg:.3f} deg per 0.1 s (worst {worst_deg:.4f}, {worst_at})",
     worst_deg < limit_deg)

# A high note well off pitch peaks outside the 3 bins round the reference
# bin (B5 26 c flat: peak at bin 90, window 91-93). The estimator climbs to
# the lobe's top instead of stopping half a bin short.
f_b5 = 440.0 * 2 ** ((83 - 69) / 12)
r = TunerEngine().analyze_buffer(make_tone_h2(f_b5 * 2 ** (-26.3 / 1200)))
test(f"B5 26.3 c flat reads -26.3 c (got {r.cents_errors[11]:+.3f})",
     abs(r.cents_errors[11] + 26.3) < 0.15)


# ============================================
# IMPORTS ARE SEPARATE (2026-10-06)
# ============================================
# One combined try used to set np = None whenever sounddevice was missing,
# so a machine without PortAudio lost the analysis math too. Import the
# module in a child interpreter with sounddevice blocked and check that
# numpy is still bound and the flag is honest.
print("\n--- numpy survives a missing sounddevice ---")
import subprocess  # noqa: E402
_probe = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.modules['sounddevice'] = None\n"
     "sys.path.insert(0, %r)\n"
     "import tuner.engine as e\n"
     "print(e.np is not None, e.sd is None, e.AUDIO_AVAILABLE)\n"
     "import numpy as np\n"
     "r = e.TunerEngine().analyze_buffer((0.5 * np.sin(2 * np.pi * 440 * np.arange(8192) / 44100)).astype(np.float32))\n"
     "print(r.active[9])" % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))],
    capture_output=True, text=True)
_lines = _probe.stdout.split()
test(f"with sounddevice blocked: np bound, sd None, AUDIO_AVAILABLE False ({_probe.stdout.strip() or _probe.stderr.strip()[-120:]})",
     _probe.returncode == 0 and _lines[:3] == ["True", "True", "False"])
test("with sounddevice blocked: analyze_buffer still lights the A wheel",
     _probe.returncode == 0 and len(_lines) > 3 and _lines[3] == "True")


# ============================================
# SYNTHETIC SOURCE (2026-10-06)
# ============================================
# TunerEngine.synthetic_hz lets the tab run with no microphone: start()
# opens no stream, analyze() feeds the tone itself.
print("\n--- Synthetic source ---")
eng = TunerEngine()
eng.synthetic_hz = 440.0
ok, err = eng.start(device=None)
test(f"start() succeeds with no device ({err})", ok and err is None)
test("start() opened no stream", eng._stream is None and eng.is_running)
test("silent_seconds() is 0 with no stream (no 'no signal' warning)", eng.silent_seconds() == 0.0)
r = None
for _ in range(8):           # 8 x 1024 samples > one FFT frame
    r = eng.analyze()
test(f"analyze() fed {eng._synth_pos} samples (phase-continuous counter advances)", eng._synth_pos == 8 * 1024)
test("analyze() through the live path lights A", r.active[9] and r.magnitudes[9] > 0.9)
test(f"analyze() through the live path reads A within 0.2 c ({r.cents_errors[9]:+.3f})", abs(r.cents_errors[9]) < 0.2)
test("no stream error", eng.last_error is None)
eng.stop()
test("stop() clears running", not eng.is_running)
eng2 = TunerEngine()
test("synthetic_hz defaults to None (never set in normal use)", eng2.synthetic_hz is None)


# ============================================
# RESULT STRUCTURE / BASICS
# ============================================
print("\n--- Basics ---")
r = TunerEngine().analyze_buffer(make_tone_h2(440.0))
test("A4 lights the A wheel", r.active[9] and r.magnitudes[9] > 0.9)
test("A4 leaves non-adjacent wheels dark",
     max(r.magnitudes[i] for i in range(12) if i not in (8, 9, 10)) < 0.05)
test("A4's brightest ring is octave 4",
     int(np.argmax(r.ring_magnitudes[9])) == 4 - MIN_OCTAVE)
r0 = TunerEngine().analyze_buffer(np.zeros(FFT_SIZE, dtype=np.float32))
test("silence lights nothing", not any(r0.active) and max(r0.magnitudes) == 0.0)
test("math.log2 on cents is finite for every wheel", all(math.isfinite(c) for c in r.cents_errors))


# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
