"""The progression editor dialog (Drone > Progression...).

Pick a preset or a saved progression, type chords in the notation, or add
them with the pickers; choose bars-at-a-tempo, seconds, or manual advance
on a key; Use it on the tab, Save it under a name, Delete a saved one.
No message boxes: problems show in the dialog's own status line, so the
tour and the tests can drive it.
"""
import tkinter as tk
from tkinter import ttk

from exerciser.engine import VOICING_LABELS, VOICING_SYMBOLS
from exerciser.intervals import NOTE_NAMES
from exerciser.progression import (
    MODES, PRESETS, Progression, format_steps, load_progressions, parse_steps, save_progressions,
)

BG = "#F0EAD6"
FG = "black"
ERR = "#B00020"


class ProgressionDialog(tk.Toplevel):
    def __init__(self, parent, progression, advance_key, config_dir, on_use, on_key_change=None):
        super().__init__(parent)
        self.title("Drone Progression")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=BG)
        try:
            self.geometry(f"+{parent.winfo_rootx() + 80}+{parent.winfo_rooty() + 80}")
        except tk.TclError:
            pass
        self.config_dir = config_dir
        self.on_use = on_use
        self.on_key_change = on_key_change
        self.saved = load_progressions(config_dir)
        self.advance_key = advance_key
        self._capturing = False

        f = tk.Frame(self, bg=BG, padx=16, pady=12)
        f.pack(fill="both", expand=True)

        # ---- pick ----
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="Preset / saved:", bg=BG, fg=FG).pack(side="left", padx=(0, 6))
        self.pick_var = tk.StringVar()
        self.pick = ttk.Combobox(row, textvariable=self.pick_var, state="readonly", width=34)
        self.pick.pack(side="left")
        self.pick.bind("<<ComboboxSelected>>", self._on_pick)
        self._fill_pick()

        # ---- name + chords ----
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(0, 4))
        tk.Label(row, text="Name:", bg=BG, fg=FG, width=12, anchor="w").pack(side="left")
        self.name_var = tk.StringVar(value=progression.name)
        tk.Entry(row, textvariable=self.name_var, width=40).pack(side="left")

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(0, 2))
        tk.Label(row, text="Chords:", bg=BG, fg=FG, width=12, anchor="w").pack(side="left")
        self.text_var = tk.StringVar(value=format_steps(progression.steps))
        self.text = tk.Entry(row, textvariable=self.text_var, width=40)
        self.text.pack(side="left")
        tk.Label(f, text="Root letter, # or b, chord type, optional :length  —  e.g.  C | F | G7:2 | Am",
                 bg=BG, fg="#666666", font=("Helvetica", 8)).pack(anchor="w", padx=(0, 0), pady=(0, 6))

        # ---- picker ----
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text="Add a chord:", bg=BG, fg=FG, width=12, anchor="w").pack(side="left")
        self.root_var = tk.StringVar(value="C")
        ttk.Combobox(row, textvariable=self.root_var, values=list(NOTE_NAMES) + ["C#", "D#", "F#", "G#", "A#"],
                     state="readonly", width=4).pack(side="left")
        self.chord_var = tk.StringVar(value=VOICING_LABELS["major"])
        self._chord_by_label = {label: name for name, label in VOICING_LABELS.items()}
        ttk.Combobox(row, textvariable=self.chord_var, values=list(VOICING_LABELS.values()),
                     state="readonly", width=20).pack(side="left", padx=(4, 0))
        tk.Label(row, text="length", bg=BG, fg=FG).pack(side="left", padx=(8, 2))
        self.len_var = tk.StringVar(value="1")
        tk.Spinbox(row, from_=0.25, to=16, increment=0.25, textvariable=self.len_var, width=5).pack(side="left")
        tk.Button(row, text="Add", command=self._add_chord, width=6).pack(side="left", padx=(8, 0))

        # ---- timing ----
        box = tk.LabelFrame(f, text="Timing", bg=BG, fg=FG, padx=8, pady=4)
        box.pack(fill="x", pady=(0, 8))
        self.mode_var = tk.StringVar(value=progression.mode)
        tk.Radiobutton(box, text="Bars at a tempo", variable=self.mode_var, value="bars",
                       bg=BG, fg=FG, selectcolor=BG, activebackground=BG).grid(row=0, column=0, sticky="w")
        tk.Label(box, text="BPM", bg=BG, fg=FG).grid(row=0, column=1, padx=(12, 2))
        self.bpm_var = tk.StringVar(value=f"{progression.bpm:g}")
        tk.Spinbox(box, from_=30, to=240, textvariable=self.bpm_var, width=5).grid(row=0, column=2)
        tk.Label(box, text="beats / bar", bg=BG, fg=FG).grid(row=0, column=3, padx=(12, 2))
        self.beats_var = tk.StringVar(value=str(progression.beats_per_bar))
        tk.Spinbox(box, from_=1, to=12, textvariable=self.beats_var, width=4).grid(row=0, column=4)
        tk.Radiobutton(box, text="Seconds per chord (the :length)", variable=self.mode_var, value="seconds",
                       bg=BG, fg=FG, selectcolor=BG, activebackground=BG).grid(row=1, column=0, columnspan=3, sticky="w")
        tk.Radiobutton(box, text="Manual: advance on a key", variable=self.mode_var, value="manual",
                       bg=BG, fg=FG, selectcolor=BG, activebackground=BG).grid(row=2, column=0, sticky="w")
        self.key_btn = tk.Button(box, text="", command=self._capture_key, width=22)
        self.key_btn.grid(row=2, column=1, columnspan=4, sticky="w", padx=(12, 0))
        self._show_key()

        # ---- buttons + status ----
        self.status = tk.Label(f, text="", bg=BG, fg=ERR, anchor="w", justify="left", wraplength=440)
        self.status.pack(fill="x", pady=(0, 6))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x")
        tk.Button(row, text="Use", width=8, command=self._use).pack(side="left")
        tk.Button(row, text="Save", width=8, command=self._save).pack(side="left", padx=(6, 0))
        tk.Button(row, text="Delete", width=8, command=self._delete).pack(side="left", padx=(6, 0))
        tk.Button(row, text="Close", width=8, command=self.destroy).pack(side="right")

    # ---- helpers ----

    def _fill_pick(self):
        names = [f"Preset: {p.name}" for p in PRESETS] + [f"Saved: {p.name}" for p in self.saved]
        self.pick["values"] = names

    def _on_pick(self, event=None):
        label = self.pick_var.get()
        pool = PRESETS if label.startswith("Preset: ") else self.saved
        name = label.split(": ", 1)[1]
        p = next((x for x in pool if x.name == name), None)
        if p is None:
            return
        self.name_var.set(p.name)
        self.text_var.set(format_steps(p.steps))
        self.mode_var.set(p.mode)
        self.bpm_var.set(f"{p.bpm:g}")
        self.beats_var.set(str(p.beats_per_bar))
        self.status.config(text="")

    def _add_chord(self):
        sym = self.root_var.get() + VOICING_SYMBOLS[self._chord_by_label[self.chord_var.get()]]
        try:
            length = float(self.len_var.get())
        except ValueError:
            length = 1.0
        if length != 1.0:
            sym += f":{length:g}"
        cur = self.text_var.get().strip()
        self.text_var.set(f"{cur} | {sym}" if cur else sym)

    def _show_key(self):
        self.key_btn.config(text=f"Key: {self.advance_key}   (click to change)" if not self._capturing
                            else "Press the key to use...")

    def _capture_key(self):
        self._capturing = True
        self._show_key()
        self.bind("<KeyPress>", self._on_key_captured)
        self.focus_set()

    def _on_key_captured(self, event):
        self.unbind("<KeyPress>")
        self._capturing = False
        if event.keysym and event.keysym not in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            self.advance_key = event.keysym
            if self.on_key_change:
                self.on_key_change(self.advance_key)
        self._show_key()

    def read(self):
        """The dialog's fields as a Progression, or None with the status set."""
        try:
            steps = parse_steps(self.text_var.get())
            if not steps:
                raise ValueError("no chords yet")
            bpm = float(self.bpm_var.get())
            beats = int(self.beats_var.get())
            if not (30 <= bpm <= 240) or not (1 <= beats <= 12):
                raise ValueError("BPM 30-240, beats per bar 1-12")
            mode = self.mode_var.get()
            if mode not in MODES:
                raise ValueError("pick a timing mode")
            name = self.name_var.get().strip() or "Untitled"
            self.status.config(text="")
            return Progression(name, steps, mode, bpm, beats)
        except ValueError as e:
            self.status.config(text=str(e))
            return None

    def _use(self):
        p = self.read()
        if p is not None:
            self.on_use(p)
            self.destroy()

    def _save(self):
        p = self.read()
        if p is None:
            return
        self.saved = [s for s in self.saved if s.name != p.name] + [p]
        try:
            save_progressions(self.config_dir, self.saved)
        except OSError as e:
            self.status.config(text=f"could not save: {e}")
            return
        self._fill_pick()
        self.pick_var.set(f"Saved: {p.name}")
        self.status.config(text=f"saved '{p.name}'")
        self.status.config(fg="#2a6f2a")
        self.after(1500, lambda: self.status.config(fg=ERR))

    def _delete(self):
        name = self.name_var.get().strip()
        before = len(self.saved)
        self.saved = [s for s in self.saved if s.name != name]
        if len(self.saved) == before:
            self.status.config(text=f"'{name}' is not a saved progression (presets can't be deleted)")
            return
        save_progressions(self.config_dir, self.saved)
        self._fill_pick()
        self.pick_var.set("")
        self.status.config(text=f"deleted '{name}'")
