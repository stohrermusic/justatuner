"""Drone-bleed cancellation on a simulated room — no audio device.

The engine's own output callback generates the drone; a simulated room
delays it, gives every partial its own gain and phase (a short decaying
echo), runs it through a mic clock that drifts by a chosen ppm against the
speaker clock, adds noise, and mixes the player's note in. Everything is
pushed through _push_input and read back through get_pitch(), the live
path, in input-sample time (no real-time waits).

Scenarios, each measured first (2026-10-07):
  speakers, player silent     -> no pitch (the drone must not read as a unison)
  speakers, just third/fifth  -> within 2 c (the notch read -12 / -5.5 c)
  speakers, locked unison     -> within 2 c and NOT learned away over 30 s
  speakers + 50 ppm drift     -> still cancelling after 60 s of silence
  headphones mode             -> no listen, unison exact
  speakers mode on headphones -> gains learn ~0, unison exact
  sample drone                -> the old notch (documented)
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-cancel-test-")

import numpy as np  # noqa: E402

from exerciser.engine import (  # noqa: E402
    AudioEngine, BLEED_LISTEN_S, BLEED_SETTLE_S, INPUT_BLOCK, OUTPUT_BLOCK,
)

SR = 44100
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


class Room:
    """Speaker -> room -> mic for the engine's drone output.

    delay_s: round trip. echo: (delay_s, gain) of one reflection, which
    makes the gain and phase differ per partial. ppm: the mic clock's rate
    error against the speaker clock. level: bleed level at the mic.
    """

    def __init__(self, engine, delay_s=0.12, echo=(0.011, 0.5), ppm=0.0, level=0.3,
                 noise_db=-55.0, seed=1):
        self.e = engine
        self.delay = int(delay_s * SR)
        self.echo_d, self.echo_g = int(echo[0] * SR), echo[1]
        self.ppm = ppm
        self.level = level
        self.noise = 10 ** (noise_db / 20)
        self.rng = np.random.default_rng(seed)
        self.out = np.zeros(0)
        self.pos = 0.0          # read position into the speaker stream, in speaker samples

    def _more_output(self, n):
        buf = np.zeros((OUTPUT_BLOCK, 1), dtype=np.float32)
        while len(self.out) < n:
            self.e._output_callback(buf, OUTPUT_BLOCK, None, None)
            self.out = np.concatenate([self.out, buf[:, 0].astype(np.float64)])

    def block(self, player=None):
        """One INPUT_BLOCK of mic signal: bleed (+ player)."""
        n = INPUT_BLOCK
        rate = 1.0 + self.ppm * 1e-6              # speaker samples per mic sample
        idx = self.pos + rate * np.arange(n)
        need = int(idx[-1]) + 3
        self._more_output(need)
        base = np.interp(idx, np.arange(len(self.out)), self.out)
        d_idx = idx - self.delay
        direct = np.interp(d_idx, np.arange(len(self.out)), self.out, left=0.0)
        e_idx = d_idx - self.echo_d
        echo = np.interp(e_idx, np.arange(len(self.out)), self.out, left=0.0)
        del base
        mic = self.level * (direct + self.echo_g * echo)
        mic = mic / 0.3 * 0.3 if np.max(np.abs(self.out)) > 0 else mic
        mic = mic + self.rng.normal(0, self.noise, n)
        if player is not None:
            mic = mic + player
        self.pos += rate * n
        return mic.astype(np.float32)


def player_tone(f, start_sample, n=INPUT_BLOCK, amp=0.3):
    t = (np.arange(n) + start_sample) / SR
    return amp * (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t)
                  + 0.25 * np.sin(2 * np.pi * 3 * f * t))


def run(engine, room, seconds, player_hz=None, player_amp=0.3):
    """Drive the live path for `seconds` of input time; return the pitch
    readings (Hz or None) from every get_pitch() call."""
    readings = []
    n_blocks = int(seconds * SR / INPUT_BLOCK)
    for b in range(n_blocks):
        p = None if player_hz is None else player_tone(player_hz, engine._in_total, amp=player_amp)
        engine._push_input(room.block(p))
        f, c = engine.get_pitch()
        readings.append(f if (f is not None and c > 0.2) else None)
    return readings


def fresh(monitoring="speakers", dtype="rich"):
    e = AudioEngine()
    # No device ever: with running=True the health check would open the real
    # microphone, and a pile of never-closed PortAudio streams segfaulted
    # the interpreter on garbage collection (2026-10-07).
    e._start_input_stream = lambda: None
    e._start_output_stream = lambda: None
    e.running = True
    e.monitoring = monitoring
    e.set_drone(on=True, freq=130.81, voicing="root", dtype=dtype, volume=0.3)
    return e


LISTEN_TOTAL = BLEED_SETTLE_S + BLEED_LISTEN_S + 0.4   # plus a buffer's worth


# ============================================
print("\n--- Speakers: the drone alone must not read as a note ---")
e = fresh()
room = Room(e)
r = run(e, room, LISTEN_TOTAL)
test(f"no pitch is reported while listening ({sum(x is None for x in r)}/{len(r)} None)", all(x is None for x in r))
test("after the listen the engine is cancelling", e.bleed_status() == "ready")
r = run(e, room, 4.0)
test(f"drone through speakers, player silent, 4 s: no pitch read ({sum(x is not None for x in r)} readings)",
     all(x is None for x in r))
# Residual bleed at the fundamental: project the cleaned buffer.
buf = np.roll(e._ring_buf, -e._ring_pos).copy()
t0 = (e._in_total - e._ring_size) / SR
c_raw, refs = e._bleed_project(buf, t0, [130.81])
dt = t0 + 0.5 * len(buf) / SR - e._bleed_tref
pred = e._bleed_gain[0] * np.exp(1j * e._bleed_slope[0] * dt)
residual_db = 20 * math.log10(abs(c_raw[0] - pred) / (abs(c_raw[0]) + 1e-12) + 1e-12)
test(f"fundamental bleed removed by {-residual_db:.1f} dB (gate 20 dB)", residual_db < -20)

# ============================================
print("\n--- Speakers: intervals over the bleed ---")
for name, ratio in (("just third", 5 / 4), ("just fifth", 3 / 2), ("just fourth", 4 / 3)):
    e = fresh()
    room = Room(e)
    run(e, room, LISTEN_TOTAL)
    f = 130.81 * ratio
    r = [x for x in run(e, room, 2.0, player_hz=f) if x is not None]
    err = cents(np.median(r), f) if r else float("nan")
    test(f"{name} over the bleeding drone reads within 2 c ({err:+.2f} c, {len(r)} readings)",
         bool(r) and abs(err) < 2.0)

# ============================================
print("\n--- Speakers: a locked unison is not learned away ---")
e = fresh()
room = Room(e)
run(e, room, LISTEN_TOTAL)
r = run(e, room, 30.0, player_hz=130.81 * 2 ** (1.0 / 1200))   # +1 c, held 30 s
vals = [x for x in r if x is not None]
errs = [cents(x, 130.81) for x in vals]
test(f"unison +1 c held 30 s: read on {len(vals)}/{len(r)} frames, median {np.median(errs):+.2f} c, "
     f"last 5 s median {np.median(errs[-50:]):+.2f} c (gate: >95 % read, within 2 c, not fading)",
     len(vals) > 0.95 * len(r) and abs(np.median(errs)) < 2.0 and abs(np.median(errs[-50:])) < 2.0)
gain_before = abs(e._bleed_gain[0])
test("the bleed gain did not absorb the player (unchanged while a pitch was read)",
     abs(abs(e._bleed_gain[0]) - gain_before) < 1e-9)

# ============================================
print("\n--- Speakers: clock drift of 50 ppm (USB mic + laptop speakers) ---")
e = fresh()
room = Room(e, ppm=50.0)
run(e, room, LISTEN_TOTAL)
slope_deg = np.degrees(e._bleed_slope[0])
print(f"        info: fitted drift at the fundamental {slope_deg:+.2f} deg/s (true {360 * 130.81 * 50e-6:.2f})")
r = run(e, room, 60.0)
test(f"50 ppm drift, 60 s of silence: still no pitch read ({sum(x is not None for x in r)} readings)",
     all(x is None for x in r))
f = 130.81 * 5 / 4
r = [x for x in run(e, room, 2.0, player_hz=f) if x is not None]
err = cents(np.median(r), f) if r else float("nan")
test(f"50 ppm drift: just third after 60 s reads within 2 c ({err:+.2f} c)", bool(r) and abs(err) < 2.0)

# ============================================
print("\n--- Headphones ---")
e = fresh(monitoring="headphones")
room = Room(e, level=0.0)                       # nothing reaches the mic
test("headphones: no listen, status off", e.bleed_status() == "off")
r = [x for x in run(e, room, 1.0, player_hz=130.81 * 2 ** (2.5 / 1200)) if x is not None]
test(f"headphones: unison +2.5 c reads {cents(np.median(r), 130.81):+.2f} c from the first frame (within 0.3)",
     bool(r) and abs(cents(np.median(r), 130.81) - 2.5) < 0.3)

e = fresh(monitoring="speakers")
room = Room(e, level=0.0)
run(e, room, LISTEN_TOTAL)
test(f"speakers mode on headphones: learned gain ~0 ({abs(e._bleed_gain[0]):.2e})", abs(e._bleed_gain[0]) < 1e-3)
r = [x for x in run(e, room, 1.0, player_hz=130.81 * 2 ** (2.5 / 1200)) if x is not None]
test(f"speakers mode on headphones: unison +2.5 c reads {cents(np.median(r), 130.81):+.2f} c (within 0.3)",
     bool(r) and abs(cents(np.median(r), 130.81) - 2.5) < 0.3)

# ============================================
print("\n--- The room table: a chord heard once needs no second listen ---")
e = fresh()
room = Room(e, ppm=20.0)
run(e, room, LISTEN_TOTAL)
test("C rich calibrated; its partials are in the room", e.room_known())
e.set_drone(freq=146.83)                        # D: new partials
test("D: not in the room yet", not e.room_known())
run(e, room, LISTEN_TOTAL)
test("D calibrated after its listen", e.bleed_status() == "ready" and e.room_known())
e.set_drone(freq=130.81)                        # back to C
test("back to C: known, so only the settle, no listen", e.room_known())
r = run(e, room, BLEED_SETTLE_S + 0.3)
test(f"back to C: cancelling within {BLEED_SETTLE_S + 0.3:.1f} s, not {BLEED_SETTLE_S + BLEED_LISTEN_S:.1f}",
     e.bleed_status() == "ready")
r = run(e, room, 4.0)
test(f"back to C from the room: drone alone reads no pitch ({sum(x is not None for x in r)} readings)",
     all(x is None for x in r))
buf = np.roll(e._ring_buf, -e._ring_pos).copy()
t0 = (e._in_total - e._ring_size) / SR
c_raw, _ = e._bleed_project(buf, t0, [130.81])
dt = t0 + 0.5 * len(buf) / SR - e._bleed_tref
pred = e._bleed_gain[0] * np.exp(1j * e._bleed_slope[0] * dt)
residual_db = 20 * math.log10(abs(c_raw[0] - pred) / (abs(c_raw[0]) + 1e-12) + 1e-12)
test(f"back to C from the room (20 ppm drift, no new listen): fundamental removed by {-residual_db:.1f} dB (gate 20)",
     residual_db < -20)
f = 130.81 * 5 / 4
r = [x for x in run(e, room, 2.0, player_hz=f) if x is not None]
test(f"back to C from the room: just third reads within 2 c ({cents(np.median(r), f):+.2f} c)",
     bool(r) and abs(cents(np.median(r), f)) < 2.0)
print(f"        info: session clock difference learned {e._room_ppm:+.1f} ppm (true 20.0)")
test("learned clock difference within 3 ppm of the truth", abs(e._room_ppm - 20.0) < 3.0)
e.set_drone(voicing="major")                    # C major: 5/4 and 3/2 partials are new
test("C major: the new partials are unknown, the root's are known", not e.room_known())

# A chord change must not click: the first output block crossfades.
e = fresh()
out = np.zeros((OUTPUT_BLOCK, 1), dtype=np.float32)
for _ in range(30):
    e._output_callback(out, OUTPUT_BLOCK, None, None)
prev = out[:, 0].astype(np.float64).copy()
e.set_drone(freq=196.0, voicing="major")
e._output_callback(out, OUTPUT_BLOCK, None, None)
joined = np.concatenate([prev, out[:, 0].astype(np.float64)])
step = np.abs(np.diff(joined))
seam = step[OUTPUT_BLOCK - 1]
typical = float(np.percentile(step[:OUTPUT_BLOCK - 1], 99))
test(f"chord change: the output seam is {seam:.4f}, a normal step is {typical:.4f} (no click)", seam <= 1.5 * typical)
test("the new chord's epoch is the output sample index of that block",
     e._synth["epoch"] == 30 * OUTPUT_BLOCK and e._synth_pending is None)

# ============================================
print("\n--- Note change and sample drone ---")
e = fresh()
room = Room(e)
run(e, room, LISTEN_TOTAL)
e.set_drone(freq=146.83)                        # new root: new partials, must re-listen
test("changing the drone note starts a new listen", e.bleed_status() == "listening")
run(e, room, LISTEN_TOTAL)
r = run(e, room, 3.0)
test(f"after the note change the new drone is cancelled ({sum(x is not None for x in r)} readings)",
     all(x is None for x in r) and e.bleed_status() == "ready")
e.set_drone(on=False)
test("drone off: status off", e.bleed_status() == "off")

e = fresh()
e._drone_sample = np.sin(2 * np.pi * 220 * np.arange(SR) / SR).astype(np.float32)
e._drone_sample_sr = SR
e._drone_sample_freq = 220.0
e._sample_phases = np.zeros(1)
e.set_drone(dtype="sample")
test("sample drone: the notch path, status off (not a known set of partials)",
     e.bleed_status() == "off")

# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
