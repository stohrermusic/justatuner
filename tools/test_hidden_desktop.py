"""The suites run on a private Windows desktop: gates for tools/hidden_desktop.py
and for the hand-off at the top of tools/run_tests.py.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on any
failure. Imports nothing from the app and reads no settings.

What is judged is where a window ends up, not what the code says it asked for
(SSC's first version set an attribute Python ignores, and "worked" because the
suites passed in the open): a child started through rerun_hidden opens a real Tk
window, and that window's title must be among the windows of its own desktop
and absent from this process's desktop and from the user's ("Default").

The decision rules (`wanted`, `where`) and the runner's summary (a passing
suite's SKIP and INFO lines repeated) are checked on every platform, so this
suite never skips itself. The desktop checks run on Windows only, CI included:
they call rerun_hidden directly, which does not look at GITHUB_ACTIONS.

When JUSTATUNER_DESKTOP_PROBE is set this file is not a test: it writes the name
of the desktop it is running on to that path and exits. The hand-off check runs
`run_tests.py hidden_desktop` that way to see where the runner puts a suite.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import hidden_desktop as hd  # noqa: E402

PROBE_ENV = "JUSTATUNER_DESKTOP_PROBE"

if os.environ.get(PROBE_ENV):
    with open(os.environ[PROBE_ENV], "w", encoding="utf-8") as _f:
        json.dump({"desktop": hd.current_desktop_name(), "flag": os.environ.get(hd.ENV_FLAG, "")}, _f)
    print("  SKIP  probe: a planted check that did not run")
    print("  INFO  probe: a planted number, 12.3 fps " + "(padding) " * 20 + "END-OF-LINE")
    print("ALL TESTS PASSED (probe: wrote the desktop name)")
    sys.exit(0)

passed = 0
failed = 0


def check(name, fn):
    global passed, failed
    try:
        result = fn()
        if result is False:
            raise AssertionError("returned False")
        print(f"  PASS  {name}")
        passed += 1
    except Exception as e:  # noqa: BLE001 — a check that raises is a failed check
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        failed += 1


# --------------------------------------------------------------------------
# The decision rules, on every platform
# --------------------------------------------------------------------------
print("When the run moves to a private desktop")


class Env:
    """Set or remove environment variables for a block, and optionally the platform."""

    def __init__(self, platform=None, **values):
        self.platform, self.values = platform, values

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.values}
        for k, v in self.values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.saved_platform = sys.platform
        if self.platform:
            sys.platform = self.platform

    def __exit__(self, *exc):
        sys.platform = self.saved_platform
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


CLEAN = {"GITHUB_ACTIONS": None, "JUSTATUNER_VISIBLE": None, hd.ENV_FLAG: None}


def rules():
    argv = ["run_tests.py", "engine"]
    with Env(platform="win32", **CLEAN):
        assert hd.wanted(argv), "Windows, no CI, nothing asked: the run should move"
        assert not hd.wanted(argv + ["--visible"]), "--visible should keep it here"
        assert "your desktop" in hd.where(argv + ["--visible"])
    with Env(platform="win32", **dict(CLEAN, JUSTATUNER_VISIBLE="1")):
        assert not hd.wanted(argv), "JUSTATUNER_VISIBLE=1 should keep it here"
    with Env(platform="win32", **dict(CLEAN, GITHUB_ACTIONS="true")):
        assert not hd.wanted(argv), "CI should stay as it was"
        assert "CI" in hd.where(argv)
    with Env(platform="win32", **dict(CLEAN, **{hd.ENV_FLAG: "justatuner-tests-1"})):
        assert not hd.wanted(argv), "already on a private desktop: no second move"
        assert "justatuner-tests-1" in hd.where(argv) and "nothing shows" in hd.where(argv)
    for other in ("darwin", "linux"):
        with Env(platform=other, **CLEAN):
            assert not hd.wanted(argv), f"{other}: there is no private desktop"
            assert "not Windows" in hd.where(argv)


check("moves on Windows only; not in CI, not with --visible or JUSTATUNER_VISIBLE=1, not twice", rules)

if sys.platform != "win32":
    print("  INFO  the desktop checks are Windows-only; the rules above are what runs here")
else:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ENUMPROC, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def titles_on(desktop_handle):
        """Titles of the top-level windows on a desktop."""
        found = []

        def each(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:
                found.append(buf.value)
            return True

        user32.EnumDesktopWindows(desktop_handle, ENUMPROC(each), 0)
        return found

    def titles_here():
        return titles_on(user32.GetThreadDesktop(kernel32.GetCurrentThreadId()))

    def titles_on_users_desktop():
        """Titles on "Default", the desktop the user works on, or None if it cannot be opened."""
        DESKTOP_READOBJECTS, DESKTOP_ENUMERATE = 0x0001, 0x0040
        h = user32.OpenDesktopW("Default", 0, False, DESKTOP_READOBJECTS | DESKTOP_ENUMERATE)
        if not h:
            return None
        try:
            return titles_on(h)
        finally:
            user32.CloseDesktop(h)

    tmp = tempfile.mkdtemp(prefix="jat_test_desktop_")
    here = hd.current_desktop_name()
    print(f"\nA child started through rerun_hidden (this process is on {here!r})")

    # ---- the child: where it is, what it was told, and a real Tk window ----
    TITLE = f"jat-desktop-gate-{os.getpid()}"
    report_path = os.path.join(tmp, "child.json")
    ready_path = os.path.join(tmp, "ready")
    CHILD = r'''
import ctypes, json, os, sys, time
sys.path.insert(0, sys.argv[1])
import hidden_desktop as hd
title, report_path, ready_path = sys.argv[2], sys.argv[3], sys.argv[4]
rep = {"desktop": hd.current_desktop_name(), "flag": os.environ.get(hd.ENV_FLAG, "")}
import tkinter as tk
root = tk.Tk()
root.title(title)
root.geometry("200x80+40+40")
root.update()
rep["viewable"] = bool(root.winfo_viewable())
rep["screen"] = [root.winfo_screenwidth(), root.winfo_screenheight()]
from ctypes import wintypes
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
u.GetThreadDesktop.restype = wintypes.HANDLE
u.GetThreadDesktop.argtypes = [wintypes.DWORD]
P = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.EnumDesktopWindows.argtypes = [wintypes.HANDLE, P, wintypes.LPARAM]
u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
seen = []
def each(hwnd, _):
    b = ctypes.create_unicode_buffer(256); u.GetWindowTextW(hwnd, b, 256); seen.append(b.value); return True
u.EnumDesktopWindows(u.GetThreadDesktop(k.GetCurrentThreadId()), P(each), 0)
rep["own_window_on_own_desktop"] = title in seen
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(rep, f)
open(ready_path, "w").close()
t0 = time.time()
while time.time() - t0 < 2.5:        # stay up while the parent looks for the window
    root.update()
    time.sleep(0.05)
root.destroy()
print("CHILD-OUTPUT-MARK")
sys.exit(7)
'''
    child_py = os.path.join(tmp, "child.py")
    with open(child_py, "w", encoding="utf-8") as f:
        f.write(CHILD)

    seen_while_up = {}

    def look():
        t0 = time.time()
        while not os.path.exists(ready_path) and time.time() - t0 < 30:
            time.sleep(0.05)
        seen_while_up["ready"] = os.path.exists(ready_path)
        seen_while_up["here"] = titles_here()
        seen_while_up["default"] = titles_on_users_desktop()

    watcher = threading.Thread(target=look, daemon=True)
    watcher.start()
    flag_before = os.environ.get(hd.ENV_FLAG)
    code = hd.rerun_hidden([sys.executable, "-u", child_py, TOOLS, TITLE, report_path, ready_path], cwd=ROOT)
    watcher.join(35)
    rep = {}
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            rep = json.load(f)

    def exit_code_back():
        assert code == 7, f"exit code {code}, report {rep}"

    check("the child ran, and its exit code (7) came back", exit_code_back)
    check(f"the child is on a desktop of its own ({rep.get('desktop')!r}), not this one",
          lambda: rep.get("desktop", "").startswith(hd.DESKTOP_PREFIX) and rep["desktop"] != here)
    check("the child was told which desktop it is on (the flag), and this process's flag is as it was",
          lambda: rep.get("flag") == rep.get("desktop") and os.environ.get(hd.ENV_FLAG) == flag_before)
    check("a Tk window opens there: viewable, and listed among that desktop's windows",
          lambda: rep.get("viewable") is True and rep.get("own_window_on_own_desktop") is True)

    def not_here():
        assert seen_while_up.get("ready"), "the child never opened its window"
        assert TITLE not in seen_while_up["here"], "the child's window is on this process's desktop"

    check("while it was open, that window was NOT among the windows of this process's desktop", not_here)

    def not_on_default():
        assert seen_while_up.get("ready"), "the child never opened its window"
        d = seen_while_up["default"]
        assert d is not None, "the user's desktop could not be opened to look"
        assert TITLE not in d, "the child's window is on the user's desktop"

    check('while it was open, that window was NOT among the windows of the user\'s desktop ("Default")',
          not_on_default)
    check(f"the screen size read there is a real one ({rep.get('screen')})",
          lambda: rep.get("screen", [0, 0])[0] >= 640 and rep["screen"][1] >= 480)

    # ---- as a command: output and exit code pass through a pipe ----
    def as_command():
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "JUSTATUNER_VISIBLE", hd.ENV_FLAG)}
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "hidden_desktop.py"), sys.executable, "-c",
                            "import sys, hidden_desktop as hd; print('MARK', hd.current_desktop_name()); sys.exit(3)"],
                           cwd=TOOLS, env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 3, f"exit code {r.returncode}: {r.stderr[-300:]}"
        assert "MARK " + hd.DESKTOP_PREFIX in r.stdout, f"output did not come back through the pipe: {r.stdout!r}"

    check("`python tools/hidden_desktop.py <command>`: the command's output and exit code come back", as_command)

    # ---- the hand-off in run_tests.py ----
    print("\ntools/run_tests.py puts a suite on a private desktop")

    def run_runner(extra, visible_env=None):
        probe = os.path.join(tmp, f"probe-{len(os.listdir(tmp))}.json")
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "JUSTATUNER_VISIBLE", hd.ENV_FLAG)}
        env[PROBE_ENV] = probe
        if visible_env:
            env["JUSTATUNER_VISIBLE"] = visible_env
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "run_tests.py"), "hidden_desktop"] + extra,
                           cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180)
        assert r.returncode == 0, f"the runner exited {r.returncode}:\n{r.stdout[-600:]}\n{r.stderr[-300:]}"
        with open(probe, encoding="utf-8") as f:
            return json.load(f), r.stdout

    def handed_off():
        got, out = run_runner([])
        assert got["desktop"].startswith(hd.DESKTOP_PREFIX), f"the suite ran on {got['desktop']!r}"
        assert got["desktop"] != here
        first = out.strip().splitlines()[0]
        assert "private desktop" in first and got["desktop"] in first, f"the runner's first line: {first!r}"

    check("a suite started by run_tests.py is on a private desktop, and the runner's first line says so", handed_off)

    def stays_visible():
        got, out = run_runner(["--visible"])
        assert got["desktop"] == here, f"--visible: the suite ran on {got['desktop']!r}, this process is on {here!r}"
        assert "--visible" in out.strip().splitlines()[0]
        got, _ = run_runner([], visible_env="1")
        assert got["desktop"] == here, f"JUSTATUNER_VISIBLE=1: the suite ran on {got['desktop']!r}"

    check("--visible and JUSTATUNER_VISIBLE=1 keep the suite on the desktop the runner was started from",
          stays_visible)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

# --------------------------------------------------------------------------
# The runner's summary, on every platform
# --------------------------------------------------------------------------
print("\ntools/run_tests.py repeats what one line per passing suite hides")


def runner_output():
    """`run_tests.py hidden_desktop` with this file as the probe: it passes, having
    printed one planted SKIP line and one planted INFO line. --visible, so this
    needs no desktop and reads the same on every platform."""
    tmp2 = tempfile.mkdtemp(prefix="jat_test_runner_")
    try:
        env = dict(os.environ)
        env[PROBE_ENV] = os.path.join(tmp2, "probe.json")
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "run_tests.py"), "hidden_desktop", "--visible"],
                           cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=180)
        assert r.returncode == 0, f"the runner exited {r.returncode}:\n{r.stdout[-600:]}\n{r.stderr[-300:]}"
        return r.stdout
    finally:
        import shutil as _sh
        _sh.rmtree(tmp2, ignore_errors=True)


try:
    RUNNER_OUT = runner_output()
except Exception as e:  # noqa: BLE001 — the two checks below report it
    RUNNER_OUT = f"(the runner could not be run: {type(e).__name__}: {e})"


def inner_skip_reported():
    # A passing suite that left a check out says so on a "SKIP" line; the runner's
    # one line per suite would hide it (on a private desktop the GPU picture check
    # cannot grab the screen), so the runner repeats those lines at the end.
    assert "left out inside suites that passed" in RUNNER_OUT, RUNNER_OUT[-400:]
    assert "test_hidden_desktop: SKIP  probe: a planted check that did not run" in RUNNER_OUT, RUNNER_OUT[-400:]


check("a check a passing suite left out (a SKIP line) is repeated in the runner's summary", inner_skip_reported)


def inner_info_reported():
    # A number a suite measures but does not judge is on an "INFO" line. The Mac
    # runner's frame rate was printed that way and never seen: the runner repeats
    # those lines too, whole (the planted one is 250 characters long).
    assert "marked INFO in suites that passed" in RUNNER_OUT, RUNNER_OUT[-600:]
    line = next((ln for ln in RUNNER_OUT.splitlines()
                 if ln.strip().startswith("test_hidden_desktop: INFO  probe: a planted number, 12.3 fps")), None)
    assert line is not None, RUNNER_OUT[-600:]
    assert line.rstrip().endswith("END-OF-LINE"), f"the INFO line was cut short: {line[-80:]!r}"


check("a number a passing suite printed (an INFO line) is repeated in the runner's summary, whole",
      inner_info_reported)

print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
