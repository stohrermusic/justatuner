"""Drone-tab engine math on synthetic audio — no microphone, no display.

YIN accuracy over the instrument range at 44.1 kHz and at a 16 kHz
(Bluetooth) input rate, the just-intonation interval math, note naming and
transposition, instrument presets and voicings, the live get_pitch() path
on the synthetic source, and the drone-cancellation notch measured in the
two ways it is used: headphones (no bleed) and speakers (drone in the mic).
Standalone script, PASS/FAIL per check, exit 1 on any failure.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-exengine-test-")

import numpy as np  # noqa: E402

from audio_utils import synthetic_tone  # noqa: E402
from exerciser.engine import AudioEngine, INPUT_BLOCK, INSTRUMENT_PRESETS  # noqa: E402
from exerciser.intervals import (  # noqa: E402
    JI_INTERVALS, NOTE_NAMES, analyze_interval, freq_to_note_name, note_freq,
    transpose_note_name,
)
from exerciser.pitch import moving_median_filter, yin_detect  # noqa: E402

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


def cents(f, ref):
    return 1200.0 * math.log2(f / ref)


def tone(f, sr, n=INPUT_BLOCK * 2, pos=0):
    """The engine's synthetic voice: fundamental, -6 and -12 dB harmonics."""
    return synthetic_tone(pos, n, f, sr, harmonics_db=(0.0, -6.0, -12.0)).astype(np.float64)


# ============================================
# YIN ACCURACY (2026-10-06, measured first)
# ============================================
print("\n--- YIN on the instrument range ---")


def sweep(sr, lo_midi, hi_midi):
    worst, worst_at, misses = 0.0, "", []
    for midi in range(lo_midi, hi_midi + 1):
        f = 440.0 * 2 ** ((midi - 69) / 12)
        got, conf = yin_detect(tone(f, sr), sr, fmin=65, fmax=2500, threshold=0.25)
        if got is None or conf < 0.2:
            misses.append(round(f, 1))
            continue
        c = abs(cents(got, f))
        if c > worst:
            worst, worst_at = c, f"{f:.1f} Hz"
    return worst, worst_at, misses


w, at, miss = sweep(44100, 36, 84)        # C2 .. C6
test(f"44.1 kHz C2-C6: every note within 1 c, none missed (worst {w:.2f} c at {at}, misses {miss})",
     w < 1.0 and not miss)
w, at, miss = sweep(44100, 36, 96)        # C2 .. C7
test(f"44.1 kHz C2-C7: every note within 3 c (worst {w:.2f} c at {at}; tau is ~21 samples at C7)",
     w < 3.0 and not miss)
# A Bluetooth hands-free mic delivers 16 kHz (the MIC lamp says "low
# quality input"): coarser lag resolution, and C2 (65.4 Hz) is at the
# fmin edge of the 8192-sample buffer. Measured: worst 4.1 c, C2 missed.
w, at, miss = sweep(16000, 38, 84)        # D2 .. C6
test(f"16 kHz D2-C6: every note within 6 c, none missed (worst {w:.2f} c at {at}, misses {miss})",
     w < 6.0 and not miss)
_, _, miss16 = sweep(16000, 36, 37)
print(f"        info: 16 kHz C2/C#2 misses {miss16} (fmin edge of the buffer; reported, not gated)")

test("silence: no pitch, confidence 0",
     yin_detect(np.zeros(INPUT_BLOCK * 2), 44100) == (None, 0.0))
rng = np.random.default_rng(3)
noise = rng.normal(0, 0.1, INPUT_BLOCK * 2)
f_n, c_n = yin_detect(noise, 44100, fmin=65, fmax=2500, threshold=0.25)
test(f"white noise: not confident (freq {f_n}, conf {c_n:.2f})", f_n is None or c_n < 0.2)
test("moving_median_filter: median of the last 5, last value when short",
     moving_median_filter([1, 100, 2, 3, 50], 5) == 3.0 and moving_median_filter([7, 9], 5) == 9
     and moving_median_filter([], 5) is None)


# ============================================
# JUST INTONATION MATH
# ============================================
print("\n--- Interval math ---")
root = 130.81
# The ratio is normalised into [1, 2) with the octave count reported
# separately, so the "Octave" entry can only be reached from below (a flat
# octave) and 2:1 itself reads as Unison, octave_shift 1 -- by design.
within = [iv for iv in JI_INTERVALS if iv["name"] != "Octave"]
ok = True
for iv in within:
    r = analyze_interval(root * iv["ratio"][0] / iv["ratio"][1], root)
    if r["interval"]["name"] != iv["name"] or abs(r["cents_off"]) > 1e-6:
        ok = False
        print(f"        {iv['name']}: read {r['interval']['name']} {r['cents_off']:+.3f} c")
test("every JI ratio within the octave, at exactly its ratio, names itself at 0.000 c", ok)
r = analyze_interval(root * 2, root)
test("exactly 2:1 reads Unison with octave_shift 1 (the octave is normalised away)",
     r["interval"]["name"] == "Unison" and r["octave_shift"] == 1 and abs(r["cents_off"]) < 1e-9)

# ET semitones land on the nearest JI interval with the catalogued ET difference.
et_ok = True
for iv in within:
    r = analyze_interval(root * 2 ** (iv["semitones"] / 12), root)
    if r["interval"]["name"] != iv["name"] or abs(r["cents_off"] + iv["et_diff"]) > 1e-6:
        et_ok = False
test("every ET semitone within the octave names the matching JI interval, off by exactly -et_diff", et_ok)
m3 = next(iv for iv in JI_INTERVALS if iv["short"] == "M3")
test(f"JI major third is {m3['et_diff']:.1f} c from ET (-13.7)", abs(m3["et_diff"] + 13.686) < 0.01)
r = analyze_interval(root * 5 / 4 / 2, root)
test("a third played an octave below the root: octave_shift -1, still Major 3rd",
     r["octave_shift"] == -1 and r["interval"]["name"] == "Major 3rd")
r = analyze_interval(root * 4.0, root)
test("two octaves up: octave_shift 2, Unison at 0 c",
     r["octave_shift"] == 2 and r["interval"]["name"] == "Unison" and abs(r["cents_off"]) < 1e-6)
r = analyze_interval(root * 2 ** (1195 / 1200), root)
test(f"1195 c (a flat octave) reads -5 c from Unison, not Major 7th (got {r['interval']['name']} {r['cents_off']:+.1f})",
     r["interval"]["name"] == "Unison" and abs(r["cents_off"] + 5) < 0.01)
test("non-positive frequencies return None", analyze_interval(0, root) is None and analyze_interval(440, -1) is None)

rt = all(freq_to_note_name(note_freq(i, o)) == (NOTE_NAMES[i], o)
         for o in range(1, 8) for i in range(12))
test("note_freq -> freq_to_note_name round-trips every note C1-B7", rt)
test("note_freq(9, 4) is A4 = 440.0", abs(note_freq(9, 4) - 440.0) < 1e-9)
test("freq_to_note_name(0) is ('?', 0)", freq_to_note_name(0) == ("?", 0))
test("transposition: concert C is written D on Bb, A on Eb, G on F, C on concert",
     [transpose_note_name(0, k) for k in ("Bb", "Eb", "F", "Concert (C)")] == [2, 9, 7, 0])


# ============================================
# ENGINE STATE
# ============================================
print("\n--- Engine state ---")
e = AudioEngine()
test("default drone C4 rich root, off", e.drone_freq == 261.63 and e.drone_type == "rich" and not e.drone_on)
counts = {}
for voicing in ("root", "fifth", "major", "minor"):
    e.set_drone(voicing=voicing, dtype="rich")
    counts[voicing] = len(e._osc_freqs)
test(f"rich voicings: 8 partials per voice, fundamental plus harmonics 2-8 ({counts})",
     counts == {"root": 8, "fifth": 16, "major": 24, "minor": 24})
e.set_drone(voicing="major", dtype="sine")
test("sine major: three voices at 1, 5/4, 3/2 of the root",
     [round(f / e.drone_freq, 4) for f, _ in e._osc_freqs] == [1.0, 1.25, 1.5])
e.set_drone(voicing="minor")
test("sine minor: 6/5 third", abs(e._osc_freqs[1][0] / e.drone_freq - 1.2) < 1e-9)
from exerciser.engine import VOICINGS, VOICING_LABELS, VOICING_SYMBOLS  # noqa: E402
ok = True
for name, ratios in VOICINGS.items():
    e.set_drone(voicing=name, dtype="sine")
    got = [round(f / e.drone_freq, 6) for f, _ in e._osc_freqs]
    want = [round(r, 6) for r, _ in ratios]
    if got != want or ratios[0][0] != 1 or any(not (1 <= r < 2) for r, _ in ratios):
        ok = False
        print(f"        {name}: {got} vs {want}")
test(f"every voicing is its just ratios within the octave, root first ({len(VOICINGS)} voicings)", ok)
test("every voicing has a menu label and a chord symbol",
     set(VOICINGS) == set(VOICING_LABELS) == set(VOICING_SYMBOLS))
test("dom7 carries the harmonic seventh 7:4, min7 the just minor seventh 9:5",
     VOICINGS["dom7"][3][0] == 7 / 4 and VOICINGS["min7"][3][0] == 9 / 5)
e.set_drone(on=True, volume=0.5)
test("set_drone(on) targets the volume; off targets 0",
     e._target_amp == 0.5 and (e.set_drone(on=False) or e._target_amp == 0.0))
e.set_instrument("Bari Sax")
test("instrument preset applies fmin/fmax/thresholds",
     (e._fmin, e._fmax, e._yin_threshold, e._conf_threshold) == INSTRUMENT_PRESETS["Bari Sax"][:4])
test("unknown preset leaves the settings alone",
     e.set_instrument("Kazoo") is None and e._fmin == INSTRUMENT_PRESETS["Bari Sax"][0])
e.set_instrument("Auto")
test("input_open() is False with no stream and no synthetic source", not e.input_open())


# ============================================
# LIVE get_pitch() PATH ON THE SYNTHETIC SOURCE
# ============================================
print("\n--- get_pitch on the synthetic source ---")
e = AudioEngine()
e.synthetic_hz = 196.0
e._start_input_stream = lambda: None   # never a real device in a test
e._start_output_stream = lambda: None  # nor a real output: get_pitch() checks its health too
e.running = True                       # start() needs sounddevice; the path under test does not
for _ in range(6):
    f, c = e.get_pitch()
test(f"synthetic 196 Hz reads within 0.5 c through get_pitch ({cents(f, 196.0):+.3f} c, conf {c:.2f})",
     f is not None and abs(cents(f, 196.0)) < 0.5 and c > 0.9)
test("input_open() is True on the synthetic source; no input error", e.input_open() and e.input_error is None)
test(f"synthetic counter advanced {e._synth_pos // INPUT_BLOCK} blocks", e._synth_pos == 6 * INPUT_BLOCK)
e.synthetic_hz = None
for _ in range(e._hold_frames):
    f, _ = e.get_pitch()               # no new audio: buffer not ready, pitch held
test("the last pitch is held for the hold frames", f is not None)
# Feed silence so the detector runs and misses, past the hold.
for _ in range(e._hold_frames + 2):
    e._push_input(np.zeros(INPUT_BLOCK, dtype=np.float32))
    f, c = e.get_pitch()
test("after the hold frames of silence the pitch clears", f is None and c == 0.0)
e.running = False


# ============================================
# MONITORING MODES (2026-10-07)
# ============================================
# Speakers mode (listen to the room, subtract the drone's partials) is gated
# in tools/test_drone_cancel.py. Here: headphones mode does nothing to the
# signal, and the sample drone keeps the old +-4 Hz spectral notch, whose
# leakage is documented rather than gated (headphones are the answer there).
print("\n--- Monitoring modes ---")


def feed(e, blocks):
    for b in blocks:
        e._push_input(b.astype(np.float32))
    e.pitch_history.clear()
    e.latest_pitch = None
    e._miss_count = 0


def player_blocks(f, n=2):
    return [tone(f, 44100, INPUT_BLOCK, pos=b * INPUT_BLOCK) for b in range(n)]


def drone_blocks(e, n=2):
    out = np.zeros((INPUT_BLOCK, 1), dtype=np.float32)
    kept = []
    for i in range(60):
        e._output_callback(out, INPUT_BLOCK, None, None)
        if i >= 60 - n:
            kept.append(out[:, 0].astype(np.float64).copy())
    peak = max(np.max(np.abs(b)) for b in kept) or 1.0
    return [b / peak for b in kept]


e = AudioEngine()
e._start_input_stream = lambda: None   # never a real device in a test
e._start_output_stream = lambda: None  # nor a real output: get_pitch() checks its health too
e.monitoring = "headphones"
e.running = True
e.set_drone(on=True, freq=130.81, voicing="root", dtype="rich", volume=0.3)
test("headphones: no listen, bleed status off", e.bleed_status() == "off")
worst = 0.0
for off in (0.0, 2.5, 10.0, 30.0):
    feed(e, player_blocks(130.81 * 2 ** (off / 1200)))
    f, c = e.get_pitch()
    worst = max(worst, abs(cents(f, 130.81) - off))
test(f"headphones: drone on, unison practice at 0-30 c reads within 0.3 c (worst {worst:.2f} c)", worst < 0.3)
d = drone_blocks(e)
feed(e, [b * 0.3 for b in d])
f, c = e.get_pitch()
print(f"        info: headphones mode but speakers in use: the drone reads {f:.1f} Hz conf {c:.2f} (the user's choice)")

# The sample drone is not a known set of partials: the notch stays for it.
e.monitoring = "speakers"
e._drone_sample = np.sin(2 * np.pi * 220 * np.arange(44100) / 44100).astype(np.float32)
e._drone_sample_sr, e._drone_sample_freq, e._sample_phases = 44100, 220.0, np.zeros(1)
e.set_drone(dtype="sample")
test("sample drone in speakers mode: status off (notch path)", e.bleed_status() == "off")
x = player_blocks(130.81 * 2 ** (2.5 / 1200))[0] + d[0] * 0.3
y = e._notch_drone(x)
fn, cn = yin_detect(y, 44100, fmin=65, fmax=2500, threshold=0.25)
test(f"sample-drone notch: a unison +2.5 c over the bleed still reads a pitch ({cents(fn, 130.81):+.1f} c; leakage, documented)",
     fn is not None)


# ============================================
# WHERE THE DRONE PLAYS, AND AN OUTPUT THAT DIES
# ============================================
# 2026-11-28: the drone only ever opened "the system default", which was a USB
# microphone's own headphone jack, and when that device was unplugged the
# output was never reopened (the mic has had a health check since v1.1.3).
# The sound library here is a stand-in: no real device is opened.
print("\n--- the output device: chosen, refused, absent, dead ---")
import time  # noqa: E402

import exerciser.engine as eng_mod  # noqa: E402


class FakeOut:
    def __init__(self, device):
        self.device, self.latency = device, 0.02
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeSD:
    """sounddevice's OutputStream only; `refuse` is the set of devices that
    will not open (None in it = the system default will not open either)."""

    def __init__(self, refuse=()):
        self.refuse, self.opened = set(refuse), []

    def OutputStream(self, samplerate=None, device=None, **kw):  # noqa: N802 — sounddevice's name
        if device in self.refuse:
            raise RuntimeError(f"Error opening OutputStream: device {device} unavailable")
        st = FakeOut(device)
        self.opened.append(st)
        return st

    def devices(self):
        return [st.device for st in self.opened]


def out_engine(fake, device=None):
    eng = AudioEngine()
    eng._start_input_stream = lambda: None
    eng_mod.sd = fake
    setter = getattr(eng, "set_output_device", None)
    if setter is not None:
        setter(device)
    eng.running = True
    eng._start_output_stream()
    return eng


real_sd = eng_mod.sd
try:
    fake = FakeSD()
    e = out_engine(fake, device=7)
    test(f"a chosen output device is the one opened (opened {fake.devices()})",
         fake.devices() == [7] and fake.opened[0].started)
    test("... and nothing is wrong: no error, no note",
         getattr(e, "output_error", "?") is None and getattr(e, "output_note", "?") is None)

    fake = FakeSD(refuse={7})
    e = out_engine(fake, device=7)
    test(f"a chosen device that will not open: the drone plays on the system default (opened {fake.devices()})",
         fake.devices() == [None])
    test("... and the engine says why the chosen one is not in use",
         "unavailable" in (getattr(e, "output_note", None) or "") and getattr(e, "output_error", "?") is None)

    fake = FakeSD(refuse={None})
    e = out_engine(fake)
    test("no output at all: the reason is kept for the tab to show",
         e._output_stream is None and "unavailable" in (getattr(e, "output_error", None) or ""))
    fake.refuse.clear()                       # the device comes back
    e._last_output_attempt = time.monotonic() - 10.0
    e.get_pitch()
    test("... and the next look reopens it once the device is back",
         e._output_stream is not None and getattr(e, "output_error", "?") is None)
    n = len(fake.opened)
    e._last_output_time = time.monotonic()
    e.get_pitch()
    test("a healthy output is left alone", len(fake.opened) == n)

    # A dead output: the stream object is there, its callback has stopped.
    fake = FakeSD()
    e = out_engine(fake)
    e.set_drone(on=True, freq=130.81, voicing="root", dtype="rich", volume=0.3)
    e._bleed_state, e._bleed_gain = "ready", np.ones(8, dtype=complex)
    e._room = {130.81: (0.1, 0.0, 0.0)}
    first = fake.opened[0]
    e._last_output_time = time.monotonic() - 2.0      # no callback for 2 s
    e._last_output_attempt = time.monotonic() - 1.0   # but it was opened 1 s ago: not yet
    e.get_pitch()
    test("an output silent for 2 s is not reopened inside the 3 s pacing", len(fake.opened) == 1)
    e._last_output_attempt = time.monotonic() - 10.0
    e.get_pitch()
    test(f"an output whose callback has stopped is closed and opened again ({len(fake.opened)} opens)",
         len(fake.opened) == 2 and first.closed and e._output_stream is fake.opened[-1])
    test("... what was learned about the room is dropped, and the drone is listened to again",
         e._room == {} and e._bleed_gain is None and e.bleed_status() == "listening")

    # Picking another device while the drone tab is running.
    fake = FakeSD()
    e = out_engine(fake)
    first = fake.opened[0]
    getattr(e, "set_output_device", lambda d: None)(4)
    test(f"picking a device while running closes the old output and opens the new one ({fake.devices()})",
         fake.devices() == [None, 4] and first.closed)

    # The output callback is what proves the stream alive.
    e._last_output_time = 0.0
    e._output_callback(np.zeros((64, 1), dtype=np.float32), 64, None, None)
    test("the output callback stamps the time it ran",
         time.monotonic() - getattr(e, "_last_output_time", 0.0) < 1.0)

    # The synthetic source (tests, CI): no health check, as for the mic.
    fake = FakeSD()
    e = out_engine(fake)
    e.synthetic_hz = 196.0
    e._last_output_time = e._last_output_attempt = time.monotonic() - 10.0
    e.get_pitch()
    test("with the synthetic source the output is not health-checked", len(fake.opened) == 1)
finally:
    eng_mod.sd = real_sd

# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
