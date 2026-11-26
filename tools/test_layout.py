"""Nothing on either tab is cut off at the window sizes real screens give.

The control bar of the tuner tab was three equal thirds, so its left group
overflowed below about 1070 px of window while the middle third had 190 px
to spare; the drone tab's round scope asked for a fixed 380 px, so on a
short window the rows under it (the root buttons, the DRONE and MIC lines)
were squeezed instead of the picture; and the window's minimum size
(960x620) was a guess smaller than either tab needed (Matt, 2026-11-25:
"when run in a smaller window, controls get cut off").

A maximised window is about 1280x621 on a 1920x1080 laptop at 150 % scaling
and about 1366x669 on a 1366x768 one (screen less taskbar, title bar and
menu). The suite sets those sizes, and the app's own minimum, and walks
every widget of both tabs: none may stick out of its parent, and none may be
given less than it asks for. Only the wheel area is allowed to give.

No engine is started (the tab-change handler is unbound). Self-skips without
a display; sizes that do not fit this screen are printed, not judged. Uses an
isolated config profile (JUSTATUNER_CONFIG_DIR).
"""
import builtins
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-layout-test-")
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s

import faulthandler  # noqa: E402
faulthandler.dump_traceback_later(240, exit=True)

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

messagebox.showerror = lambda *a, **k: print("  (showerror suppressed)", a[:2])
messagebox.showinfo = lambda *a, **k: print("  (showinfo suppressed)", a[:2])

results = []

# Maximised windows on two common laptops (logical pixels).
LAPTOPS = [("1920x1080 at 150 %", 1280, 621), ("1366x768", 1366, 669)]


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


def _name(w):
    try:
        t = w.cget("text")
    except tk.TclError:
        t = ""
    return f"{w.winfo_class()}{' ' + ascii(str(t)[:16]) if t else ''}"


def _cut_off(w, out, path=""):
    """Every widget under w that sticks out of its parent or is given less
    than it asks for (more than 1 px either way)."""
    pw, ph = w.winfo_width(), w.winfo_height()
    for c in w.winfo_children():
        if not c.winfo_ismapped() or c.winfo_class() in ("Toplevel", "Menu"):
            continue
        if getattr(c, "_layout_elastic", False):
            continue
        here = f"{path}/{_name(c)}"
        over_x = c.winfo_x() + c.winfo_width() - pw
        over_y = c.winfo_y() + c.winfo_height() - ph
        short_x = c.winfo_reqwidth() - c.winfo_width()
        short_y = c.winfo_reqheight() - c.winfo_height()
        if over_x > 1 or over_y > 1:
            out.append(f"{here} sticks out {max(over_x, 0)} px across, {max(over_y, 0)} px down")
        elif (short_x > 1 or short_y > 1) and not c.winfo_children():
            out.append(f"{here} squeezed {max(short_x, 0)} px across, {max(short_y, 0)} px down")
        _cut_off(c, out, here)


def main():
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as e:
        print(f"Skipping: no display available ({e})")
        return 0
    from tuner.engine import AUDIO_AVAILABLE
    if not AUDIO_AVAILABLE:
        print("Skipping: audio libraries not installed (the tuner tab is the fallback panel)")
        return 0

    print("Nothing cut off at real window sizes")
    print("=" * 60)
    import exerciser.view as ev
    from main import JustATunerApp

    app = JustATunerApp(autostart=False)
    app.notebook.unbind("<<NotebookTabChanged>>")        # layout only: start nothing
    root, tuner, ex = app.root, app.tuner, app.exerciser
    root.state("normal")
    for attr in ("_tuner_gpu_frame", "_tuner_canvas"):   # the wheels stretch and shrink by design
        w = getattr(tuner, attr, None)
        if w is not None:
            w._layout_elastic = True
    root.update()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    min_w, min_h = root.minsize()
    print(f"        screen {sw}x{sh}; the window's minimum size is {min_w}x{min_h}")

    def at(w, h):
        root.geometry(f"{w}x{h}+0+0")
        cut = {}
        for label, frame in (("tuner", app.tuner_frame), ("drone", app.exerciser_frame)):
            app.notebook.select(frame)
            for _ in range(4):                           # a resize settles over a few passes
                root.update()
            out = []
            _cut_off(frame, out)
            cut[label] = out
        return cut

    def nothing_cut(w, h):
        cut = at(w, h)
        got = (root.winfo_width(), root.winfo_height())
        assert got == (w, h), f"asked for {w}x{h}, the window is {got[0]}x{got[1]}"
        for label in ("tuner", "drone"):
            assert not cut[label], (f"{label} tab at {w}x{h}: {len(cut[label])} cut off, first "
                                    f"{cut[label][0].rsplit('/', 2)[-2:]}")

    check(f"at the window's own minimum size ({min_w}x{min_h}) nothing on either tab is cut off",
          lambda: nothing_cut(min_w, min_h))
    for label, w, h in LAPTOPS:
        if w > sw or h > sh - 60:
            print(f"  SKIP  {label}: a {w}x{h} window does not fit this {sw}x{sh} screen")
            continue
        check(f"maximised on a {label} laptop ({w}x{h}): nothing on either tab is cut off",
              lambda w=w, h=h: nothing_cut(w, h))
    check(f"the minimum size fits both of those laptops ({min_w}x{min_h} within 1280x621)",
          lambda: min_w <= 1280 and min_h <= 621)

    def minimum_is_what_the_tabs_ask():
        at(min_w, min_h)
        need_w = max(app.tuner_frame.winfo_reqwidth(), app.exerciser_frame.winfo_reqwidth())
        assert min_w >= need_w, f"minimum width {min_w} is under the {need_w} px the tabs ask for"
        assert min_w <= need_w + 40, f"minimum width {min_w} is well over the {need_w} px the tabs ask for"
    check("the minimum width is what the wider tab asks for, not a guess", minimum_is_what_the_tabs_ask)

    # ---- the tuner bar: the pilot stays in the middle ----
    def pilot_centred():
        bar = tuner._tuner_ctrl_frame
        for w, h in ((min_w, min_h), (1280, 621), (sw - 20, min(sh - 80, 800))):
            if w > sw or h > sh - 60:
                continue
            at(w, h)
            app.notebook.select(app.tuner_frame)
            root.update()
            mid = bar.grid_slaves(row=0, column=1)[0]
            off = (mid.winfo_x() + mid.winfo_width() / 2.0) - bar.winfo_width() / 2.0
            assert abs(off) <= 2, f"at {w}x{h} the pilot group is {off:+.0f} px off the bar's centre"
    check("tuner bar: the motor pilot is centred at every width", pilot_centred)

    # ---- the drone tab: the scope is what gives ----
    def scope_gives():
        sizes = {}
        for w, h in ((min_w, min_h), (1280, 621), (1366, 669), (1280, min(sh - 60, 900))):
            if w > sw or h > sh - 60:
                continue
            at(w, h)
            app.notebook.select(app.exerciser_frame)
            root.update()
            s = ex.scope
            assert s.winfo_width() == s.winfo_height() == s._size, (s.winfo_width(), s.winfo_height(), s._size)
            assert ev.SCOPE_MIN_SIZE <= s._size <= ev.SCOPE_MAX_SIZE, s._size
            cx, cy, r = s.get_draw_area()
            assert (cx, cy) == (s._size // 2, s._size // 2) and r == s._size // 2 - 22, (cx, cy, r, s._size)
            x0, y0, x1, y1 = s.bbox("bezel_ring") if s.find_withtag("bezel_ring") else (0, 0, s._size, s._size)
            assert x0 >= -2 and y0 >= -2 and x1 <= s._size + 2 and y1 <= s._size + 2, \
                f"the bezel ({x0},{y0},{x1},{y1}) was not redrawn for a {s._size} px scope"
            sizes[(w, h)] = s._size
        tall = [v for (w, h), v in sizes.items() if h >= 800]
        assert not tall or tall[0] == ev.SCOPE_MAX_SIZE, f"on a tall window the scope is {tall[0]}, not {ev.SCOPE_MAX_SIZE}"
        assert sizes[(min_w, min_h)] < ev.SCOPE_MAX_SIZE, sizes
        print(f"        scope size by window: {sizes}")
    check("drone tab: the scope shrinks to fit a short window and is full size on a tall one", scope_gives)

    root.destroy()
    print("=" * 60)
    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
