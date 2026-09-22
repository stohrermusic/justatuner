"""Small shared UI helpers: hover tooltips.

Ported from Stohrer Sax Shop Companion's ui_dialogs.py (only the tooltip
part; SSC's module also holds its many app-specific dialogs). The tuner
settings dialog in tuner/view.py imports ``add_tooltip`` from here, and
that import was missing in every JustATuner release before v1.1.3, so
Tuner > Settings... raised ImportError instead of opening.
"""

import tkinter as tk


# Tooltips can be switched off globally; bindings stay in place but
# become no-ops while disabled.
_TOOLTIPS_ENABLED = True


def set_tooltips_enabled(enabled):
    """Globally enable or disable tooltip popups. Applies immediately."""
    global _TOOLTIPS_ENABLED
    _TOOLTIPS_ENABLED = bool(enabled)


def tooltips_enabled():
    return _TOOLTIPS_ENABLED


class Tooltip:
    """Lightweight hover-to-explain tooltip for any tk widget.

    Shows a small borderless popup near the cursor after a short hover delay,
    hides on leave / click / focus-out. Safe across Windows/macOS/Linux:
    uses an overrideredirect Toplevel and avoids grabbing focus.
    """

    _BG = "#FFFFE0"  # pale yellow, readable on every platform
    _FG = "#000000"
    _BORDER = "#7A7A7A"
    DELAY_MS = 500
    WRAPLENGTH = 360

    def __init__(self, widget, text, delay_ms=None, wraplength=None):
        self.widget = widget
        self.text = text
        self.delay_ms = self.DELAY_MS if delay_ms is None else delay_ms
        self.wraplength = self.WRAPLENGTH if wraplength is None else wraplength
        self._after_id = None
        self._tip = None
        self._label = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<FocusOut>", self._hide, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def update_text(self, text):
        self.text = text
        if self._tip and self._label is not None:
            try:
                self._label.configure(text=text)
            except tk.TclError:
                pass

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        if not _TOOLTIPS_ENABLED:
            return
        try:
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 18
        except tk.TclError:
            return
        try:
            tip = tk.Toplevel(self.widget)
        except tk.TclError:
            return
        tip.wm_overrideredirect(True)
        # Keep tooltip out of the taskbar / above grabbed dialogs.
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(bg=self._BORDER)
        self._label = tk.Label(
            tip, text=self.text,
            bg=self._BG, fg=self._FG,
            justify="left", relief="flat",
            wraplength=self.wraplength,
            padx=6, pady=3,
            font=("Helvetica", 9),
        )
        self._label.pack(padx=1, pady=1)
        tip.update_idletasks()
        # Nudge back on screen if we'd overflow the right/bottom edge.
        try:
            sw = self.widget.winfo_screenwidth()
            sh = self.widget.winfo_screenheight()
            tw = tip.winfo_reqwidth()
            th = tip.winfo_reqheight()
            if x + tw > sw:
                x = max(0, sw - tw - 4)
            if y + th > sh:
                y = max(0, sh - th - 4)
        except tk.TclError:
            pass
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
            self._label = None

    def _on_destroy(self, _event=None):
        self._hide()


def add_tooltip(widget, text, **kwargs):
    """Attach a Tooltip to `widget`. Returns the Tooltip for further tweaking."""
    return Tooltip(widget, text, **kwargs)


def add_tooltips(text, *widgets, **kwargs):
    """Attach the same tooltip text to multiple widgets in one call."""
    return [Tooltip(w, text, **kwargs) for w in widgets]
