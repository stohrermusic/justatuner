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

    def __init__(self):
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

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Pick the tab the user last had open
        initial = self.settings.get("active_tab", "tuner")
        if initial == "exerciser":
            self.notebook.select(self.exerciser_frame)
        else:
            self.notebook.select(self.tuner_frame)

        # The tab-changed event won't have fired for the *initial*
        # selection on every platform, so trigger our handler manually
        # to start the right engine and populate the menus.
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


def main():
    setup_logging()
    sys.excepthook = _handle_exception
    app = JustATunerApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
