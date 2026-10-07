"""GPU strobe renderer gates: tuner_render API, surface limits, present
mode, and the view's panic-safe fallback to the canvas.

The wheel is a build artifact, not a checkout: a fresh clone and the CI
test runners don't have it, and macOS must never have it (Tk Aqua's
winfo_id() isn't an NSView; wgpu segfaults). Missing is therefore a skip,
not a failure — unless JUSTATUNER_REQUIRE_GPU=1 asks for it (set that on
a machine that has built the wheel to make a broken wheel fail loudly).

On a runner with no GPU surface (Linux without Vulkan) the construction
cases skip on "GPU init failed"; the tab's init-failure fallback is what
runs there, and test_tuner_canvas covers it.

Uses an isolated config profile (JUSTATUNER_CONFIG_DIR) so it never reads
or writes the user's settings.
"""
import builtins
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-gpu-test-")
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s          # main.py installs this; the view needs it

import faulthandler  # noqa: E402
# A GUI suite that hangs must say where: dump every thread's stack to
# stderr and exit after four minutes (a Windows CI runner hung test_tour
# for the runner's whole 600 s with no output, 2026-10-06).
faulthandler.dump_traceback_later(240, exit=True)

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

# An error dialog would block the test forever (exception hook pattern).
messagebox.showerror = lambda *a, **k: print("  (showerror suppressed)", a[:2])
messagebox.showinfo = lambda *a, **k: print("  (showinfo suppressed)", a[:2])

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ============================================================
# 1. tuner_render module import and API
# ============================================================
print("\n--- tuner_render module ---")
try:
    import tuner_render
    _has_gpu = True
    test("tuner_render imports successfully", True)
except ImportError:
    _has_gpu = False
    if sys.platform == "darwin":
        print("  SKIP: tuner_render absent on macOS — canvas-only by design")
    elif os.environ.get("JUSTATUNER_REQUIRE_GPU") == "1":
        test("tuner_render imports successfully (JUSTATUNER_REQUIRE_GPU=1)", False)
    else:
        print("  SKIP: tuner_render not built here; GPU cases skipped (see CLAUDE.md to build it)")

if _has_gpu:
    for m in ['resize', 'set_layout', 'render', 'set_stripe_color',
              'set_faceplate_color', 'adapter_info', 'present_mode']:
        test(f"TunerRenderer has {m}", callable(getattr(tuner_render.TunerRenderer, m, None)))


# ============================================================
# 2. View module flags and the fallback source contract
# ============================================================
print("\n--- tuner.view flags ---")
import tuner.view as tv  # noqa: E402

test("_HAS_GPU_RENDERER matches the import", tv._HAS_GPU_RENDERER == (_has_gpu and sys.platform != "darwin"))
test("GPU_RENDER_FAIL_LIMIT is a positive int", isinstance(tv.GPU_RENDER_FAIL_LIMIT, int) and tv.GPU_RENDER_FAIL_LIMIT > 0)
test("_last_line trims a multi-line panic",
     tv._last_line(RuntimeError("Error in Surface::configure\nInvalid surface")) == "Invalid surface")

view_src = _src("tuner", "view.py")
test("macOS never imports tuner_render (darwin gate)", "if IS_MACOS:\n    _HAS_GPU_RENDERER = False" in view_src)
test("no bare 'except Exception' round the GPU render() call",
     "except BaseException as e:\n                    # A Rust panic" in view_src)
test("resize is guarded", "resize to {w}x{h} failed" in view_src)
test("software adapter (Cpu, or WARP by name) takes the canvas path",
     'if info[2] == "Cpu" or "basic render driver" in info[0].lower():' in view_src)
test("adapter is logged at WARNING", '_log.warning("Tuner GPU renderer: %s via %s (%s), present mode %s"' in view_src)

rs_src = _src("tuner_renderer", "src", "renderer.rs")
test("renderer.rs asks for the adapter's resolution limits", ".using_resolution(adapter.limits())" in rs_src)
test("renderer.rs clamps every configure", rs_src.count("clamp_surface(") >= 3)
test("renderer.rs prefers Mailbox", "wgpu::PresentMode::Mailbox" in rs_src)
test("GpuWheelData compile-time size assert (128 bytes)", "size_of::<GpuWheelData>() == 128" in rs_src)
test("build.py skips tuner_render on macOS", "skipping tuner_render" in _src("build.py"))


# ============================================================
# 3. Surface limits and present mode (needs the wheel and a display)
# ============================================================
print("\n--- Surface limits / present mode ---")
_root = None
try:
    _root = tk.Tk()
except tk.TclError as e:
    print(f"  SKIP: no display ({e})")

if _root is not None and _has_gpu and sys.platform != "darwin":
    _root.geometry("400x300+0+0")
    _f = tk.Frame(_root, width=400, height=300)
    _f.pack(fill="both", expand=True)
    _root.update_idletasks()
    _root.update()
    try:
        _r = tuner_render.TunerRenderer(_f.winfo_id(), 3500, 1500)
        test("Surface 3500x1500 (past the 2048 downlevel cap) constructs", True)
        _info = _r.adapter_info()
        test(f"adapter_info is 3 strings ({_info[0]}, {_info[1]}, {_info[2]})",
             len(_info) == 3 and all(isinstance(x, str) for x in _info))
        _pm = _r.present_mode()
        test(f"present_mode is Mailbox or Fifo ({_pm})", _pm in ("Mailbox", "Fifo"))
        _r.resize(400, 300)
        _r.resize(3500, 1500)
        _r.resize(400, 300)
        test("resize past 2048 and back does not raise", True)
        _r.set_layout([(100.0, 100.0, 40.0, True), (200.0, 200.0, 40.0, False)])
        import time as _time
        _t0 = _time.perf_counter()
        for i in range(60):
            _r.render([[float(i + r) for r in range(7)]] * 12, [0.5] * 12, [[0.5] * 7] * 12, 80.0, 100.0)
        _ms = (_time.perf_counter() - _t0) * 1000 / 60
        test(f"60 frames render ({_ms:.2f} ms/frame, {_pm})", True)
        _r = None
    except BaseException as e:  # noqa: BLE001 — a wgpu panic is a BaseException
        if "GPU init failed" in str(e):
            print("  SKIP: no GPU surface here; surface-limit cases skipped")
        else:
            test(f"big surface / resize raised {type(e).__name__}: {tv._last_line(e)[:70]}", False)
    _root.destroy()
    _root = None
elif _root is not None:
    print("  SKIP: no tuner_render here")
    _root.destroy()
    _root = None


# ============================================================
# 4. Panic-safe fallback on the real app
# ============================================================
print("\n--- Render-failure fallback ---")
try:
    _probe = tk.Tk()
    _probe.destroy()
    _display = True
except tk.TclError:
    _display = False

if _display and tv._HAS_GPU_RENDERER:
    from main import JustATunerApp  # noqa: E402
    _a = JustATunerApp(autostart=False)
    _a.root.withdraw()
    _v = _a.tuner
    if not _v._tuner_use_gpu:
        print("  (tab is not in GPU mode here; skipping fallback cases)")
    else:
        class _FakePanic(BaseException):
            """Stands in for pyo3_runtime.PanicException."""

        # A run of render() failures drops the tab to the canvas — but not
        # a single one, which is just a dropped frame.
        for _ in range(tv.GPU_RENDER_FAIL_LIMIT - 1):
            _v._tuner_gpu_render_failed(_FakePanic("Error in Surface::configure\nInvalid surface"))
        test(f"{tv.GPU_RENDER_FAIL_LIMIT - 1} render failures: still GPU", _v._tuner_use_gpu)
        _v._tuner_gpu_render_failed(_FakePanic("Error in Surface::configure\nInvalid surface"))
        test(f"{tv.GPU_RENDER_FAIL_LIMIT} render failures: switched to canvas",
             not _v._tuner_use_gpu and _v._gpu_renderer is None)
        test("fallback created and packed a canvas",
             _v._tuner_canvas is not None and _v._tuner_canvas.winfo_manager() == "pack")
        test("fallback unpacked the GPU frame", not _v._tuner_gpu_frame.winfo_manager())
        test("fallback shows the CPU-mode notice", hasattr(_v, '_cpu_mode_lbl'))
        test("fallback resets the failure counter", _v._tuner_gpu_fail_count == 0)
        test("render loop would now take the canvas branch", not (_v._tuner_use_gpu and _v._gpu_renderer))
    _a.root.destroy()
else:
    print("  SKIP: " + ("no display" if not _display else "no GPU renderer in the view"))


# ============================================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
