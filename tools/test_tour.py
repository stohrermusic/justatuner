"""The screenshot tour as a gate, and the dialogs it opens.

`run_tour(app, shots_dir=None)` walks every stop on the live app with
screenshots off, so every tab and dialog is constructed and torn down on
every platform in CI, and anything that raised lands in the error list.
Then the two dialogs the tour cannot inspect from a picture: Tuner
Settings must open (its imports are lazy, and two releases shipped with it
raising ImportError) with the input-device box reading "System Default",
and the latency dialog must open and close without starting a test.

Both tabs run on synthetic tones. Self-skips without a display; isolated
profile via JUSTATUNER_CONFIG_DIR.
"""
import builtins
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-tour-test-")
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


def _toplevels(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def _widgets(w, cls):
    out = []
    for c in w.winfo_children():
        out += _widgets(c, cls)
        if c.winfo_class() == cls:
            out.append(c)
    return out


def main():
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as e:
        print(f"Skipping: no display available ({e})")
        return 0
    from tuner.engine import AUDIO_AVAILABLE
    if not AUDIO_AVAILABLE:
        print("Skipping: audio libraries not installed")
        return 0

    print("Tour as a gate, and the dialogs")
    print("=" * 60)
    from main import JustATunerApp, run_tour

    app = JustATunerApp(autostart=False)
    app.root.state("normal")
    app.root.geometry("1000x720+0+0")
    tk_errors = []
    app.root.report_callback_exception = lambda et, ev, tb: tk_errors.append(
        "".join(traceback.format_exception(et, ev, tb)))
    app.root.update()

    # ---- the whole tour, screenshots off, fast steps ----
    done = {}
    log, errors = run_tour(app, shots_dir=None, step_ms=400,
                           on_done=lambda: done.setdefault("yes", app.root.quit()))
    app.root.after(60000, app.root.quit)        # safety net
    app.root.mainloop()
    check("tour finished", lambda: "yes" in done)
    check(f"tour visited all 12 stops ({len(log)})", lambda: len(log) == 12)
    check(f"tour raised nothing ({errors})", lambda: not errors)
    check("no Tk callback exception during the tour", lambda: not tk_errors)
    if tk_errors:
        print(tk_errors[0])
    check("tour left no dialog open", lambda: not _toplevels(app.root))
    check("tour stopped both engines", lambda: not app.tuner._tuner_running and not app.exerciser._running)

    # ---- Tuner Settings: lazy imports, the device box, a change applies ----
    app.notebook.select(app.tuner_frame)
    app.tuner._tuner_engine.synthetic_hz = 440.0
    app._on_tab_changed()
    app.root.update()
    app.tuner._tuner_open_settings()
    app.root.update()
    dlg = [w for w in _toplevels(app.root) if w.title() == "Tuner Settings"]
    check("Tuner > Settings... opens a 'Tuner Settings' window (lazy imports resolved)", lambda: len(dlg) == 1)
    if dlg:
        combos = _widgets(dlg[0], "TCombobox")
        check("input-device box reads 'System Default' (StringVar kept alive)",
              lambda: combos and combos[0].get() == "System Default")
        check("dialog opened over the app, not at the screen corner",
              lambda: dlg[0].winfo_rootx() >= app.root.winfo_rootx() and dlg[0].winfo_rooty() >= app.root.winfo_rooty())
        checks = _widgets(dlg[0], "Checkbutton")
        check("the FPS checkbox toggles show_fps",
              lambda: checks and (checks[0].invoke() or app.tuner._tuner_show_fps.get() is True))
        dlg[0].destroy()
    app.root.update()

    # ---- latency dialog opens and closes without running ----
    app._open_latency_test()
    app.root.update()
    lat = [w for w in _toplevels(app.root) if w.title() == "Audio Latency Test"]
    check("Help > Test Audio Latency... opens its dialog", lambda: len(lat) == 1)
    check("a second open just raises the same dialog",
          lambda: (app._open_latency_test() or True) and len([w for w in _toplevels(app.root) if w.title() == "Audio Latency Test"]) == 1)
    if lat:
        lat[0].destroy()
        app.root.update()
    check("closing it clears the handle", lambda: app._latency_dialog is None)
    check("tuner still running on its tone after the dialogs", lambda: app.tuner._tuner_running)

    app.tuner.stop()
    app.root.destroy()
    print("=" * 60)
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
