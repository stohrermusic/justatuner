"""audio_utils gates + TunerEngine stream handling on a fake sounddevice.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on
any failure. Run directly or through tools/run_tests.py. Never opens a
real audio stream: every stream comes from FakeSD below, so it runs with
no display and no audio device.
"""
import logging
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat_test_audio_utils_")

import numpy as np  # noqa: E402

import tuner.engine as te  # noqa: E402
from audio_utils import (  # noqa: E402
    AudioRingBuffer, hann_peak_freq, open_input_stream, open_output_stream,
    synthetic_tone,
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


class FakePortAudioError(Exception):
    pass


class FakeSD:
    """Stands in for the sounddevice module. Streams refuse any rate in
    refuse_rates, any device in refuse_devices, or everything when
    refuse_all; query_devices reports default_rate (or raises)."""

    def __init__(self, refuse_rates=(), refuse_devices=(), default_rate=44100,
                 query_raises=False):
        self.refuse_rates = set(refuse_rates)
        self.refuse_devices = set(refuse_devices)
        self.refuse_all = False
        self.default_rate = default_rate
        self.query_raises = query_raises
        self.attempts = []      # (kind, device, rate) for every constructor call
        self.constructed = []   # streams that opened
        self.raised = []        # exceptions raised, in order
        fake = self

        class _Stream:
            kind = None

            def __init__(s, samplerate=None, device=None, callback=None, **kw):
                s.samplerate, s.device, s.callback, s.kwargs = samplerate, device, callback, kw
                s.started = s.stopped = s.closed = False
                s.latency = 0.0116
                fake.attempts.append((s.kind, device, samplerate))
                if (fake.refuse_all or samplerate in fake.refuse_rates
                        or device in fake.refuse_devices):
                    err = FakePortAudioError(
                        f"Invalid sample rate [{samplerate}] on device {device!r}")
                    fake.raised.append(err)
                    raise err
                fake.constructed.append(s)

            def start(s):
                s.started = True

            def stop(s):
                s.stopped = True

            def close(s):
                s.closed = True

        class InputStream(_Stream):
            kind = "input"

        class OutputStream(_Stream):
            kind = "output"

        self.InputStream, self.OutputStream = InputStream, OutputStream

    def query_devices(self, device=None, kind=None):
        if self.query_raises:
            raise FakePortAudioError("no such device")
        return {"name": "Fake", "default_samplerate": float(self.default_rate)}


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self, word=""):
        return [r.getMessage() for r in self.records
                if r.levelno >= logging.WARNING and word in r.getMessage()]


LOG = Capture()
logging.getLogger().addHandler(LOG)
te.AUDIO_AVAILABLE = True   # start() must reach the fake even without PortAudio


def push(stream, block):
    """Deliver one block through the stream's recorded callback, shaped
    (frames, 1) the way sounddevice hands it over."""
    block = np.asarray(block, dtype=np.float32).reshape(-1, 1)
    stream.callback(block, len(block), None, None)


# ============================================
print("\n--- 1. AudioRingBuffer ---")
rb = AudioRingBuffer(10)
test("read() is None before any write", rb.read() is None)
test("buffer dtype is float32", rb.buffer.dtype == np.float32)
rb.write(np.arange(1, 8, dtype=np.float32))
rb.write(np.arange(8, 13, dtype=np.float32))
got = rb.read()
test(f"write 1..7 then 8..12 wraps; read() gives 3..12 (got {got.astype(int).tolist()})",
     got.tolist() == list(range(3, 13)))
test(f"read() returns float32 (got {got.dtype})", got.dtype == np.float32)
test("is_stale() True right after a read", rb.is_stale())
rb.write(np.array([13.0], dtype=np.float32))
test("is_stale() False after the next write", not rb.is_stale())
test("read() after 1 more sample gives 4..13", rb.read().tolist() == list(range(4, 14)))
rb.write(np.arange(1, 16, dtype=np.float32))
test("a 15-sample write keeps the last 10 (6..15)", rb.read().tolist() == list(range(6, 16)))
rb.clear()
test("clear() resets: read() None, zeros, write_pos 0, counts 0",
     rb.read() is None and not rb.buffer.any() and rb.write_pos == 0
     and rb.write_count == 0 and rb.last_read_count == 0)


# ============================================
print("\n--- 2. synthetic_tone ---")
chunks = np.concatenate([synthetic_tone(p, 1024, 440.0, 44100) for p in (0, 1024, 2048)])
whole = synthetic_tone(0, 3072, 440.0, 44100)
d = float(np.max(np.abs(chunks - whole)))
test(f"440 Hz: chunks at pos 0/1024/2048 == one 3072-sample call (max diff {d:.2e})", d < 1e-5)
# Each call normalises by its own peak, so the gain of a chunk depends on
# which samples it happens to hold. Measured 2026-10-06: worst 0.0120 abs
# (4.0 % of amplitude) at 3675.7 Hz; 0.0 at 440 Hz. Phase is continuous;
# per-chunk gain is not.
worst, worst_f = 0.0, 0.0
for f in np.arange(27.5, 4200.0, 0.37):
    c = np.concatenate([synthetic_tone(p, 1024, f, 44100) for p in (0, 1024, 2048)])
    dd = float(np.max(np.abs(c - synthetic_tone(0, 3072, f, 44100))))
    if dd > worst:
        worst, worst_f = dd, f
test(f"27.5-4200 Hz sweep: chunked vs one call within 5 % of amplitude "
     f"(worst {worst:.4f} = {worst / 0.3:.1%} at {worst_f:.1f} Hz; per-call peak normalisation)",
     worst < 0.3 * 0.05)
amp = float(np.max(np.abs(synthetic_tone(0, 4096, 440.0, 44100, amplitude=0.42))))
test(f"peak amplitude equals amplitude=0.42 (got {amp:.6f})", abs(amp - 0.42) < 1e-6)
pure = synthetic_tone(0, 4096, 430.6640625, 44100, harmonics_db=(0.0,))   # exactly bin 40
m = np.abs(np.fft.rfft(pure * np.hanning(4096)))
ratio = float(m[80] / m[40])
test(f"harmonics_db=(0.0,) is a pure sine: energy at 2f is {20 * np.log10(ratio + 1e-30):.0f} dB re f",
     ratio < 1e-4)
h2 = synthetic_tone(0, 4096, 430.6640625, 44100)
m2 = np.abs(np.fft.rfft(h2 * np.hanning(4096)))
test(f"default harmonics_db: 2f sits at -6 dB ({20 * np.log10(m2[80] / m2[40]):+.2f} dB)",
     abs(20 * np.log10(m2[80] / m2[40]) + 6.0) < 0.05)
test("dtype float32", pure.dtype == np.float32 and h2.dtype == np.float32)


# ============================================
print("\n--- 3. hann_peak_freq edge cases ---")
test("all-zero mags returns k*bin_freq (7 * 2.5 = 17.5)",
     hann_peak_freq(np.zeros(20), 7, 2.5) == 17.5)
# A hand-made lobe peaking at bin 6 with Hann on-bin neighbours (0.5).
lobe = np.array([0.01, 0.02, 0.04, 0.08, 0.16, 0.5, 1.0, 0.5, 0.16, 0.08, 0.04, 0.02])
test(f"k=4, peak two bins up: climbs to 6 (got {hann_peak_freq(lobe, 4, 1.0)})",
     hann_peak_freq(lobe, 4, 1.0) == 6.0)
test(f"k=8, peak two bins down: climbs to 6 (got {hann_peak_freq(lobe, 8, 1.0)})",
     hann_peak_freq(lobe, 8, 1.0) == 6.0)
# Three bins away the 2-step climb stops at bin 5 (or 7), on the lobe's
# flank; there a = 1.0/0.5 = 2 gives d = 1.0, which the clamp cuts to half
# a bin. Documented behaviour: reads 5.5 (6.5), half a bin short of 6.
got3 = hann_peak_freq(lobe, 3, 1.0)
test(f"k=3, peak three bins up: climb stops at 5, d clamps to +0.5 -> 5.5 (got {got3})", got3 == 5.5)
got9 = hann_peak_freq(lobe, 9, 1.0)
test(f"k=9, peak three bins down: climb stops at 7, d clamps to -0.5 -> 6.5 (got {got9})", got9 == 6.5)
sym = hann_peak_freq(np.array([0.0, 0.5, 1.0, 0.5, 0.0]), 2, 1.0)
test(f"symmetric Hann on-bin neighbours [0.5, 1, 0.5]: d = 0 (got {sym - 2:+.4f})", sym == 2.0)
# A lobe broadened symmetrically (e.g. a note decaying inside the frame)
# has equal neighbours above 0.5. The one-sided formula uses whichever
# neighbour wins the >= tie and reads d = (2a-1)/(a+1) = +0.333 here; the
# answer by symmetry is 0. Measured 2026-10-06 on an exactly-on-bin tone
# decaying with tau 50 ms: +0.021 bin, and -0.030/+0.030 for tones only
# +-0.01 bin either side (tau 20 ms: +-0.11 bin) -- a jump across d = 0.
# 2(R-L)/(L+2P+R) is equally exact on a clean Hann lobe and gives 0 here.
symb = hann_peak_freq(np.array([0.0, 0.8, 1.0, 0.8, 0.0]), 2, 1.0)
test(f"symmetric broadened neighbours [0.8, 1, 0.8]: d = 0 (got {symb - 2:+.4f})",
     abs(symb - 2.0) < 1e-9)


# ============================================
print("\n--- 4. Stream fallback ---")
for opener, kind in ((open_input_stream, "input"), (open_output_stream, "output")):
    fake = FakeSD()
    LOG.records.clear()
    s, rate = opener(fake, None, 44100, channels=1, blocksize=1024)
    test(f"{kind}: 44100 accepted returns (stream, 44100) (got {rate})",
         rate == 44100 and s.samplerate == 44100 and s.kind == kind
         and s.kwargs == {"channels": 1, "blocksize": 1024})
    test(f"{kind}: no 'refused' warning when the rate is accepted", not LOG.warnings("refused"))

    fake = FakeSD(refuse_rates={44100}, default_rate=16000)
    LOG.records.clear()
    s, rate = opener(fake, 3, 44100, channels=1)
    w = LOG.warnings("refused")
    test(f"{kind}: 44100 refused, default 16000 -> stream at 16000 (got {rate}, {s.samplerate})",
         rate == 16000 and s.samplerate == 16000 and s.device == 3)
    test(f"{kind}: WARNING names both rates ({w[0] if w else 'none'})",
         len(w) == 1 and "44100" in w[0] and "16000" in w[0])

    fake = FakeSD(refuse_rates={44100, 16000}, default_rate=16000)
    try:
        opener(fake, None, 44100)
        test(f"{kind}: fallback also refused raises", False)
    except FakePortAudioError as e:
        test(f"{kind}: fallback also refused raises the ORIGINAL exception ({e})",
             e is fake.raised[0] and "44100" in str(e) and len(fake.raised) == 2)

    fake = FakeSD(refuse_rates={44100}, query_raises=True)
    try:
        opener(fake, None, 44100)
        test(f"{kind}: no default rate (query_devices raises) re-raises", False)
    except FakePortAudioError as e:
        test(f"{kind}: no default rate (query_devices raises) re-raises the open error, one attempt",
             e is fake.raised[0] and len(fake.attempts) == 1)

    fake = FakeSD(refuse_rates={44100}, default_rate=44100)
    try:
        opener(fake, None, 44100)
        test(f"{kind}: default == refused rate re-raises", False)
    except FakePortAudioError as e:
        test(f"{kind}: default rate == refused 44100 re-raises without a retry",
             e is fake.raised[0] and len(fake.attempts) == 1)


# ============================================
print("\n--- 5. TunerEngine on a 16 kHz device (CoreAudio Bluetooth path) ---")
fake = FakeSD(refuse_rates={44100}, default_rate=16000)
te.sd = fake
eng = te.TunerEngine()
ok, err = eng.start()
test(f"start() returns (True, None) (got {ok}, {err})", ok and err is None)
test(f"engine.sample_rate == 16000 (got {eng.sample_rate})", eng.sample_rate == 16000)
size = len(eng._ring_buffer.buffer)
test(f"ring buffer = max(16000*{te.BUFFER_SECONDS}, FFT_SIZE) = FFT_SIZE {te.FFT_SIZE} (got {size})",
     size == max(int(16000 * te.BUFFER_SECONDS), te.FFT_SIZE) == te.FFT_SIZE)
stream = fake.constructed[-1]
test("stream opened at 16000, blocksize 1024, 1 channel, started",
     stream.samplerate == 16000 and stream.kwargs.get("blocksize") == 1024
     and stream.kwargs.get("channels") == 1 and stream.started)
n_blocks = 0
while n_blocks * 1024 < te.FFT_SIZE:
    t = (np.arange(1024) + n_blocks * 1024) / 16000.0
    push(stream, 0.5 * np.sin(2 * np.pi * 440.0 * t))
    n_blocks += 1
r = eng.analyze()
test(f"{n_blocks} blocks fill one FFT frame; analyze() lights A only "
     f"(mag {r.magnitudes[9]:.3f}, active {[i for i in range(12) if r.active[i]]})",
     r.active[9] and r.magnitudes[9] > 0.9 and sum(r.active) == 1)
test(f"A within 1 c at 16 kHz, bins {16000 / te.FFT_SIZE:.3f} Hz (cents_errors[9] = {r.cents_errors[9]:+.4f})",
     abs(r.cents_errors[9]) < 1.0)
eng.stop()


# ============================================
print("\n--- 6. Saved device that won't open ---")
fake = FakeSD(refuse_devices={7})
te.sd = fake
LOG.records.clear()
eng = te.TunerEngine()
ok, err = eng.start(device=7)
w = LOG.warnings("Input device")
test(f"device 7 refused, default accepted: (True, None) (got {ok}, {err})", ok and err is None)
test(f"_last_device is None after the fallback (got {eng._last_device!r})", eng._last_device is None)
test(f"WARNING mentions the device ({w[0] if w else 'none'})", len(w) == 1 and "7" in w[0])
test("the working stream is on the default device", fake.constructed[-1].device is None)
eng.stop()
fake = FakeSD(refuse_devices={7, None})
te.sd = fake
eng = te.TunerEngine()
ok, err = eng.start(device=7)
test(f"both refused: (False, message) and not running (got {ok}, {err!r})",
     ok is False and isinstance(err, str) and err and not eng.is_running)


# ============================================
print("\n--- 7. Stale-stream restart ---")
fake = FakeSD()
te.sd = fake
eng = te.TunerEngine()
eng.start()
first = fake.constructed[-1]
push(first, 0.5 * np.sin(2 * np.pi * 440.0 * np.arange(1024) / 44100.0))
eng.analyze()
n0 = len(fake.constructed)
for _ in range(te.STALE_RESTART_THRESHOLD + 1):
    eng.analyze()
test(f"{te.STALE_RESTART_THRESHOLD + 1} stale reads construct a new InputStream "
     f"({n0} -> {len(fake.constructed)})", len(fake.constructed) == n0 + 1)
test("old stream stopped and closed, new one started",
     first.stopped and first.closed and fake.constructed[-1].started)
test(f"last_error None and still running (got {eng.last_error!r})",
     eng.last_error is None and eng.is_running)
push(fake.constructed[-1], np.full(1024, 0.1))
eng.analyze()
fake.refuse_all = True
for _ in range(te.STALE_RESTART_THRESHOLD + 1):
    eng.analyze()
test(f"restart refused: last_error begins 'Audio stream lost' ({eng.last_error!r})",
     isinstance(eng.last_error, str) and eng.last_error.startswith("Audio stream lost"))
test("restart refused: is_running False", not eng.is_running)


# ============================================
print("\n--- 8. silent_seconds ---")
fake = FakeSD()
te.sd = fake
eng = te.TunerEngine()
eng.start()
s0 = eng.silent_seconds()
test(f"after start silent_seconds() is near 0 ({s0:.4f} s)", 0.0 <= s0 < 0.02)
push(fake.constructed[-1], np.zeros(1024))
time.sleep(0.05)
s1 = eng.silent_seconds()
test(f"exact zeros don't reset it: > 0.04 s after a 0.05 s sleep ({s1:.4f} s)", s1 > 0.04)
push(fake.constructed[-1], np.full(1024, 1e-4))
s2 = eng.silent_seconds()
test(f"a non-zero block resets it to near 0 ({s2:.4f} s)", s2 < 0.01)
eng.stop()
test(f"after stop() it is 0.0 (got {eng.silent_seconds()})", eng.silent_seconds() == 0.0)


# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
