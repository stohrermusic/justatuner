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
import time
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

import faulthandler  # noqa: E402
# A GUI suite that hangs must say where: dump every thread's stack to
# stderr and exit after four minutes (a Windows CI runner hung test_tour
# for the runner's whole 600 s with no output, 2026-10-06).
faulthandler.dump_traceback_later(240, exit=True)

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

    # ---- a progression on the synthetic tone --------------------------
    # The tone stays E3; the root moves C -> F -> G -> C, so the interval
    # read against it must go Major 3rd -> Major 7th -> Major 6th -> Major 3rd.
    from exerciser.progression import PRESETS, Progression
    ex.monitoring.set("headphones")
    ex._on_monitoring_changed()
    prog = Progression("test", PRESETS[0].steps, mode="seconds")
    for s in prog.steps:
        s.length = 0.7
    app.notebook.select(app.exerciser_frame)
    _run(app, 0.3)
    ex._prog_use(prog)
    check("the transport shows the chosen progression while idle",
          lambda: "test" in ex.prog_label.cget("text") and "4 chords" in ex.prog_label.cget("text"))
    ex._prog_start()
    check("start turns the drone on and the button says Stop",
          lambda: ex.drone_on and ex.engine.drone_on and "Stop" in ex.prog_btn.cget("text"))
    check("count-in first (headphones: no listen)", lambda: ex._player.state == "countin" and "Count-in" in ex.prog_label.cget("text"))
    seen = []
    deadline = time.monotonic() + 2.0 + 4 * 0.7 + 1.0
    while time.monotonic() < deadline:
        _run(app, 0.15)
        name = ex.interval_label.cget("text")
        if name != "- - -" and (not seen or seen[-1] != name):
            seen.append(name)
    check(f"interval names follow the roots: {seen}",
          lambda: seen[:4] == ["Major 3rd", "Major 7th", "Major 6th", "Major 3rd"])
    check("root buttons follow the progression", lambda: ex.root_note in (0, 5, 7))
    check("the transport shows current and next chord with time left",
          lambda: "next" in ex.prog_label.cget("text") and "s" in ex.prog_label.cget("text"))
    ex._prog_stop()
    check("stop: button back to Start, drone still on", lambda: "Start" in ex.prog_btn.cget("text") and ex.drone_on)

    # Manual mode: the key advances, typing in an Entry does not.
    manual = Progression("manual", PRESETS[0].steps, mode="manual")
    ex._prog_use(manual)
    ex._prog_start()
    _run(app, 0.2)
    check("manual: playing at once on C", lambda: ex._player.state == "playing" and ex.root_note == 0)
    ex.root.event_generate("<KeyPress-space>")
    _run(app, 0.2)
    check("manual: the space key advances to F", lambda: ex.root_note == 5)
    entry = tk.Entry(ex.root)
    entry.pack()
    entry.focus_set()
    _run(app, 0.1)
    entry.event_generate("<KeyPress-space>")
    _run(app, 0.2)
    check("manual: a space typed into a text field does not advance", lambda: ex.root_note == 5)
    entry.destroy()
    ex._prog_next()
    check("Next button advances to G", lambda: ex.root_note == 7)
    ex._set_drone(False)
    check("switching the drone off stops the progression", lambda: ex._player is None)
    ex.save_settings()
    check("save_settings keeps the progression and the key",
          lambda: app.settings["exerciser_settings"]["progression"]["name"] == "manual"
          and app.settings["exerciser_settings"]["advance_key"] == "space")

    # Switching back to the tuner stops the drone.
    app.notebook.select(app.tuner_frame)
    _run(app, 0.5)
    check("switching tabs stops the drone engine", lambda: not ex._running and not ex.engine.running)

    ex.visualizer_mode.set("Spectrum")
    ex.save_settings()
    check("save_settings records the visualizer mode and root",
          lambda: app.settings["exerciser_settings"]["visualizer_mode"] == "Spectrum"
          and app.settings["exerciser_settings"]["root_note"] == 7)   # the progression left it on G
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
