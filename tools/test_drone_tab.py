"""Drive the Just Intonation Drone tab end to end on a synthetic tone — no
microphone needed.

`AudioEngine.synthetic_hz` replaces the mic with a generated tone (the
same hook the tuner has), so the whole tab — tab switch, engine start, the
real analysis and scope timers, every visualizer mode, the interval panel —
runs on a machine with no input device. The tone is a just major third
(5:4) above the saved root, so the panel must say "Major 3rd", 5:4, LOCKED.

Also gates: the "Phase Wheel" visualizer-mode migration, the transposed
note name, the MIC lamp on the synthetic source, a visualizer-mode cycle
with no Tk callback exception, and save_settings round-tripping the mode.

Frames run under a real mainloop with a quit timer (a root.update() loop
livelocks when a frame outlasts its interval). Self-skips without a
display. Isolated profile via JUSTATUNER_CONFIG_DIR.
"""
import builtins
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROFILE = tempfile.mkdtemp(prefix="jat-drone-test-")
os.environ["JUSTATUNER_CONFIG_DIR"] = _PROFILE
with open(os.path.join(_PROFILE, "app_settings.json"), "w", encoding="utf-8") as _f:
    # A retired mode from an old config, and the drone tab as the saved tab.
    json.dump({"exerciser_settings": {"visualizer_mode": "Phase Wheel", "root_note": 0, "octave": 3},
               "active_tab": "exerciser"}, _f)
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

messagebox.showerror = lambda *a, **k: print("  (showerror suppressed)", a[:2])
messagebox.showinfo = lambda *a, **k: print("  (showinfo suppressed)", a[:2])

results = []
tk_errors = []


def check(name, fn):
    try:
        if fn() is False:
            raise AssertionError("check returned False")
        print(f"  PASS  {name}")
        results.append(True)
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        traceback.print_exc()
        results.append(False)


def _run(app, seconds):
    app.root.after(int(seconds * 1000), app.root.quit)
    app.root.mainloop()


def main():
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as e:
        print(f"Skipping: no display available ({e})")
        return 0
    from exerciser.engine import sd
    if sd is None:
        print("Skipping: sounddevice not installed — the drone engine refuses to start without it")
        return 0

    print("Drone tab on a synthetic tone")
    print("=" * 60)
    from main import JustATunerApp
    from exerciser.intervals import note_freq

    app = JustATunerApp(autostart=False)
    app.root.state("normal")
    app.root.geometry("1000x720+0+0")
    app.root.report_callback_exception = lambda et, ev_, tb: tk_errors.append(
        "".join(traceback.format_exception(et, ev_, tb)))
    app.root.update()
    ex = app.exerciser

    check("retired visualizer mode 'Phase Wheel' migrated to Lissajous",
          lambda: ex.visualizer_mode.get() == "Lissajous")
    check("saved tab (drone) is the initial selection",
          lambda: app.notebook.select() == str(app.exerciser_frame))

    root_hz = note_freq(ex.root_note, ex.octave)          # C3
    tone_hz = root_hz * 5.0 / 4.0                         # just major third
    ex.engine.synthetic_hz = tone_hz
    app._on_tab_changed()                                  # starts the drone tab
    _run(app, 2.5)

    check("drone tab running, tuner stopped",
          lambda: ex._running and ex.engine.running and not app.tuner._tuner_running)
    check("no microphone stream opened, no input error",
          lambda: ex.engine._input_stream is None and ex.engine.input_error is None)
    check(f"engine fed {ex.engine._synth_pos // 4096} blocks of the tone",
          lambda: ex.engine._synth_pos >= 10 * 4096)

    def pitch_within_a_cent():
        f, conf = ex.engine.get_pitch()
        assert f is not None, "no pitch"
        cents = 1200.0 * __import__("math").log2(f / tone_hz)
        assert abs(cents) < 1.0, f"{f:.3f} Hz = {cents:+.2f} c, conf {conf:.2f}"
        assert conf > 0.5, f"confidence {conf:.2f}"
    check(f"YIN reads the tone within 1 c ({tone_hz:.2f} Hz)", pitch_within_a_cent)

    check("interval panel says Major 3rd", lambda: ex.interval_label.cget("text") == "Major 3rd")
    check("ratio 5:4", lambda: ex.interval_ratio.cget("text") == "5:4" and ex.ratio_label.cget("text") == "5:4")
    check("LOCKED (within 5 c of just)", lambda: "LOCKED" in ex.lock_label.cget("text"))
    check("played label names E3 at the tone's frequency",
          lambda: ex.played_label.cget("text").startswith("Playing: E3") and f"{tone_hz:.1f} Hz" in ex.played_label.cget("text"))
    check("ET difference line says JI M3 is -13.7 c from ET",
          lambda: ex.et_label.cget("text") == "JI M3 is -13.7¢ from ET")
    check("MIC lamp green on the synthetic source", lambda: ex._mic_state == ("green", ""))

    # Transposition: a Bb instrument reads concert E as written F#.
    ex.transposition = "Bb"
    _run(app, 0.3)
    check("Bb transposition shows the written note F#3",
          lambda: ex.played_label.cget("text").startswith("Playing: F#3"))
    ex.transposition = "Concert (C)"

    # Every visualizer mode draws for half a second without a Tk error.
    for mode in ex._available_modes:
        ex.visualizer_mode.set(mode)
        ex._on_visualizer_mode_changed()
        before = len(tk_errors)
        _run(app, 0.6)
        check(f"visualizer {mode}: frames drawn, no callback exception, scope has items",
              lambda m=mode, b=before: len(tk_errors) == b and len(ex.scope.find_all()) > 0)

    # Switching back to the tuner stops the drone.
    app.notebook.select(app.tuner_frame)
    _run(app, 0.5)
    check("switching tabs stops the drone engine", lambda: not ex._running and not ex.engine.running)

    ex.visualizer_mode.set("Spectrum")
    ex.save_settings()
    check("save_settings records the visualizer mode and root",
          lambda: app.settings["exerciser_settings"]["visualizer_mode"] == "Spectrum"
          and app.settings["exerciser_settings"]["root_note"] == 0)
    check("no Tk callback exceptions during the run", lambda: not tk_errors)
    if tk_errors:
        print(tk_errors[0])
    app.tuner.stop()
    app.root.destroy()

    print("=" * 60)
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
