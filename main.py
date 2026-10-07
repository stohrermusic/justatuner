"""JustATuner — stroboscopic tuner + just-intonation drone.

Standalone Tk app. Two tabs:
  - Stroboscopic Tuner:  12-wheel chromatic strobe-style tuner (from Stohrer
                         Sax Shop Companion)
  - Just Intonation Drone: drone + pitch detector + Lissajous CRT (from the
                           legacy JustATone)

The two engines each own a sounddevice InputStream, and only the
active tab's engine runs — switching tabs stops one and starts the
other so the OS only sees one open mic at a time.
"""

import builtins
import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox


# JustATuner does not (yet) ship translation catalogs. The SSC tuner
# view code wraps user-facing strings with `_()` — install an identity
# function as a builtin so those calls pass through unchanged.
# Same pattern SSC uses via `i18n.init_translation()`.
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s


from config import (  # noqa: E402
    APP_NAME, APP_VERSION, load_settings, save_settings,
    setup_logging, get_log_file,
)
from tuner.view import TunerView  # noqa: E402
from exerciser.view import ExerciserView  # noqa: E402
from user_guide import open_user_guide  # noqa: E402


class JustATunerApp:
    """Top-level Tk app. Owns the notebook, the two views, and the
    settings dict that gets persisted on close."""

    def __init__(self, autostart=True):
        """Build the window and both tabs.

        autostart=False builds everything but starts no engine: the tests
        and --selftest use it to set a synthetic tone on the tuner engine
        before the first start. Normal launch starts the saved tab.
        """
        self.settings = load_settings()

        self.root = tk.Tk()
        # Route exceptions raised inside Tk callbacks / after-loop frames to
        # the log + a dialog — Tk swallows them silently by default, which is
        # where most of this app's code actually runs.
        self.root.report_callback_exception = _handle_exception
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        # Fallback geometry — used if maximize fails (e.g. unusual WMs)
        # and as the size the window restores to when un-maximized.
        self.root.geometry("1100x720")
        self.root.minsize(960, 620)
        self._maximize_window()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # WM_DELETE_WINDOW only covers the window close button. On macOS,
        # Cmd-Q and the app menu's Quit go through Tk's ::tk::mac::Quit
        # handler, whose default exits the process without running
        # _on_close — settings would silently never save. Route it
        # through the same close path.
        if sys.platform == "darwin":
            self.root.createcommand("::tk::mac::Quit", self._on_close)

        # Notebook + tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Tuner tab — built lazily once the tk root exists. The strobe
        # tuner picks up `_skip_theme` / `_dark_canvas` flags via its
        # own widget walker, so no extra theme prep is needed here.
        self.tuner_frame = tk.Frame(self.notebook, bg="#0D0D0D")
        self.notebook.add(self.tuner_frame, text="Stroboscopic Tuner")
        self.tuner = TunerView(self.tuner_frame, self.root, self.settings)

        # Exerciser tab
        self.exerciser_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self.exerciser_frame, text="Just Intonation Drone")
        self.exerciser = ExerciserView(self.exerciser_frame, self.root,
                                       self.settings)

        # Menu bar — populated per-tab in _on_tab_changed
        self._menubar = tk.Menu(self.root)
        self.root.config(menu=self._menubar)

        # Pick the tab the user last had open. ttk QUEUES a
        # <<NotebookTabChanged>> for this select (and for the first add),
        # delivered on the next event-loop pass, so binding after the
        # select does not keep the handler from running then. Instead the
        # handler ignores an event for the tab that is already active:
        # the explicit call below (or the caller, with autostart=False)
        # owns the first start, exactly once.
        initial = self.settings.get("active_tab", "tuner")
        if initial == "exerciser":
            self.notebook.select(self.exerciser_frame)
        else:
            self.notebook.select(self.tuner_frame)
        self._active_tab_id = self.notebook.select()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        if autostart:
            self._on_tab_changed()

    def run(self):
        self.root.mainloop()

    def _maximize_window(self):
        """Open maximized on every platform.

        Windows: `state('zoomed')` is the native maximize.
        Linux:   `attributes('-zoomed', True)` is the X11/wayland equivalent.
        macOS:   neither works (Aqua has no programmatic maximize); fall
                 back to sizing the window to the screen so it covers the
                 desktop. The user can still drag/resize from there.
        """
        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.root.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")

    # ------------------------------------------------------------------ #
    #  Tab + engine lifecycle
    # ------------------------------------------------------------------ #

    def _on_tab_changed(self, event=None):
        current = self.notebook.select()
        if event is not None and current == self._active_tab_id:
            # The queued event for a tab that is already running (the
            # initial selection): starting it again would open the mic
            # twice, and would start an engine the caller asked us not to.
            return
        self._active_tab_id = current
        is_tuner = current == str(self.tuner_frame)

        # Stop the inactive engine first to release the mic, THEN start
        # the new one. The other order risks two streams briefly fighting
        # for the input device on macOS.
        if is_tuner:
            self.exerciser.stop()
            self.tuner.start()
            self.settings["active_tab"] = "tuner"
        else:
            self.tuner.stop()
            self.exerciser.start()
            self.settings["active_tab"] = "exerciser"

        # Rebuild the menubar for the active tab. Both views expose a
        # populate_menu(menubar) when they have menus to contribute.
        self._rebuild_menubar(is_tuner)

    def _rebuild_menubar(self, is_tuner):
        # Wipe the existing cascades. Tk doesn't have a clean "remove
        # cascade" API, so build a fresh menubar each time.
        new_menubar = tk.Menu(self.root)

        file_menu = tk.Menu(new_menubar, tearoff=0)
        new_menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Quit", command=self._on_close)

        if is_tuner:
            if hasattr(self.tuner, "populate_menu"):
                self.tuner.populate_menu(new_menubar)
        elif hasattr(self.exerciser, "populate_menu"):
            self.exerciser.populate_menu(new_menubar)

        help_menu = tk.Menu(new_menubar, tearoff=0)
        new_menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Guide",
                              command=lambda: open_user_guide(self.root))
        help_menu.add_command(label="Open Log File",
                              command=self._open_log_file)
        help_menu.add_command(label="Test Audio Latency...",
                              command=self._open_latency_test)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)

        self.root.config(menu=new_menubar)
        self._menubar = new_menubar

    def _show_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            f"Stroboscopic tuner + just-intonation drone for musicians.\n\n"
            f"Tuner extracted from Stohrer Sax Shop Companion.\n"
            f"Drone is the original JustATone Python prototype.",
            parent=self.root,
        )

    def _open_latency_test(self):
        """Help > Test Audio Latency...: loopback round-trip measurement.

        The measurement (audio_latency.measure) needs the mic, and macOS
        may refuse a second open of the same input device, so the active
        tab's engine is stopped for the ~3 s the test runs and restarted
        through _on_tab_changed afterwards, even if the dialog was closed
        mid-test. The work runs on a thread; the UI polls it.
        """
        import threading
        import audio_latency
        from config import resolve_input_device

        if getattr(self, "_latency_dialog", None) is not None:
            try:
                self._latency_dialog.lift()
                return
            except tk.TclError:
                self._latency_dialog = None

        dlg = tk.Toplevel(self.root)
        dlg.title("Audio Latency Test")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:   # over the app, not at the screen's top-left
            dlg.geometry(f"+{self.root.winfo_rootx() + 80}+{self.root.winfo_rooty() + 80}")
        except tk.TclError:
            pass
        self._latency_dialog = dlg

        intro = (
            "Plays three short chirps through your speakers and listens for "
            "them on the microphone, then reports the round trip: how long "
            "the app waits between a sound happening and hearing it. That "
            "is the lag you feel on the strobe wheels and the drone "
            "analysis.\n\n"
            "Use speakers, not headphones, and keep the room quiet for a "
            "few seconds. The microphone is handed to the test while it "
            "runs and returned to the tuner or drone afterwards.")
        tk.Label(dlg, text=intro, wraplength=460, justify="left",
                 anchor="w").pack(fill="x", padx=16, pady=(14, 10))

        result_var = tk.StringVar(value="")
        tk.Label(dlg, textvariable=result_var, wraplength=460,
                 justify="left", anchor="w").pack(fill="x", padx=16,
                                                  pady=(0, 10))

        btn_row = tk.Frame(dlg)
        btn_row.pack(pady=(0, 14))
        run_btn = tk.Button(btn_row, text="Run Test", width=12)
        run_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Close", width=12,
                  command=dlg.destroy).pack(side="left", padx=6)

        state = {"thread": None, "result": None}

        def fmt(r):
            if r is None:
                return "The test could not run."
            lines = []
            if r.ok:
                lines.append(f"Round trip: {r.round_trip_ms:.0f} ms "
                             f"(speakers \u2192 room \u2192 mic).")
                lines.append(r.verdict())
            else:
                lines.append(r.message)
            if r.reported_input_ms is not None:
                lines.append(
                    f"\nReported by the audio driver: input "
                    f"{r.reported_input_ms:.0f} ms, output "
                    f"{r.reported_output_ms:.0f} ms. That figure is buffering "
                    f"only and cannot see a Bluetooth link or the room.")
            if r.sample_rate:
                lines.append(f"Stream: {r.sample_rate / 1000:g} kHz, "
                             f"mic \u201c{r.input_name}\u201d, "
                             f"speakers \u201c{r.output_name}\u201d.")
            return "\n".join(lines)

        def finish():
            # Give the mic back whether or not the dialog still exists.
            try:
                self._on_tab_changed()
            except Exception:
                logging.exception("Restarting audio after latency test")
            if dlg.winfo_exists():
                result_var.set(fmt(state["result"]))
                run_btn.configure(state="normal")

        def poll():
            t = state["thread"]
            if t is not None and t.is_alive():
                self.root.after(100, poll)
                return
            state["thread"] = None
            finish()

        def run():
            run_btn.configure(state="disabled")
            result_var.set("Listening\u2026")
            self.tuner.stop()
            self.exerciser.stop()
            in_dev = resolve_input_device(self.settings)

            def work():
                try:
                    state["result"] = audio_latency.measure(input_device=in_dev)
                except Exception:
                    logging.exception("Latency test failed")
                    state["result"] = None

            state["thread"] = threading.Thread(target=work, daemon=True)
            state["thread"].start()
            self.root.after(100, poll)

        run_btn.configure(command=run)

        def on_destroy(event=None):
            if event is not None and event.widget is not dlg:
                return
            self._latency_dialog = None

        dlg.bind("<Destroy>", on_destroy)

    def _open_log_file(self):
        """Open the diagnostic log in the OS default handler."""
        path = get_log_file()
        if not path or not os.path.exists(path):
            messagebox.showinfo(
                "Log file",
                f"No log file yet — it appears here once something is "
                f"logged:\n\n{path}",
                parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            messagebox.showerror(
                "Couldn't open log",
                f"{e}\n\nThe log file is at:\n{path}",
                parent=self.root)

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #

    def _on_close(self):
        try:
            self.tuner.stop()
        except Exception:
            pass
        try:
            self.exerciser.stop()
        except Exception:
            pass
        try:
            self.tuner.save_settings()
        except Exception:
            pass
        try:
            self.exerciser.save_settings()
        except Exception:
            pass
        save_settings(self.settings)
        try:
            self.root.destroy()
        except Exception:
            pass


def _handle_exception(exc_type, exc_value, exc_tb):
    """Log an unhandled exception and show a dialog pointing at the log.

    Wired to both ``sys.excepthook`` and Tk's ``report_callback_exception``
    so a crash in either path leaves a trace — the app ships without a
    console, so there's nowhere else for it to go.
    """
    import traceback
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error("Unhandled exception:\n%s", tb_text)
    try:
        messagebox.showerror(
            "Unexpected Error",
            f"{exc_type.__name__}: {exc_value}\n\n"
            "Details were saved to the log file (Help → Open Log File).")
    except Exception:
        pass  # GUI may not be available


# ---------------------------------------------------------------------- #
#  Self-test and screenshot tour (CI, and the frozen-build probe)
# ---------------------------------------------------------------------- #

TAB_LABEL_PADDING_PX = 30


def _fit_window_to_tabs(app):
    """Widen the window so every tab label fits.

    Aqua's ttk notebook clips tab labels instead of growing the tab row
    (seen on SSC's Mac tour, 2026-10-06). Windows and X11 grow the row, so
    there this is a no-op. Measures the labels with the notebook's own
    font rather than trusting a requested width that Aqua may not report.
    """
    import tkinter.font as tkfont
    root, nb = app.root, app.notebook
    try:
        root.update_idletasks()
        style = ttk.Style(root)
        spec = style.lookup("TNotebook.Tab", "font") or "TkDefaultFont"
        font = (tkfont.nametofont(spec) if spec in tkfont.names(root)
                else tkfont.Font(root, font=spec))
        need = sum(font.measure(nb.tab(t, "text")) for t in nb.tabs())
        need += TAB_LABEL_PADDING_PX * len(nb.tabs()) + 40
        cur_w = root.winfo_width()
        if cur_w <= 1:
            cur_w = 1100
        if need > cur_w:
            h = root.winfo_height() if root.winfo_height() > 1 else 760
            root.geometry(f"{need}x{h}")
    except tk.TclError:
        pass


def run_tour(app, shots_dir=None, step_ms=1500, on_done=None, appearance=None):
    """Walk every tab and dialog, optionally screenshotting each.

    This is how the Mac gets looked at: nobody on the project owns one, so
    the macOS build job runs the frozen .app with `--tour all --shots DIR`
    and uploads the pictures. With shots_dir=None it is a gate instead:
    every dialog is constructed and torn down on the live app, on every
    platform, and the returned error list holds anything that raised.

    Each step is (name, open, close). `open` may block in a modal
    wait_window — Tk keeps firing after() callbacks meanwhile, so the
    step's finish is scheduled BEFORE open is called. Modal or not, the
    same code works. Help > About is a native messagebox and is not
    toured: a native modal cannot be closed from a timer on every platform.
    """
    root = app.root
    tour_log = []
    tour_errors = []
    pre_toplevels = set()
    brightness = []

    def apply_appearance(win):
        # macOS only. `defaults write -g AppleInterfaceStyle Dark` does not
        # change a running login session, so a CI "dark" tour comes back
        # light (SSC, 2026-10-06). Tk can force a window's appearance.
        if appearance and sys.platform == "darwin":
            try:
                win.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win,
                            "darkaqua" if appearance == "dark" else "aqua")
                win.update_idletasks()
            except tk.TclError as e:
                tour_errors.append(f"appearance {appearance}: {e}")
    apply_appearance(root)

    def new_toplevels():
        return [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel) and w not in pre_toplevels]

    def destroy_new():
        for w in new_toplevels():
            try:
                w.destroy()
            except tk.TclError:
                pass

    def shot(name):
        if not shots_dir:
            return
        os.makedirs(shots_dir, exist_ok=True)
        path = os.path.join(shots_dir, f"{len(tour_log):02d}-{name}.png")
        try:
            from PIL import ImageGrab, ImageStat
            # Crop to the app's own windows (root + any open Toplevel) so
            # the picture is the app, not a desktop. Tk reports logical
            # pixels and the grab is physical: on a 250 % laptop (this PC,
            # 2026-10-06) the uncorrected crop was a corner of the browser
            # behind the app, so scale by the grab's size over Tk's.
            wins = [root] + [w for w in root.winfo_children()
                             if isinstance(w, tk.Toplevel) and w.winfo_viewable()]
            for w in wins:
                w.lift()
            root.update_idletasks()
            try:
                full = ImageGrab.grab(all_screens=True)
            except TypeError:
                full = ImageGrab.grab()
            scale = full.size[0] / max(1, root.winfo_screenwidth())
            x0 = min(w.winfo_rootx() for w in wins) - 12
            y0 = min(w.winfo_rooty() for w in wins) - 40
            x1 = max(w.winfo_rootx() + w.winfo_width() for w in wins) + 12
            y1 = max(w.winfo_rooty() + w.winfo_height() for w in wins) + 12
            box = tuple(int(round(v * scale)) for v in (x0, y0, x1, y1))
            box = (max(0, box[0]), max(0, box[1]), min(full.size[0], box[2]), min(full.size[1], box[3]))
            img = full.crop(box)
            img.save(path)
            # Mean brightness: says which appearance was really captured,
            # so a "dark" artifact can't quietly be the light one.
            try:
                brightness.append(ImageStat.Stat(img.convert("L")).mean[0])
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001 — fall back to the OS tool
            if sys.platform == "darwin":
                subprocess.run(["screencapture", "-x", path], check=False)
            else:
                tour_errors.append(f"{name}: screenshot failed: {e}")

    def open_tuner_no_mic():
        # What a user with no (or a denied) microphone sees: the real
        # engine start, which fails on a runner and draws the audio-error
        # text. On a machine with a mic this is just the live tuner.
        app.notebook.select(app.tuner_frame)
        app._on_tab_changed()

    def open_tuner():
        app.tuner._tuner_engine.synthetic_hz = 440.0
        app.notebook.select(app.tuner_frame)
        app.tuner.stop()
        app.tuner.start()

    def open_drone():
        app.notebook.select(app.exerciser_frame)
        app._on_tab_changed()

    def open_drone_mode(mode):
        def _open():
            app.exerciser.visualizer_mode.set(mode)
            app.exerciser._on_visualizer_mode_changed()
        return _open

    steps = [
        ("tuner-no-mic", open_tuner_no_mic, None),
        ("tuner", open_tuner, None),
        ("tuner-settings", app.tuner._tuner_open_settings, destroy_new),
        ("drone", open_drone, None),
    ]
    for mode in getattr(app.exerciser, "_available_modes", ()):
        steps.append((f"drone-{mode.lower()}", open_drone_mode(mode), None))
    steps += [
        ("latency-test", app._open_latency_test, destroy_new),
        ("user-guide", lambda: open_user_guide(root), destroy_new),
    ]

    def run_step(i):
        if i >= len(steps):
            try:
                app.tuner.stop()
                app.exerciser.stop()
            except Exception:
                pass
            if shots_dir:
                with open(os.path.join(shots_dir, "tour-done.txt"), "w", encoding="utf-8") as f:
                    # One line per stop with the picture's mean brightness
                    # (0-255). The app is dark by design, so a whole-shot
                    # verdict would say "dark" in either system appearance;
                    # the dialogs (settings, latency, guide) follow the
                    # system, so compare THEIR numbers between the light
                    # and dark runs.
                    for name, b in zip(tour_log, brightness or [None] * len(tour_log)):
                        f.write(f"{name}" + (f"  mean brightness {b:.0f}/255" if b is not None else "") + "\n")
                    f.write(f"appearance requested: {appearance or 'system'}\n")
                    f.write(f"window {root.winfo_width()}x{root.winfo_height()} on a "
                            f"{root.winfo_screenwidth()}x{root.winfo_screenheight()} screen; "
                            f"content wants {root.winfo_reqwidth()}x{root.winfo_reqheight()}\n")
                    if tour_errors:
                        f.write("ERRORS:\n" + "\n".join(tour_errors) + "\n")
            if on_done is not None:
                on_done()
            return
        name, open_fn, close_fn = steps[i]
        pre_toplevels.clear()
        pre_toplevels.update(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))

        def finish():
            try:
                for w in new_toplevels():
                    apply_appearance(w)
                root.update_idletasks()
                shot(name)
                tour_log.append(name)
            except Exception as e:  # noqa: BLE001
                tour_errors.append(f"{name}: {e!r}")
            try:
                if close_fn is not None:
                    close_fn()
            except Exception as e:  # noqa: BLE001
                tour_errors.append(f"{name} close: {e!r}")
            root.after(150, lambda: run_step(i + 1))

        # Audio tabs need a couple of seconds of frames before they look alive.
        wait = step_ms * (2 if name in ("tuner-no-mic", "tuner", "drone") else 1)
        root.after(wait, finish)
        try:
            open_fn()
        except Exception as e:  # noqa: BLE001
            tour_errors.append(f"{name} open: {e!r}")

    root.after(200, lambda: run_step(0))
    return tour_log, tour_errors


def _selftest():
    """Frozen-build probe: build the whole app headless, run each tab once,
    print SELFTEST OK / SELFTEST FAIL and exit 0 or 1.

    `JustATuner --selftest` constructs both tabs in a withdrawn root, runs
    the tuner on a synthetic 440 Hz tone through its real animate loop and
    checks the readout says A, then runs the drone tab (its real mic path:
    no input on a runner is reported, not a failure), and exits without
    saving anything. CI runs it against the PyInstaller output on each
    platform — the one check that runs the *shipped* bundle rather than
    the source tree, so a missing hidden import or a module bundled on the
    wrong platform fails the build instead of a user's first launch. No
    dialog can block: the exception hooks are replaced for the run.
    """
    import traceback

    def _say(msg):
        # os._exit skips Python's buffer flush, so write the verdict straight
        # to fd 1; a windowed .exe may have no fd 1 at all, hence the guard.
        try:
            os.write(1, (msg + "\n").encode("utf-8", "replace"))
        except OSError:
            pass

    def _plain_hook(exc_type, exc_value, exc_tb):
        _say("SELFTEST FAIL: " + "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        os._exit(1)

    sys.excepthook = _plain_hook
    root = None
    try:
        app = JustATunerApp(autostart=False)
        root = app.root
        root.report_callback_exception = _plain_hook
        root.withdraw()

        eng = app.tuner._tuner_engine
        if eng is None:
            raise RuntimeError("tuner tab not built (audio libraries missing)")
        eng.synthetic_hz = 440.0
        app.notebook.select(app.tuner_frame)
        app._on_tab_changed()                     # starts the tuner on the tone
        root.after(1500, root.quit)
        root.mainloop()
        frames = eng._synth_pos // 1024
        if frames < 20:
            raise RuntimeError(f"tuner fed only {frames} frames in 1.5 s")
        if app.tuner._tuner_error_state is not None:
            raise RuntimeError(f"tuner error state {app.tuner._tuner_error_state}")
        note = app.tuner._vu_note_label.cget("text")
        if note.rstrip("0123456789") != "A":
            raise RuntimeError(f"tuner readout {note!r}, expected A")
        # The wheel is only constructed on a viewable frame, never in a
        # withdrawn root, so this says whether the GPU module is present.
        renderer = "GPU wheel bundled" if app.tuner._tuner_use_gpu else "canvas"

        app.notebook.select(app.exerciser_frame)  # queued event -> drone starts, tuner stops
        root.after(1000, root.quit)
        root.mainloop()
        if not app.exerciser._running or app.tuner._tuner_running:
            raise RuntimeError("tab switch did not hand the audio to the drone tab")
        mic = app.exerciser.engine.input_error
        app.tuner.stop()
        app.exerciser.stop()
        _say(f"SELFTEST OK: {APP_VERSION} on {sys.platform}, frozen={getattr(sys, 'frozen', False)}, "
             f"tuner {frames} frames, readout {note}, renderer {renderer}, "
             f"drone mic {'ok' if mic is None else 'no input (' + mic + ')'}")
    except BaseException:
        _say("SELFTEST FAIL:\n" + traceback.format_exc())
        os._exit(1)
    try:
        root.destroy()
    except Exception:
        pass
    os._exit(0)


def _parse_args(argv):
    """--selftest | --tour all [--shots DIR] [--appearance dark|light]."""
    opts = {"selftest": False, "tour": None, "shots": None, "appearance": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--selftest":
            opts["selftest"] = True
        elif arg.startswith("--tour="):
            opts["tour"] = arg.split("=", 1)[1]
        elif arg == "--tour" and i + 1 < len(argv):
            i += 1
            opts["tour"] = argv[i]
        elif arg.startswith("--shots="):
            opts["shots"] = arg.split("=", 1)[1]
        elif arg == "--shots" and i + 1 < len(argv):
            i += 1
            opts["shots"] = argv[i]
        elif arg.startswith("--appearance="):
            opts["appearance"] = arg.split("=", 1)[1]
        elif arg == "--appearance" and i + 1 < len(argv):
            i += 1
            opts["appearance"] = argv[i]
        i += 1
    return opts


def main():
    setup_logging()
    opts = _parse_args(sys.argv[1:])
    if opts["selftest"]:
        _selftest()                      # never returns
    sys.excepthook = _handle_exception
    if opts["tour"] == "all":
        # Full walk: every tab and dialog, screenshot each when --shots is
        # given, then exit. A fixed window size so the pictures compare
        # across runs; the Mac gets its tab row widened first.
        app = JustATunerApp(autostart=False)
        app.root.state("normal")
        # Fit the runner's screen: the macOS runner is about 1024x768 and
        # the WM clamped a 1100x760 request, clipping the drone tab's
        # bottom row (first Mac tour, 2026-10-06). The size actually used
        # is written to tour-done.txt so each picture is self-describing.
        sw, sh = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
        w, h = min(1100, sw - 40), min(760, sh - 110)
        app.root.geometry(f"{w}x{h}+20+40")
        _fit_window_to_tabs(app)
        # A window opened from a background process stays behind whatever
        # the user has in front; the pictures must be of the app. Topmost
        # is set and cleared: left on, it covered the non-transient user
        # guide window in its own screenshot.
        app.root.lift()
        app.root.attributes("-topmost", True)
        app.root.update_idletasks()
        app.root.attributes("-topmost", False)

        def _finished():
            try:
                app.root.destroy()
            finally:
                os._exit(0)
        run_tour(app, shots_dir=opts["shots"], on_done=_finished, appearance=opts["appearance"])
        app.run()
        return 0
    app = JustATunerApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
