"""Measure the drone's bleed into a real microphone, and what the drone tab
would read, on this machine's actual devices. Not a test; a measuring tool.

    python tools/measure_bleed.py                   # default mic and speakers
    python tools/measure_bleed.py --input scarlett  # input device by name substring
    python tools/measure_bleed.py --seconds 30 --root 130.81 --volume 0.3

Plays the rich drone through the speakers for --seconds (keep quiet, or
play along after the listen and watch the readings), captures the mic
through the engine's own stream, and reports per partial: level, phase
drift (deg/s, the mic-vs-speaker clock difference), jitter, and how much
of the bleed the engine's cancellation removed; then the pitch readings the
drone tab would have shown, with and without the cancellation. Run it with
the speakers and mic you would actually use.
"""
import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JUSTATUNER_CONFIG_DIR", tempfile.mkdtemp(prefix="jat-measure-"))

import numpy as np  # noqa: E402

from exerciser.engine import AudioEngine  # noqa: E402


def pick_input(name):
    import sounddevice as sd
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and name.lower() in d["name"].lower():
            print(f"input device {i}: {d['name']}")
            return i
    sys.exit(f"no input device matching {name!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="", help="input device name substring (default: system default)")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--root", type=float, default=130.81, help="drone root Hz (C3)")
    ap.add_argument("--volume", type=float, default=0.3)
    args = ap.parse_args()

    e = AudioEngine()
    e._input_device = pick_input(args.input)
    e.monitoring = "speakers"
    blocks, states, reads = [], [], []
    orig = e._push_input

    def spy(data):
        blocks.append(data.astype(np.float64).copy())
        orig(data)
    e._push_input = spy
    e.start()
    if e.input_error:
        sys.exit(f"microphone: {e.input_error}")
    print(f"mic at {e.in_sr} Hz, speakers at {e.sr} Hz; drone root {args.root} Hz rich, {args.seconds:.0f} s. Quiet, please.")
    e.set_drone(on=True, freq=args.root, voicing="root", dtype="rich", volume=args.volume)
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.seconds:
        f, c = e.get_pitch()
        states.append(e.bleed_status())
        reads.append((time.monotonic() - t0, f, c))
        time.sleep(0.08)
    e.set_drone(on=False)
    time.sleep(0.2)
    e.stop()

    x = np.concatenate(blocks)
    sr = e.in_sr
    print(f"\ncaptured {len(x) / sr:.1f} s, rms {20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12):.1f} dBFS")
    freqs = [f for f, _ in e._osc_freqs][:6]
    win = int(0.5 * sr)
    n_win = len(x) // win
    t_all = np.arange(len(x)) / sr
    print(f"{'partial':>8} {'level dBFS':>10} {'drift deg/s':>11} {'jitter deg':>10}")
    for f in freqs:
        ref = np.exp(-2j * np.pi * f * t_all)
        c = np.array([2 * np.mean(x[i * win:(i + 1) * win] * ref[i * win:(i + 1) * win]) for i in range(n_win)])
        ph = np.unwrap(np.angle(c))
        tt = (np.arange(n_win) + 0.5) * 0.5
        slope, icpt = np.polyfit(tt[2:], ph[2:], 1)
        jitter = np.degrees(np.std(ph[2:] - (slope * tt[2:] + icpt)))
        print(f"{f:8.1f} {20 * np.log10(np.mean(np.abs(c[2:])) + 1e-12):10.1f} {np.degrees(slope):11.2f} {jitter:10.2f}")
    ready_t = next((t for (t, _, _), s in zip(reads, states) if s == "ready"), None)
    after = [(t, f, c) for (t, f, c), s in zip(reads, states) if s == "ready"]
    heard = [(round(t, 1), round(f, 1), round(c, 2)) for t, f, c in after if f is not None and c > 0.2]
    print(f"\ncancellation ready after {ready_t and round(ready_t, 1)} s; learned |gain| per partial "
          f"{np.round(np.abs(e._bleed_gain), 4) if e._bleed_gain is not None else None}, "
          f"drift {np.round(np.degrees(e._bleed_slope), 2) if e._bleed_slope is not None else None} deg/s")
    print(f"while cancelling: {len(heard)} of {len(after)} frames reported a pitch "
          f"(with nobody playing this should be 0; a unison here means bleed got through)")
    if heard:
        print("  e.g.", heard[:8])


if __name__ == "__main__":
    main()
