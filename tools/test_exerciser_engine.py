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
# DRONE CANCELLATION NOTCH (2026-10-06, measured first)
# ============================================
# _cancel_drone zeroes +-4 Hz round every partial of the drone before YIN.
# Measured with phase-continuous signals: with headphones (no bleed) the
# notch biases a unison by about +1 c; with speakers (the rich drone at
# -10 dB in the mic) a just third reads -12 c and a fifth -5.5 c, and the
# drone alone still registers as a unison (the notch cannot remove its
# leakage). Wider or Hann-windowed notches were measured and rejected:
# they bias the headphones unison by 30-80 c. No notch loses the third
# under bleed entirely. The UI's "Headphones recommended" is the honest
# answer; these gates pin the contract as measured.
print("\n--- Drone cancellation notch ---")


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
e.running = True
e.set_drone(on=True, freq=130.81, voicing="root", dtype="rich", volume=0.3)
worst = 0.0
for off in (0.0, 2.5, 10.0, 30.0):
    feed(e, player_blocks(130.81 * 2 ** (off / 1200)))
    f, c = e.get_pitch()
    worst = max(worst, abs(cents(f, 130.81) - off))
test(f"headphones: drone on, unison practice at 0-30 c reads within 2 c (worst bias {worst:.2f} c)", worst < 2.0)
d = drone_blocks(e)
feed(e, [b * 0.3 for b in d])
f, c = e.get_pitch()
print(f"        info: speakers, player silent: the drone itself reads {f:.1f} Hz conf {c:.2f} (notch leakage; headphones recommended)")
errs = {}
for name, off in (("M3", 386.31), ("P5", 701.96)):
    feed(e, [p + b * 0.3 for p, b in zip(player_blocks(130.81 * 2 ** (off / 1200)), d)])
    f, c = e.get_pitch()
    errs[name] = None if f is None else cents(f, 130.81) - off
test(f"speakers: just third and fifth over the bleeding drone read within 15 c "
     f"(M3 {errs['M3']:+.1f} c, P5 {errs['P5']:+.1f} c)",
     all(v is not None and abs(v) < 15.0 for v in errs.values()))
e.set_drone(on=False)
feed(e, player_blocks(130.81 * 2 ** (2.5 / 1200)))
f, c = e.get_pitch()
test(f"drone off: no notch, the same note reads {cents(f, 130.81):+.2f} c (within 0.3 of 2.5)",
     abs(cents(f, 130.81) - 2.5) < 0.3)


# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
