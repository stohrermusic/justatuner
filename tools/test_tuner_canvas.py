"""Drive the Tuner tab end to end on a synthetic tone — no microphone needed.

The engine's `synthetic_hz` replaces the audio stream with a generated
440 Hz tone (plus a -6 dB 2nd harmonic), so the whole tab — tab switch,
engine start, the real `_tuner_animate` loop, StrobeWheel updates, the VU
readout — runs on a machine with no input device. That is what lets the
macOS CI runner exercise the tuner at all; on a dev box it also covers the
canvas path that a GPU machine otherwise never draws.

Three passes:
  0. No microphone (engine.start stubbed to fail): the audio-error text is
     drawn, and is still there after a wheel rebuild (delete("all") used
     to wipe it, so a user with no mic saw dark wheels and no explanation).
  1. Canvas mode (forced by clearing tuner.view._HAS_GPU_RENDERER before
     the app is built): 12 wheels, the A wheel lit and the rest dark,
     readout "A" within 1 cent, no error overlay.
  2. GPU mode, only where the tuner_render wheel is built (never macOS):
     either the renderer is alive with zero render failures, or the tab
     took the designed fallback to the canvas (software adapter, no
     Vulkan) and says so.

Frames run under a real mainloop with a quit timer. A `root.update()` loop
never returns here: a canvas frame outlasts its 16 ms interval, so update()
keeps servicing the already-due reschedule (SSC measured a 25 s stall in
canvas.coords, 2026-10-06).

Self-skips without a display. Uses an isolated config profile
(JUSTATUNER_CONFIG_DIR) so it never reads or writes the user's settings.
"""
import builtins
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROFILE = tempfile.mkdtemp(prefix="jat-tuner-test-")
os.environ["JUSTATUNER_CONFIG_DIR"] = _PROFILE
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s

import faulthandler  # noqa: E402
# A GUI suite that hangs must say where: dump every thread's stack to
# stderr and exit after four minutes (a Windows CI runner hung test_tour
# for the runner's whole 600 s with no output, 2026-10-06).
faulthandler.dump_traceback_later(240, exit=True)

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

# An error dialog would block the mainloop forever (exception hook pattern).
messagebox.showerror = lambda *a, **k: print("  (showerror suppressed)", a[:2])
messagebox.showinfo = lambda *a, **k: print("  (showinfo suppressed)", a[:2])

results = []


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


def _build_app(gpu):
    import tuner.view as tv
    tv._HAS_GPU_RENDERER = gpu
    from main import JustATunerApp
    app = JustATunerApp(autostart=False)
    app.root.state("normal")
    app.root.geometry("1000x720+0+0")
    app.root.update()
    view = app.tuner
    assert getattr(view, "_tuner_engine", None) is not None, "tuner tab not built (audio libs missing?)"
    return app, view


def _run_frames(app, view, seconds=3.0, min_frames=20):
    """Let the tab's real animate loop run under mainloop, then return.

    The GPU renderer's first-use setup can eat the first second, and the
    ring buffer holds the pre-tone silence until the engine has consumed
    four chunks, so the labels are only read once the engine has fed at
    least min_frames chunks (the readout is per frame, not damped)."""
    for _ in range(3):
        app.root.after(int(seconds * 1000), app.root.quit)
        app.root.mainloop()
        if view._tuner_engine._synth_pos >= min_frames * 1024:
            return
    raise AssertionError(f"engine processed only {view._tuner_engine._synth_pos // 1024} frames")


def _readout(view):
    note = view._vu_note_label.cget("text")
    cents_txt = view._vu_cents_label.cget("text")
    cents = None
    for tok in cents_txt.replace("¢", " ").replace("+", " ").split():
        try:
            cents = float(tok)
            break
        except ValueError:
            continue
    return note, cents, cents_txt


def _drive(gpu):
    app, view = _build_app(gpu)
    view._tuner_engine.synthetic_hz = 440.0
    app._on_tab_changed()          # the saved tab is the tuner -> view.start()
    _run_frames(app, view)
    return app, view


def main():
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as e:
        print(f"Skipping: no display available ({e})")
        return 0
    from tuner.engine import AUDIO_AVAILABLE
    if not AUDIO_AVAILABLE:
        print("Skipping: audio libraries not installed (numpy/sounddevice) — the tuner tab is the fallback panel")
        return 0

    print("Tuner tab on a synthetic tone")
    print("=" * 60)
    import tuner.view as tv
    gpu_available = tv._HAS_GPU_RENDERER
    import config
    check("profile override is in effect",
          lambda: os.path.normcase(config.get_config_dir()) == os.path.normcase(_PROFILE))

    # ---- pass 0: no microphone — the error must survive a canvas rebuild ----
    app0, v0 = _build_app(gpu=False)
    v0._tuner_engine.start = lambda device=None: (False, "no microphone (test)")
    app0._on_tab_changed()                           # _tuner_start fails -> error text
    app0.root.after(800, app0.root.quit)
    app0.root.mainloop()

    def no_mic_error_drawn():
        items = v0._tuner_canvas.find_withtag("error")
        assert items, "no audio-error message on the canvas"
        assert "no microphone" in v0._tuner_canvas.itemcget(items[0], "text")
        assert v0._tuner_error_state == ("audio", "no microphone (test)"), v0._tuner_error_state
    check("no-mic: 'Audio error' is drawn and the error state is kept", no_mic_error_drawn)
    v0._tuner_build_wheels()                         # the rebuild that used to wipe it
    app0.root.update_idletasks()

    def no_mic_error_survives_rebuild():
        items = v0._tuner_canvas.find_withtag("error")
        assert items, "audio-error message gone after the canvas rebuild"
        assert "no microphone" in v0._tuner_canvas.itemcget(items[0], "text")
    check("no-mic: 'Audio error' stays on the canvas after a rebuild", no_mic_error_survives_rebuild)
    check("no-mic: MIC lamp dark", lambda: v0._tuner_mic_state[0] == "dark")
    app0.root.destroy()

    # ---- pass 1: canvas ---------------------------------------------
    app, view = _drive(gpu=False)
    check("tuner is running on the synthetic source (no stream opened)",
          lambda: view._tuner_running and view._tuner_engine.is_running and view._tuner_engine._stream is None)
    check("a successful start cleared the error state", lambda: view._tuner_error_state is None)
    check("canvas mode with 12 StrobeWheels",
          lambda: (not view._tuner_use_gpu) and view._tuner_canvas is not None and len(view._tuner_wheels) == 12)
    check("no error overlay on the canvas", lambda: view._tuner_canvas.find_withtag("error") == ())
    check("MIC lamp green (no 'no signal' from the synthetic source)",
          lambda: view._tuner_mic_state == ("green", ""))

    def a_wheel_brightest_far_wheels_dark():
        # A pure tone also lights the two neighbouring wheels dimly (FFT
        # leakage at 10.8 Hz bins); that is how the app looks. The contract
        # is: A clearly brightest, everything not adjacent to A dark.
        b = [float(w._brightness) for w in view._tuner_wheels]
        assert b[9] > 0.5, f"A wheel brightness {b[9]:.2f}"
        others = [x for i, x in enumerate(b) if i != 9]
        assert b[9] >= 2.0 * max(others), f"A not clearly brightest: {[round(x, 2) for x in b]}"
        far = [x for i, x in enumerate(b) if i not in (8, 9, 10)]
        assert max(far) < 0.05, f"a non-adjacent wheel is lit: {[round(x, 2) for x in b]}"
    check("A wheel clearly brightest, non-adjacent wheels dark", a_wheel_brightest_far_wheels_dark)

    def readout_a_in_tune():
        note, cents, raw = _readout(view)
        assert note.rstrip("0123456789") == "A", f"note readout {note!r}"
        # 'IN TUNE' replaces the number inside +-4 c; a number means off by that much.
        assert "IN TUNE" in raw or (cents is not None and abs(cents) < 1.0), f"cents readout {raw!r}"
    check("VU readout says A, in tune", readout_a_in_tune)

    def engine_result_is_a_in_tune():
        r = view._tuner_engine.analyze()
        assert r.magnitudes[9] > 0.5, r.magnitudes
        assert abs(r.cents_errors[9]) < 0.2, r.cents_errors[9]
    check("engine reads A at 0 cents through the live path", engine_result_is_a_in_tune)

    view.stop()
    app.root.update_idletasks()
    check("stops cleanly", lambda: not view._tuner_running)
    app.root.destroy()

    # ---- pass 2: GPU, where the wheel exists --------------------------
    if gpu_available:
        app2, v2 = _drive(gpu=True)
        if v2._tuner_use_gpu:
            info = v2._tuner_gpu_adapter_info()
            print(f"        GPU adapter: {info}, present mode {v2._tuner_gpu_present_mode()}")
            check("GPU mode: renderer alive after the frames",
                  lambda: v2._tuner_use_gpu and v2._gpu_renderer is not None)
            check("GPU mode: zero render failures", lambda: v2._tuner_gpu_fail_count == 0)
        else:
            # CI runners have a software adapter (or no Vulkan): the tab
            # must have dropped to the canvas on purpose and said so.
            check("software adapter / no GPU: fell back to the canvas as designed",
                  lambda: v2._tuner_canvas is not None and len(v2._tuner_wheels) == 12
                  and v2._gpu_renderer is None and hasattr(v2, '_cpu_mode_lbl'))

        def gpu_readout():
            note, cents, raw = _readout(v2)
            assert note.rstrip("0123456789") == "A", (note, raw)
            assert "IN TUNE" in raw or (cents is not None and abs(cents) < 1.0), (note, raw)
        check("GPU build: VU readout says A, in tune", gpu_readout)
        v2.stop()
        app2.root.update_idletasks()
        app2.root.destroy()
    else:
        print("  SKIP  GPU pass: tuner_render not built here" +
              (" (macOS is canvas-only by design)" if sys.platform == "darwin" else ""))

    print("=" * 60)
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
