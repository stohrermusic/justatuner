"""JustATuner — strobe tuner + just-intonation exerciser.

Standalone Tk app. Two tabs:
  - Tuner:     12-wheel chromatic strobe tuner (from Stohrer Sax Shop Companion)
  - Exerciser: drone + pitch detector + Lissajous CRT (from the legacy JustATone)

The two engines each own a sounddevice InputStream, and only the
active tab's engine runs — switching tabs stops one and starts the
other so the OS only sees one open mic at a time.
"""

import builtins
import sys
import tkinter as tk
from tkinter import ttk, messagebox


# JustATuner does not (yet) ship translation catalogs. The SSC tuner
# view code wraps user-facing strings with `_()` — install an identity
# function as a builtin so those calls pass through unchanged.
# Same pattern SSC uses via `i18n.init_translation()`.
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s


from config import APP_NAME, APP_VERSION, load_settings, save_settings  # noqa: E402
from tuner.view import TunerView  # noqa: E402
from exerciser.view import ExerciserView  # noqa: E402
from user_guide import open_user_guide  # noqa: E402


class JustATunerApp:
    """Top-level Tk app. Owns the notebook, the two views, and the
    settings dict that gets persisted on close."""

    def __init__(self):
        self.settings = load_settings()

        self.root = tk.Tk()
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
        self.notebook.add(self.tuner_frame, text="Strobe Tuner")
        self.tuner = TunerView(self.tuner_frame, self.root, self.settings)

        # Exerciser tab
        self.exerciser_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self.exerciser_frame, text="JI Exerciser")
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

        if not is_tuner and hasattr(self.exerciser, "populate_menu"):
            self.exerciser.populate_menu(new_menubar)

        help_menu = tk.Menu(new_menubar, tearoff=0)
        new_menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Guide",
                              command=lambda: open_user_guide(self.root))
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)

        self.root.config(menu=new_menubar)
        self._menubar = new_menubar

    def _show_about(self):
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            f"Strobe tuner + just-intonation exerciser for musicians.\n\n"
            f"Tuner extracted from Stohrer Sax Shop Companion.\n"
            f"Exerciser is the original JustATone Python prototype.",
            parent=self.root,
        )

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


def main():
    app = JustATunerApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
