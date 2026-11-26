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

Which way the stripes travel is read from the picture itself in both
passes: the canvas items' own coordinates in pass 1, screen pixels of the
live GPU surface in pass 2. A sharp note drifts right in all twelve windows.

Then two start-up cases: a hand-edited reference pitch that is not a number,
and (in a child interpreter) an audio library that fails to start.

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


# ---------------------------------------------------------------------
# Which way the stripes travel (2026-11-25)
# ---------------------------------------------------------------------
# The engine RAISES a wheel's phase for a sharp note (test_tuner_engine).
# The rule, from the picture: while the phase rises, the stripes in the
# middle of every one of the twelve windows travel to the RIGHT.
MEASURED_RING = 3          # 32 segments: 22.5 degrees per stripe pair
PHASE_STEP = 3.0           # degrees; well under half a stripe pair


def _all_wheels(phase_deg):
    """Stand-in for engine.analyze: every wheel lit, every phase at phase_deg."""
    from tuner.engine import TunerResult, NUM_RINGS

    def analyze():
        r = TunerResult()
        r.magnitudes = [10.0] * 12
        r.active = [True] * 12
        r.phase_offsets = [phase_deg] * 12
        r.ring_magnitudes = [[10.0] * NUM_RINGS for _ in range(12)]
        r.ring_phase_offsets = [[phase_deg] * NUM_RINGS for _ in range(12)]
        return r
    return analyze


def _show_phase(app, view, phase_deg, drawn):
    """Run the tab's own animate loop until it has drawn phase_deg."""
    view._tuner_engine.analyze = _all_wheels(phase_deg)
    for _ in range(20):
        app.root.after(150, app.root.quit)
        app.root.mainloop()
        if drawn():
            return
    raise AssertionError(f"the tab never drew phase {phase_deg}")


def _canvas_stripes(view):
    """{pitch class: {polygon id: x}} for the stripes of one ring that sit in
    the middle of that wheel's window, from the canvas's own coordinates."""
    import math
    out = {}
    c = view._tuner_canvas
    for pc, wheel in enumerate(view._tuner_wheels):
        xs = {}
        for poly_id, _base, _span, _steps in wheel._segments[MEASURED_RING]:
            xy = c.coords(poly_id)
            x, y = sum(xy[0::2]) / (len(xy) / 2), sum(xy[1::2]) / (len(xy) / 2)
            ang = math.degrees(math.atan2(-(y - wheel.cy), x - wheel.cx))     # counter-clockwise from east
            if abs((ang - wheel._wedge_center + 180.0) % 360.0 - 180.0) < 20.0:
                xs[poly_id] = x
        out[pc] = xs
    return out


def _canvas_travel(app, view, p0, p1):
    """Mean x travel (px) of the stripes in each window as the phase goes p0 -> p1."""
    def drawn(p):
        return lambda: all(abs(abs(w._last_ring_phases[MEASURED_RING]) - p) < 1e-6 for w in view._tuner_wheels)
    _show_phase(app, view, p0, drawn(p0))
    a = _canvas_stripes(view)
    _show_phase(app, view, p1, drawn(p1))
    b = _canvas_stripes(view)
    travel = {}
    for pc in range(12):
        dxs = [b[pc][i] - a[pc][i] for i in a[pc] if i in b[pc]]
        assert dxs, f"no stripe of ring {MEASURED_RING} in the window of pitch class {pc}"
        assert len({d > 0 for d in dxs}) == 1, f"pitch class {pc}: stripes in one window travel both ways {dxs}"
        travel[pc] = sum(dxs) / len(dxs)
    return travel


def _screen_ring(img, scale, ox, oy, cx, cy, radius, centre_deg):
    """Green level along one ring, 0.1 degree steps over +-30 degrees round the
    window's centre; the angle is clockwise from the top OF THE SCREEN."""
    import math
    import tuner.view as tv
    gap = radius * tv.CENTER_GAP_FRACTION
    r = gap + (MEASURED_RING + 0.5) * (radius - gap) / tv.NUM_RINGS
    out = []
    for k in range(-300, 301):
        th = math.radians(centre_deg + k * 0.1)
        x = (ox + cx + r * math.sin(th)) * scale
        y = (oy + cy - r * math.cos(th)) * scale
        out.append(img.getpixel((int(round(x)), int(round(y))))[1])
    return out


def _clockwise_turn(a, b):
    """How far (degrees, clockwise on screen) profile b is profile a turned."""
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    best = None
    for lag in range(-80, 81):
        s = n = 0
        for i in range(len(a)):
            j = i + lag
            if 0 <= j < len(b):
                s += (a[i] - ma) * (b[j] - mb)
                n += 1
        if best is None or s / n > best[0]:
            best = (s / n, lag)
    return best[1] * 0.1


def _gpu_travel(app, view, p0, p1):
    """{pitch class: travel to the right, in degrees of turn} read from screen
    pixels of the live GPU surface, or a string saying why the screen could
    not be read."""
    try:
        from PIL import ImageGrab
    except ImportError as e:
        return f"Pillow's ImageGrab is not available ({e})"
    frame = view._tuner_gpu_frame
    layout = view._tuner_compute_layout(frame.winfo_width(), frame.winfo_height())
    app.root.lift()
    app.root.attributes("-topmost", True)
    shots = []
    try:
        for p in (p0, p1):
            _show_phase(app, view, p, lambda: view._tuner_gpu_fail_count == 0)
            try:
                shots.append(ImageGrab.grab())
            except Exception as e:  # noqa: BLE001 — no screen to grab is a skip, said out loud
                return f"the screen could not be grabbed ({e})"
    finally:
        app.root.attributes("-topmost", False)
    # Tk reports logical pixels, a grab is physical (the 250 % laptop).
    scale = shots[0].width / app.root.winfo_screenwidth()
    ox, oy = frame.winfo_rootx(), frame.winfo_rooty()
    travel = {}
    for pc, cx, cy, radius, is_up in layout:
        centre = 0.0 if is_up else 180.0
        a = _screen_ring(shots[0], scale, ox, oy, cx, cy, radius, centre)
        b = _screen_ring(shots[1], scale, ox, oy, cx, cy, radius, centre)
        if max(a) - min(a) < 60:
            return f"no stripes on screen in the window of pitch class {pc} (is the app's window covered?)"
        cw = _clockwise_turn(a, b)
        travel[pc] = cw if is_up else -cw      # clockwise is rightward at the top of a disc, leftward at the bottom
    return travel


def _loop_rate(app, view, seconds=2.0):
    """(median fps, mean fps, mean ms a frame keeps Tk busy) of the tab's own
    animate loop, timed round the real method. Busy is the frame's work plus
    the redraws Tk does for it afterwards as idle work, which on the canvas
    path is most of the cost."""
    import time
    stamps, work = [], []
    real = view._tuner_animate
    idle = {"pending": False}

    def idle_ran():
        idle["pending"] = False
        work.append(time.perf_counter() - stamps[-1])

    def timed():
        stamps.append(time.perf_counter())
        # Every frame's redraws must run before the next frame starts,
        # however short the wait the pacer hands back.
        assert not idle["pending"], "a frame started before Tk reached the last frame's idle work (redraws starved)"
        idle["pending"] = True
        real()
        app.root.after_idle(idle_ran)       # queued behind this frame's redraws
    view._tuner_animate = timed
    app.root.after(int(seconds * 1000), app.root.quit)
    app.root.mainloop()
    view.__dict__.pop("_tuner_animate", None)
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    assert len(gaps) >= 5, f"only {len(stamps)} frames in {seconds} s"
    # The median frame, not the mean: one stall (a screen grab just before,
    # another program) is not the loop's pace.
    return 1.0 / gaps[len(gaps) // 2], len(gaps) / sum(gaps), 1000.0 * sum(work) / len(work)


def _check_loop_rate(label, app, view):
    """The 60 setting gives 60 frames a second wherever a frame leaves room
    for it (2026-11-25: it gave 32 on Windows). Where a frame keeps Tk busy
    for over 85 % of the period (the canvas renderer, a slow CI runner) the rate
    is printed, not judged."""
    view._tuner_fps_var.set("60")
    _run_frames(app, view, seconds=0.5, min_frames=0)
    fps, mean_fps, work_ms = _loop_rate(app, view)
    if work_ms > 0.85 * 1000.0 / 60.0:
        print(f"  SKIP  {label}: {mean_fps:.0f} fps on the 60 setting with Tk busy {work_ms:.1f} ms per frame "
              f"(over 85 % of the 16.7 ms period: the loop cannot keep up here)")
        return
    check(f"{label}: the 60 setting runs at 60 frames a second (median frame {fps:.1f} fps, mean {mean_fps:.1f}, "
          f"Tk busy {work_ms:.1f} ms per frame)", lambda: 55.0 <= fps <= 65.0)


def _wrong_way(travel, want_right):
    import tuner.view as tv
    return [tv.PITCH_CLASSES[pc] for pc in sorted(travel) if (travel[pc] > 0) != want_right]


# A child interpreter whose sounddevice raises PortAudioError at import, as it
# does on a machine whose sound system will not start. %r is the repo root.
PORTAUDIO_FAILS = r"""
import builtins, importlib.abc, importlib.machinery, os, sys, tempfile
sys.path.insert(0, %r)
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-noaudio-")
builtins._ = lambda s: s

class Boom(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path, target=None):
        if name == "sounddevice":
            return importlib.machinery.ModuleSpec(name, self)
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        class PortAudioError(Exception):
            pass
        raise PortAudioError("Error initializing PortAudio: Unanticipated host error")

sys.meta_path.insert(0, Boom())
import tkinter as tk
from tkinter import messagebox
messagebox.showerror = messagebox.showinfo = messagebox.showwarning = lambda *a, **k: print("BOX", a[:2])
import main
app = main.JustATunerApp(autostart=False)
errors = []
app.root.report_callback_exception = lambda et, ev, tb: errors.append(repr(ev))
app.root.state("normal")
app._on_tab_changed()
app.root.after(400, app.root.quit); app.root.mainloop()

def texts(w):
    out = []
    for c in w.winfo_children():
        if c.winfo_class() == "Label":
            out.append(str(c.cget("text")))
        out += texts(c)
    return out

print("TUNER", " | ".join(texts(app.tuner_frame)).replace(chr(10), " "))
app.notebook.select(app.exerciser_frame)
app.root.after(600, app.root.quit); app.root.mainloop()
print("DRONE", app.exerciser.engine.input_error)
print("ERRORS", errors)
app.exerciser.stop()
app.root.destroy()
print("BUILT")
"""


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

    def canvas_sharp_right():
        t = _canvas_travel(app, view, 20.0, 20.0 + PHASE_STEP)
        wrong = _wrong_way(t, True)
        assert not wrong, f"a sharp note's stripes travel LEFT in the windows of {wrong}"
    check("canvas: a sharp note's stripes travel RIGHT in all twelve windows", canvas_sharp_right)

    def canvas_flat_left():
        t = _canvas_travel(app, view, 20.0 + PHASE_STEP, 20.0)
        wrong = _wrong_way(t, False)
        assert not wrong, f"a flat note's stripes travel RIGHT in the windows of {wrong}"
    check("canvas: a flat note's stripes travel LEFT in all twelve windows", canvas_flat_left)
    view._tuner_engine.__dict__.pop("analyze", None)      # the engine's own analyze again

    def one_rule_for_both_renderers():
        import inspect
        layout = tv.TunerView._tuner_compute_layout(None, 900, 500)
        bottom = {pc for pc, _cx, _cy, _r, is_up in layout if not is_up}
        assert bottom == set(tv.BOTTOM_ROW_PITCH_CLASSES), bottom
        phases = [10.0, -20.0, 0.0, 3.5, 4.0, 5.0, 6.0]
        for pc in range(12):
            want = [-p for p in phases] if pc in bottom else phases
            assert tv.window_phases(pc, list(phases)) == want, pc
        src = inspect.getsource(tv.TunerView._tuner_animate)
        assert src.count("window_phases(i, ") == 3, src.count("window_phases(i, ")
        assert "ring_phases.append(list(result.ring_phase_offsets[i]))" not in src, "the GPU path sends raw phases"
        assert "rp = list(result.ring_phase_offsets[i])" not in src, "the canvas path sends raw phases"
    check("both renderers take their phases through window_phases; the bottom row's discs turn the other way",
          one_rule_for_both_renderers)
    _check_loop_rate("canvas", app, view)

    view.stop()
    app.root.update_idletasks()
    check("stops cleanly", lambda: not view._tuner_running)
    app.root.destroy()

    # ---- frame pacing: the pacer on a fake clock, then on a real Tk timer ----
    def pacer_on_a_fake_clock():
        p = tv.FramePacer()
        period = 1.0 / 60.0
        # a frame whose work ended 4 ms after its start: wait the rest of the period, not a fixed 16 ms
        assert p.next_delay_ms(period, now=10.000) == 17              # first frame: a full period from now
        assert p.next_delay_ms(period, now=10.0167 + 0.004) == 13, "the work was not taken off the wait"
        assert p.next_delay_ms(period, now=10.0333 + 0.012) == 5
        # a frame that overran (20 ms): the next follows at once, on the 1 ms floor, never 0
        assert p.next_delay_ms(period, now=10.0500 + 0.020) == 1
        # far behind (a stall): one frame at once, then the period again; no burst of catch-up frames
        assert p.next_delay_ms(period, now=10.500) == 1
        assert p.next_delay_ms(period, now=10.501 + 0.004) == 12
        total = 0.0
        p.reset()
        t = 0.0
        for _ in range(600):                                           # ten seconds of 4 ms frames, whole-ms waits
            t += 0.004
            d = p.next_delay_ms(period, now=t)
            t += d / 1000.0
            total = t
        assert abs(600 / total - 60.0) < 0.2, f"{600 / total:.2f} fps over ten simulated seconds"
    check("FramePacer: the wait is the period less the work, never 0, no catch-up burst, 60.0 fps over 600 frames",
          pacer_on_a_fake_clock)

    def pacer_on_a_real_timer():
        import time
        # In a window that is on screen, as the tuner is when anyone is
        # watching it. With the root withdrawn this measured what the system
        # does to an app with nothing visible: the Mac runner gave it coarse
        # timers (median frame 64.0 fps, 2026-11-25) while the tab itself, in
        # a visible window on the same runner, held 60; this PC did the same
        # in 3 runs of 3 that afternoon after passing all morning (Windows 11
        # does not promise a hidden process its timer resolution).
        root = tk.Tk()
        root.title("frame pacing check")
        root.geometry("260x60+30+30")
        root.update()
        holds_before = tv._fine_timer_holds
        held = tv.fine_timer(True)
        pacer, stamps = tv.FramePacer(), []

        def frame():
            stamps.append(time.perf_counter())
            while time.perf_counter() - stamps[-1] < 0.004:            # 4 ms of work, as the GPU tab does
                pass
            root.after(pacer.next_delay_ms(1.0 / 60.0), frame)
        frame()
        root.after(2000, root.quit)
        root.mainloop()
        root.destroy()
        tv.fine_timer(False)
        assert held == (sys.platform == "win32"), held
        assert tv._fine_timer_holds == holds_before, (tv._fine_timer_holds, holds_before)
        gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
        fps = 1.0 / gaps[len(gaps) // 2]
        assert 57.0 <= fps <= 63.0, f"median frame {fps:.1f} fps (worst frame {1000 * gaps[-1]:.0f} ms)"
    check("a Tk loop paced by FramePacer under fine_timer runs 4 ms frames at 60 a second; the timer hold is released",
          pacer_on_a_real_timer)

    # ---- pass 2: GPU, where the wheel exists --------------------------
    if gpu_available:
        app2, v2 = _drive(gpu=True)
        if v2._tuner_use_gpu:
            info = v2._tuner_gpu_adapter_info()
            print(f"        GPU adapter: {info}, present mode {v2._tuner_gpu_present_mode()}")
            check("GPU mode: renderer alive after the frames",
                  lambda: v2._tuner_use_gpu and v2._gpu_renderer is not None)
            check("GPU mode: zero render failures", lambda: v2._tuner_gpu_fail_count == 0)
            t = _gpu_travel(app2, v2, 20.0, 20.0 + PHASE_STEP)
            v2._tuner_engine.__dict__.pop("analyze", None)      # the engine's own analyze again
            if isinstance(t, str) and os.environ.get("JUSTATUNER_REQUIRE_GPU") != "1":
                print(f"  SKIP  GPU: stripe travel from screen pixels: {t}")
            else:
                def gpu_sharp_right():
                    assert not isinstance(t, str), t
                    wrong = _wrong_way(t, True)
                    assert not wrong, f"a sharp note's stripes travel LEFT in the windows of {wrong}"
                    off = {tv.PITCH_CLASSES[pc]: round(v, 1) for pc, v in t.items() if abs(abs(v) - PHASE_STEP) > 1.0}
                    assert not off, f"the picture did not turn by the {PHASE_STEP} degrees it was given: {off}"
                check("GPU, from screen pixels: a sharp note's stripes travel RIGHT in all twelve windows",
                      gpu_sharp_right)
                _run_frames(app2, v2, seconds=1.0)               # back on the tone for the readout below
            _check_loop_rate("GPU", app2, v2)
            check("the 1 ms timer tick is held while the tuner runs (Windows) and by nothing else",
                  lambda: tv._fine_timer_holds == (1 if sys.platform == "win32" else 0))
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

    # ---- a hand-edited reference pitch that is not a number -----------
    import json
    settings_path = os.path.join(_PROFILE, "app_settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({"tuner_settings": {"reference_pitch": "abc"}}, f)
    built = {}

    def bad_pitch_builds():
        built["app"], v = _build_app(gpu=False)
        assert v._tuner_engine.reference_pitch == 440.0, v._tuner_engine.reference_pitch
        assert float(v._tuner_pitch_var.get()) == 440.0
        v._tuner_on_pitch_changed()
        v.save_settings()
        assert built["app"].settings["tuner_settings"]["reference_pitch"] == 440.0
    check('reference_pitch "abc" in the settings file: the tab builds at A = 440', bad_pitch_builds)
    if built.get("app") is not None:
        built["app"].root.destroy()
    os.remove(settings_path)

    # ---- the audio library fails to start (child interpreter) ----------
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = subprocess.run([sys.executable, "-c", PORTAUDIO_FAILS % repo], cwd=repo,
                           capture_output=True, text=True, timeout=120)
    out = child.stdout.splitlines()

    def line(prefix):
        return next((ln for ln in out if ln.startswith(prefix)), "")
    check(f"PortAudio will not start: the app still builds and both tabs open "
          f"({line('BUILT') or child.stderr.strip()[-160:]})",
          lambda: child.returncode == 0 and "BUILT" in out and line("ERRORS") == "ERRORS []")
    check(f"the tuner tab says why ({line('TUNER')[:110]})",
          lambda: "Error initializing PortAudio" in line("TUNER"))
    check(f"the drone tab's MIC line says why ({line('DRONE')[:110]})",
          lambda: "Error initializing PortAudio" in line("DRONE"))

    print("=" * 60)
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
