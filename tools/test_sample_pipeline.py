"""Drone sample pipeline gates on synthetic audio: WAV reader, sample install
(trim, pitch, loop crossfade), sample playback, synth output, recording and
save/load. No microphone, display or audio device: AudioEngine is built but
start() is never called; callbacks are driven directly.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on
any failure. Run directly or through tools/run_tests.py.
"""
import math
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat_sample_test_")

import numpy as np

from audio_utils import hann_peak_freq
from exerciser.engine import AudioEngine, _read_wav_file

SR = 44100
TMP = tempfile.mkdtemp(prefix="jat_sample_wavs_")
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


def cents(got, want):
    return 1200 * math.log2(got / want)


def tone_h2(freq, dur, sr=SR, amp=0.5):
    """Sine plus a -6 dB 2nd harmonic."""
    t = np.arange(int(sr * dur)) / sr
    return (amp * np.sin(2 * np.pi * freq * t) + amp / 2 * np.sin(2 * np.pi * 2 * freq * t)).astype(np.float32)


def peak_in(sig, sr, lo, hi):
    """(Hz, magnitude) of the largest Hann-windowed peak between lo and hi Hz."""
    mags = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    bin_hz = sr / len(sig)
    a, b = int(lo / bin_hz), int(hi / bin_hz) + 1
    k = a + int(np.argmax(mags[a:b]))
    return hann_peak_freq(mags, k, bin_hz), float(mags[k])


def write_wav(name, frames_bytes, sr, width, channels=1):
    path = os.path.join(TMP, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(frames_bytes)
    return path


def pcm_bytes(x, width):
    """Interleaved float signal -> little-endian PCM of the given byte width."""
    full = 2 ** (8 * width - 1) - 1
    ints = np.round(np.clip(x, -1, 1) * full).astype(np.int64)
    if width == 3:
        return b"".join(int(v).to_bytes(3, "little", signed=True) for v in ints)
    return ints.astype({2: "<i2", 4: "<i4"}[width]).tobytes()


# ============================================
# _read_wav_file
# ============================================
print("\n--- WAV reader ---")
src = (0.9 * np.sin(2 * np.pi * 440 * np.arange(SR // 2) / SR)).astype(np.float32)
for width, sr in ((2, 48000), (3, 22050), (4, 44100)):
    data, got_sr = _read_wav_file(write_wav(f"m{width}.wav", pcm_bytes(src, width), sr, width))
    err = float(np.max(np.abs(data - src)))
    test(f"{8 * width}-bit PCM mono: sr {got_sr}, len {len(data)}, dtype {data.dtype}",
         got_sr == sr and len(data) == len(src) and data.dtype == np.float32)
    # 2 LSB (0.5 rounding + up to 0.9 from the 32767-vs-32768 scale); int32 is float32-limited.
    gate = max(2 / 2 ** (8 * width - 1), 2e-7)
    test(f"{8 * width}-bit PCM mono: max abs error {err:.3g} (gate {gate:.3g})", err < gate)



def write_float_wav(name, samples, sr, channels=1, bits=32):
    """A genuine IEEE-float WAV (format tag 3): the stdlib wave module can
    neither write nor open these, so the file is assembled by hand."""
    import struct
    payload = np.asarray(samples).astype("<f4" if bits == 32 else "<f8").tobytes()
    fmt = struct.pack("<HHIIHH", 3, channels, sr, sr * channels * bits // 8, channels * bits // 8, bits)
    path = os.path.join(TMP, name)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(payload)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        f.write(b"data" + struct.pack("<I", len(payload)) + payload)
    return path


data, got_sr = _read_wav_file(write_float_wav("f32.wav", src, 44100))
err = float(np.max(np.abs(data - src)))
test(f"32-bit float WAV (format tag 3): sr {got_sr}, len {len(data)}, max abs error {err:.3g}",
     got_sr == 44100 and len(data) == len(src) and data.dtype == np.float32 and err < 1e-7)
stereo_f = np.stack([src, -0.5 * src], axis=1).reshape(-1)
data, _ = _read_wav_file(write_float_wav("f32s.wav", stereo_f, 44100, channels=2))
test(f"32-bit float stereo -> per-sample mean: max abs error {float(np.max(np.abs(data - 0.25 * src))):.3g}",
     len(data) == len(src) and float(np.max(np.abs(data - 0.25 * src))) < 1e-7)
data, got_sr = _read_wav_file(write_float_wav("f64.wav", src, 48000, bits=64))
test(f"64-bit float WAV: sr {got_sr}, max abs error {float(np.max(np.abs(data - src))):.3g}",
     got_sr == 48000 and float(np.max(np.abs(data - src))) < 1e-7)

# int32 whose first 1024 samples are silence: as float32 bits they are 0.0,
# so the probe picks float and the tone after them decodes as garbage.
lead = np.concatenate([np.zeros(4410), 0.3 * np.sin(2 * np.pi * 220 * np.arange(SR) / SR)]).astype(np.float32)
with np.errstate(invalid="ignore"):
    data, _ = _read_wav_file(write_wav("i32_lead.wav", pcm_bytes(lead, 4), SR, 4))
    err = float(np.nanmax(np.abs(data - lead)))
n_nan = int(np.isnan(data).sum())
test(f"32-bit int with 0.1 s leading silence decodes (max abs error {err:.3g}, {n_nan} NaN; gate 1e-6)",
     n_nan == 0 and err < 1e-6)

L = (0.5 * np.sin(2 * np.pi * 440 * np.arange(SR // 2) / SR)).astype(np.float32)
R = (0.3 * np.sin(2 * np.pi * 660 * np.arange(SR // 2) / SR)).astype(np.float32)
inter = np.stack([L, R], axis=1).reshape(-1)
mean = (L + R) / 2
for width in (2, 3):
    data, got_sr = _read_wav_file(write_wav(f"st{width}.wav", pcm_bytes(inter, width), SR, width, channels=2))
    err = float(np.max(np.abs(data - mean)))
    gate = 2 / 2 ** (8 * width - 1)
    test(f"{8 * width}-bit stereo -> per-sample mean: len {len(data)}, max abs error {err:.3g} (gate {gate:.3g})",
         got_sr == SR and len(data) == len(L) and data.dtype == np.float32 and err < gate)

try:
    _read_wav_file(write_wav("u8.wav", bytes(1000), SR, 1))
    raised = False
except ValueError:
    raised = True
test("8-bit (1-byte width) raises ValueError", raised)


# ============================================
# _install_sample
# ============================================
print("\n--- Sample install ---")
x220 = tone_h2(220.0, 2.0)
eng = AudioEngine()
info = eng._install_sample(x220, SR, "tone220")
s = eng._drone_sample
test(f"220 Hz: freq_hz {info['freq_hz']:.4f} within 1% ({cents(info['freq_hz'], 220.0):+.3f} c)",
     abs(info["freq_hz"] / 220 - 1) < 0.01)
test(f"220 Hz: duration {info['duration_s']:.3f} s = 2.0 s minus 2 x 0.2 s trim",
     info["sr"] == SR and abs(info["duration_s"] - 1.6) < 1e-9 and len(s) == 70560)
test("220 Hz: label kept, pitch_confident", info["label"] == "tone220" and info["pitch_confident"])
test("install switches drone_type to 'sample'", eng.drone_type == "sample")
test(f"sample_info() -> {eng.sample_info()}", eng.sample_info() == ("tone220", info["freq_hz"]))

# Crossfade: a whole number of periods (4 x 200.45 = 802 samples, rounded,
# not int()-truncated to 800), only the last L samples differ from the
# trimmed input, and the last one is head[L-1] (linear weight 1).
trimmed = x220[8820:-8820]
L_rule = int(round(4 * SR / info["freq_hz"]))
changed = np.nonzero(s != trimmed[:len(s)])[0]
test(f"crossfade length {L_rule} = round(4 periods), ends on head[L-1], nothing changed before it",
     L_rule == 802 and s[-1] == trimmed[L_rule - 1] and int(changed[0]) >= len(s) - L_rule)

# 25% cap: 60 Hz for 0.25 s (no trim) wants 4 x 735 = 2940 > 11025 // 4.
# The 150 ms cap cannot bind: 4 periods at the 55 Hz fmin is 73 ms.
y60 = (0.5 * np.sin(2 * np.pi * 60 * np.arange(SR // 4) / SR)).astype(np.float32)
e60 = AudioEngine()
i60 = e60._install_sample(y60, SR, "60")
s60 = e60._drone_sample
period60 = SR / i60["freq_hz"]
L60 = int(round(3 * period60))          # 3 whole periods fit under the 25 % cap (2756); 4 do not
ch = np.nonzero(s60 != y60[:len(s60)])[0]
test(f"0.25 s input not trimmed (len {len(s60)}, {i60['duration_s']} s)", len(s60) == len(y60))
test(f"60 Hz short sample: crossfade is whole periods under the 25% cap ({L60} = 3 x {period60:.1f}; cap {len(y60) // 4})",
     L60 <= len(y60) // 4 and s60[-1] == y60[L60 - 1] and int(ch[0]) >= len(s60) - L60)

# Loop seam: the wrap from s[-1] to s[0] should be no bigger than a normal step.
step_p99 = float(np.percentile(np.abs(np.diff(s)), 99))
seam = float(abs(s[-1] - s[0]))
test(f"loop seam |s[-1]-s[0]| {seam:.4f} <= p99 step {step_p99:.4f} (ratio {seam / step_p99:.2f})", seam <= step_p99)

# Crossfade level: head and tail of a steady tone are correlated, so the
# per-period peak inside the crossfade should stay near the body's peak for
# any sample length (67 lengths spanning two periods).
lo_db, hi_db = 0.0, 0.0
x_long = tone_h2(220.0, 2.2)
for n in range(88200, 88602, 6):
    e = AudioEngine()
    e._install_sample(x_long[:n], SR, "t")
    b = e._drone_sample
    body = float(np.max(np.abs(b[:-800])))
    for i in range(0, 600, 100):
        db = 20 * math.log10(float(np.max(np.abs(b[len(b) - 800 + i:len(b) - 600 + i]))) / body)
        lo_db, hi_db = min(lo_db, db), max(hi_db, db)
test(f"crossfade level within +/-1.5 dB of body over 67 lengths (measured {lo_db:+.2f} .. {hi_db:+.2f} dB)",
     lo_db > -1.5 and hi_db < 1.5)

# YIN's lag range stops at int(sr / fmin) = 801 < 801.8, so 55 Hz itself (A1) is out of reach.
y55 = (0.5 * np.sin(2 * np.pi * 55 * np.arange(SR) / SR)).astype(np.float32)
i55 = AudioEngine()._install_sample(y55, SR, "55")
test(f"55 Hz (A1, the YIN fmin) detected: freq_hz {i55['freq_hz']:.2f}, confident {bool(i55['pitch_confident'])}",
     abs(i55["freq_hz"] / 55 - 1) < 0.01)

noise = (0.3 * np.random.default_rng(1).standard_normal(SR)).astype(np.float32)
i_n = AudioEngine()._install_sample(noise, SR, "noise")
test(f"white noise: pitch_confident False, freq_hz {i_n['freq_hz']} (440 fallback)",
     not i_n["pitch_confident"] and i_n["freq_hz"] == 440.0)


# ============================================
# _render_sample_voices
# ============================================
print("\n--- Sample playback ---")
BLOCKS, FR = 32, 1024


def render(e):
    return np.concatenate([e._render_sample_voices(FR) for _ in range(BLOCKS)])


eng.set_drone(freq=330.0, voicing="root", dtype="sample")
N = len(eng._drone_sample)
p0 = eng._sample_phases.copy()
out = render(eng)
f, _ = peak_in(out, SR, 200, 1000)
test(f"root at 330 Hz from a 220 Hz sample: peak {f:.3f} Hz ({cents(f, 330):+.3f} c, gate 1%)",
     abs(f / 330 - 1) < 0.01)
want = (330.0 / eng._drone_sample_freq * FR * BLOCKS) % N
ph = eng._sample_phases
test(f"playhead {ph[0]:.3f} = (rate x {FR * BLOCKS}) mod N = {want:.3f}, within [0, {N})",
     not np.array_equal(ph, p0) and abs(ph[0] - want) < 1e-6 and np.all((ph >= 0) & (ph < N)))
test(f"render output finite and within +/-1 (peak {np.max(np.abs(out)):.3f})",
     np.all(np.isfinite(out)) and np.max(np.abs(out)) <= 1.0)

eng.set_drone(voicing="fifth")
out = render(eng)
f1, m1 = peak_in(out, SR, 300, 360)
f2, m2 = peak_in(out, SR, 470, 520)
test(f"fifth: peaks {f1:.2f} Hz ({cents(f1, 330):+.2f} c) and {f2:.2f} Hz ({cents(f2, 495):+.2f} c), level ratio {m2 / m1:.2f}",
     abs(f1 / 330 - 1) < 0.01 and abs(f2 / 495 - 1) < 0.01 and m2 / m1 > 0.4)

eng.set_drone(voicing="root")
eng.sr = 48000
out = render(eng)
f, _ = peak_in(out, 48000, 200, 1000)
test(f"output at 48 kHz still plays 330 Hz: {f:.3f} Hz ({cents(f, 330):+.3f} c; without the sr ratio: 359)",
     abs(f / 330 - 1) < 0.01)


# ============================================
# _output_callback, synth path
# ============================================
print("\n--- Synth output ---")
e = AudioEngine()
e.set_drone(on=True, freq=261.63, voicing="root", dtype="sine", volume=0.3)
buf = np.zeros((FR, 1), dtype=np.float32)
settle = 0
while e._current_amp < 0.3 and settle < 50:
    e._output_callback(buf, FR, None, None)
    settle += 1
test(f"sine: amp slew reaches 0.3 in {settle} block(s) ({0.3 / e._amp_slew:.0f} samples)",
     settle == 1 and e._current_amp == 0.3)
chunks = []
for _ in range(BLOCKS):
    e._output_callback(buf, FR, None, None)
    chunks.append(buf[:, 0].copy())
out = np.concatenate(chunks)
f, _ = peak_in(out, SR, 100, 1000)
pk = float(np.max(np.abs(out)))
test(f"sine: peak {f:.3f} Hz ({cents(f, 261.63):+.3f} c, gate 0.5%), amplitude {pk:.4f}",
     abs(f / 261.63 - 1) < 0.005 and abs(pk - 0.3) < 0.003)
e.set_drone(on=False)
fade = 0
while fade < 50:
    e._output_callback(buf, FR, None, None)
    fade += 1
    if not buf.any():
        break
test(f"drone off fades to exact 0 in {fade} block(s)", fade <= 2 and e._current_amp == 0.0 and not buf.any())

# rich = harmonics 1..8 per voice (fundamental + 7 overtones).
counts = {}
for v in ("root", "fifth", "major"):
    e.set_drone(voicing=v, dtype="rich")
    counts[v] = len(e._osc_freqs)
e.set_drone(voicing="root")
ratios = [fr / e.drone_freq for fr, _ in e._osc_freqs]
test(f"rich oscillator counts {counts} (8 per voice)", counts == {"root": 8, "fifth": 16, "major": 24})
test(f"rich root harmonics are 1..8 x f ({[round(r, 3) for r in ratios]})", np.allclose(ratios, np.arange(1, 9)))


# ============================================
# Recording
# ============================================
print("\n--- Recording ---")
IB = 4096
rec_tone = (0.2 * np.sin(2 * np.pi * 196 * np.arange(11 * IB) / SR)).astype(np.float32)


def feed(e, sig):
    for i in range(0, len(sig), IB):
        e._input_callback(sig[i:i + IB].reshape(-1, 1), IB, None, None)


e = AudioEngine()
e.record_start()
feed(e, rec_tone)
d = e.recorded_duration_s()
test(f"recorded_duration_s {d:.4f} s = 11 x {IB} / {SR}", e.is_recording() and abs(d - 11 * IB / SR) < 1e-12)
info = e.record_stop_and_use()
b = e._drone_sample
body_pk = float(np.max(np.abs(b[:len(b) // 2])))
test(f"stop_and_use: freq {info['freq_hz']:.3f} Hz ({cents(info['freq_hz'], 196):+.3f} c, gate 1%), label {info['label']!r}",
     abs(info["freq_hz"] / 196 - 1) < 0.01 and info["label"] == "recorded" and not e.is_recording())
test(f"stop_and_use: 0.2-peak input normalized to {body_pk:.4f} (want 0.95)", abs(body_pk - 0.95) < 0.005)

e2 = AudioEngine()
e2.record_start()
feed(e2, rec_tone[:2 * IB])
short_d = e2.recorded_duration_s()
test(f"too short ({short_d:.3f} s < 0.2 s): returns None, no sample, drone_type stays 'rich'",
     e2.record_stop_and_use() is None and e2.drone_type == "rich" and e2._drone_sample is None)

e2.record_start()
feed(e2, rec_tone[:3 * IB])
e2.record_cancel()
test("record_cancel drops chunks, is_recording False", e2._recording_chunks == [] and not e2.is_recording())
feed(e2, rec_tone[:IB])
test("not recording: _input_callback appends nothing", e2._recording_chunks == [] and e2.recorded_duration_s() == 0.0)


# ============================================
# save_sample_wav / clear_sample
# ============================================
print("\n--- Save and clear ---")
path = os.path.join(TMP, "saved.wav")
e.save_sample_wav(path)
back, back_sr = _read_wav_file(path)
test(f"save round trip: len {len(back)}, sr {back_sr}", len(back) == len(b) and back_sr == SR)
# Split so the two causes read apart: anything past +/-1 is clipped by the save.
err = float(np.max(np.abs(back - b)))
over = int(np.sum(np.abs(b) > 1.0))
test(f"installed recording within +/-1 (peak {np.max(np.abs(b)):.4f}, {over} samples over; whole-buffer save error {err * 32768:.0f} LSB)",
     over == 0)
inr = np.abs(b) <= 1.0
err = float(np.max(np.abs(back - b)[inr]))
# Rounded on write, scaled by 32767 out and 32768 in (the usual asymmetric
# int16 convention): up to 0.5 + ~1 LSB.
test(f"save round trip max abs error on in-range samples {err:.3g} ({err * 32768:.2f} LSB, gate 2 LSB)",
     err < 2 / 32768 + 1e-9)
try:
    AudioEngine().save_sample_wav(os.path.join(TMP, "none.wav"))
    raised = False
except ValueError:
    raised = True
test("save with no sample raises ValueError", raised)
e.clear_sample()
test(f"clear_sample: sample_info {e.sample_info()}, drone_type {e.drone_type!r}",
     e.sample_info() == (None, None) and e.drone_type == "rich" and e._sample_phases is None)


# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
