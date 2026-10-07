"""Latency test (Help > Test Audio Latency...) on a fake sounddevice.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on
any failure. Run directly or through tools/run_tests.py. Needs no audio
device: audio_latency.sd is replaced with FakeSD, whose playrec returns
the played signal delayed by a known number of samples.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-latency-test-")

import logging  # noqa: E402

import numpy as np  # noqa: E402

import audio_latency as al  # noqa: E402

logging.disable(logging.CRITICAL)   # measure() logs at WARNING on every run

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


class FakeSD:
    """Stand-in for sounddevice. ``delays_ms`` is one delay for every chirp
    or one per chirp; ``mode`` is "echo", "zeros" or "drop_first"."""

    def __init__(self, delays_ms=(90.0,), noise_dbfs=None, mode="echo",
                 refuse_rates=(), latency=(0.046, 0.093), default_rate=44100,
                 devices=None, hostapis=None, query_raises=False):
        self.delays_ms = list(delays_ms)
        self.noise_dbfs = noise_dbfs
        self.mode = mode
        self.refuse_rates = set(refuse_rates)
        self.latency = latency
        self.default_rate = default_rate
        self.devices = devices or {}
        self.hostapis = hostapis or {}
        self.query_raises = query_raises
        self.stream_kwargs = []
        self.playrec_kwargs = []
        fake = self

        class Stream:
            def __init__(self, **kw):
                fake.stream_kwargs.append(kw)
                if kw["samplerate"] in fake.refuse_rates:
                    raise RuntimeError(f"Invalid sample rate {kw['samplerate']}")
                self.latency = fake.latency

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        self.Stream = Stream

    def query_devices(self, device, kind):
        if self.query_raises:
            raise RuntimeError("PortAudio not initialized")
        if device in self.devices:
            return self.devices[device]
        return {"name": f"Fake default {kind}", "hostapi": 0,
                "default_samplerate": float(self.default_rate)}

    def query_hostapis(self, i):
        if self.query_raises:
            raise RuntimeError("PortAudio not initialized")
        return self.hostapis.get(i, {"default_output_device": 1})

    def playrec(self, signal, blocking=True, **kw):
        self.playrec_kwargs.append(kw)
        sr = kw["samplerate"]
        if sr in self.refuse_rates:
            raise RuntimeError(f"Invalid sample rate {sr}")
        n = len(signal)
        out = np.zeros(n, dtype=np.float64)
        if self.mode != "zeros":
            clen = int(al.CHIRP_S * sr)
            for k, t0 in enumerate(al.CHIRP_TIMES_S):
                if self.mode == "drop_first" and k == 0:
                    continue
                d = self.delays_ms[k] if len(self.delays_ms) > 1 else self.delays_ms[0]
                lag = int(round(d * sr / 1000.0))
                i = int(t0 * sr)
                seg = signal[i:i + clen]
                j = min(n, i + lag + len(seg))
                out[i + lag:j] += seg[:j - (i + lag)]
        if self.noise_dbfs is not None:
            rms = 10 ** (self.noise_dbfs / 20.0)
            out += np.random.default_rng(1234).normal(0.0, rms, n)
        return out.astype(np.float32).reshape(n, 1)


def run(fake, *args, **kw):
    al.sd = fake
    return al.measure(*args, **kw)


# ============================================
# 90 ms ROUND TRIP AT 44100
# ============================================
print("\n--- 90 ms delay at 44100 Hz ---")
fake = FakeSD(delays_ms=(90.0,), latency=(0.046, 0.093))
r = run(fake)
test("ok is True", r.ok is True)
test(f"round_trip_ms within 1.5 ms of 90 (got {r.round_trip_ms})",
     r.round_trip_ms is not None and abs(r.round_trip_ms - 90.0) <= 1.5)
test(f"3 per-chirp readings (got {len(r.per_chirp_ms)})", len(r.per_chirp_ms) == 3)
test(f"sample_rate 44100 (got {r.sample_rate})", r.sample_rate == 44100)
test(f"reported_input_ms 46 from stream latency 0.046 s (got {r.reported_input_ms})",
     r.reported_input_ms is not None and abs(r.reported_input_ms - 46.0) < 1e-6)
test(f"reported_output_ms 93 from stream latency 0.093 s (got {r.reported_output_ms})",
     r.reported_output_ms is not None and abs(r.reported_output_ms - 93.0) < 1e-6)
test(f"input_name from query_devices (got {r.input_name!r})", r.input_name == "Fake default input")
test(f"output_name from query_devices (got {r.output_name!r})", r.output_name == "Fake default output")
test(f"message 'OK' (got {r.message!r})", r.message == "OK")
test("probe Stream got a callback and the same rate/channels/dtype as playrec",
     fake.stream_kwargs and callable(fake.stream_kwargs[0].get("callback"))
     and {k: fake.stream_kwargs[0][k] for k in ("samplerate", "channels", "dtype", "device")}
     == fake.playrec_kwargs[0])
test(f"90 ms -> 'Acceptable', not 'Tight' (TIGHT_MS {al.TIGHT_MS}) (got {r.verdict()[:11]!r})",
     r.verdict().startswith("Acceptable"))

for ms, word in ((60.0, "Tight"), (120.0, "Acceptable"), (300.0, "Laggy")):
    r = run(FakeSD(delays_ms=(ms,)))
    test(f"{ms:.0f} ms reads {ms:.0f} +-1.5 (got {r.round_trip_ms}) and verdict '{word}'",
         r.ok and abs(r.round_trip_ms - ms) <= 1.5 and r.verdict().startswith(word))

r = run(FakeSD(delays_ms=(90.0,)), input_device=2)
test("input device 2 passes device=(2, matching output 1) to the stream",
     al.sd.playrec_kwargs[0]["device"] == (2, 1))

# ============================================
# NOISE
# ============================================
print("\n--- -30 dBFS white noise ---")
r = run(FakeSD(delays_ms=(90.0,), noise_dbfs=-30.0))
test(f"90 ms in -30 dBFS noise: ok and within 2 ms (got {r.round_trip_ms}, chirps {r.per_chirp_ms})",
     r.ok and abs(r.round_trip_ms - 90.0) <= 2.0)

# ============================================
# NOT DETECTED
# ============================================
print("\n--- Echo cancellation ate the chirps (zeros) ---")
r = run(FakeSD(mode="zeros"))
test("zeros: ok False", r.ok is False)
test("zeros: message mentions 'echo cancellation'", "echo cancellation" in r.message)
test(f"zeros: per_chirp_ms empty (got {r.per_chirp_ms})", r.per_chirp_ms == [])
test("zeros: round_trip_ms None", r.round_trip_ms is None)
test(f"zeros: verdict 'Not measured' (got {r.verdict()!r})", r.verdict() == "Not measured")

print("\n--- Disagreeing chirps 60 / 200 / 400 ms (AGREE_MS 15) ---")
r = run(FakeSD(delays_ms=(60.0, 200.0, 400.0)))
test(f"all three detected individually (got {[round(x) for x in r.per_chirp_ms]})",
     len(r.per_chirp_ms) == 3)
test("disagreeing: ok False", r.ok is False)
test("disagreeing: message mentions 'echo cancellation'", "echo cancellation" in r.message)
test("disagreeing: round_trip_ms None", r.round_trip_ms is None)

r = run(FakeSD(delays_ms=(90.0, 100.0, 300.0)))
test(f"90 / 100 / 300 ms: two agree within 15 ms -> ok, median 100 (got {r.round_trip_ms})",
     r.ok and abs(r.round_trip_ms - 100.0) <= 1.5)

print("\n--- Only two chirps detected, agreeing ---")
r = run(FakeSD(delays_ms=(90.0,), mode="drop_first"))
test(f"first chirp dropped: 2 readings (got {len(r.per_chirp_ms)})", len(r.per_chirp_ms) == 2)
test(f"first chirp dropped: ok True, 90 +-1.5 ms (got {r.round_trip_ms})",
     r.ok and abs(r.round_trip_ms - 90.0) <= 1.5)

# ============================================
# SAMPLE-RATE FALLBACK
# ============================================
print("\n--- Rate fallback ---")
fake = FakeSD(delays_ms=(90.0,), refuse_rates=(44100,), default_rate=48000)
r = run(fake)
test(f"44100 refused -> sample_rate 48000 (got {r.sample_rate})", r.sample_rate == 48000)
test(f"at 48000 the 90 ms delay (4320 samples) reads 90 +-1.5 (got {r.round_trip_ms})",
     r.ok and abs(r.round_trip_ms - 90.0) <= 1.5)
test("44100 tried first, then 48000",
     [k["samplerate"] for k in fake.stream_kwargs] == [44100, 48000])

fake = FakeSD(delays_ms=(90.0,), refuse_rates=(44100,), default_rate=44100)
r = run(fake)
test(f"44100 refused, defaults 44100 -> 48000 still tried last (got {r.sample_rate})",
     r.sample_rate == 48000 and r.ok)

r = run(FakeSD(refuse_rates=(44100, 48000, 16000), default_rate=16000))
test("all rates refused: ok False", r.ok is False)
test(f"all rates refused: message starts 'Could not open a full-duplex stream' (got {r.message!r})",
     r.message.startswith("Could not open a full-duplex stream"))
test("all rates refused: sample_rate None", r.sample_rate is None)

# ============================================
# DEVICE HELPERS
# ============================================
print("\n--- _matching_output / _candidate_rates ---")
al.sd = FakeSD(devices={2: {"name": "USB mic", "hostapi": 1, "default_samplerate": 48000.0}},
               hostapis={1: {"default_output_device": 4}})
test("input 2 on hostapi 1 (default output 4) -> 4", al._matching_output(2) == 4)
al.sd = FakeSD(devices={2: {"name": "USB mic", "hostapi": 1, "default_samplerate": 48000.0}},
               hostapis={1: {"default_output_device": -1}})
test("hostapi default output -1 -> None", al._matching_output(2) is None)
test("input None -> None", al._matching_output(None) is None)
al.sd = FakeSD(query_raises=True)
test("query raising -> None", al._matching_output(2) is None)
test(f"query raising: candidate rates [44100, 48000] (got {al._candidate_rates(2, 4)})",
     al._candidate_rates(2, 4) == [44100, 48000])

devs = {2: {"name": "a", "hostapi": 0, "default_samplerate": 16000.0},
        4: {"name": "b", "hostapi": 0, "default_samplerate": 22050.0}}
al.sd = FakeSD(devices=devs)
got = al._candidate_rates(2, 4)
test(f"in 16000 / out 22050 -> [44100, 16000, 22050, 48000] (got {got})",
     got == [44100, 16000, 22050, 48000])
devs[4] = {"name": "b", "hostapi": 0, "default_samplerate": 16000.0}
got = al._candidate_rates(2, 4)
test(f"in 16000 / out 16000 deduplicated -> [44100, 16000, 48000] (got {got})",
     got == [44100, 16000, 48000])
devs[2] = {"name": "a", "hostapi": 0, "default_samplerate": 48000.0}
devs[4] = {"name": "b", "hostapi": 0, "default_samplerate": 44100.0}
got = al._candidate_rates(2, 4)
test(f"in 48000 / out 44100 -> [44100, 48000] (got {got})", got == [44100, 48000])

# ============================================
# NO SOUNDDEVICE
# ============================================
print("\n--- sounddevice missing ---")
_saved = al.sd
al.sd = None
r = al.measure()
al.sd = _saved
test("sd None: ok False", r.ok is False)
test(f"sd None: message 'sounddevice is not installed.' (got {r.message!r})",
     r.message == "sounddevice is not installed.")

print()
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    sys.exit(1)
