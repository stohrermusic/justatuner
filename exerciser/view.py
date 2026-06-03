"""Just-intonation exerciser view — drone + pitch detector + Lissajous CRT.

Adapted from the original JustATone Python prototype's ``main.py``.
The original was a self-contained Tk app; this version is a view that
builds into any parent Tk frame so it can live alongside the strobe
tuner inside JustATuner's notebook.
"""

import random
import tkinter as tk
from tkinter import ttk

import numpy as np

from exerciser.intervals import (
    NOTE_NAMES, TRANSPOSITIONS,
    note_freq, analyze_interval, transpose_note_name, freq_to_note_name,
)
from exerciser.engine import AudioEngine, INSTRUMENT_PRESETS, list_input_devices
from exerciser.widgets import RoundScope


# Frame rates
SCOPE_MS = 16       # ~60fps for Lissajous
ANALYSIS_MS = 80    # ~12fps for pitch analysis

# Vintage audio equipment palette — kept identical to the original
# JustATone so the look is the same. Lives here, not in a shared config,
# because the tuner tab uses an entirely different (configurable) palette.
COLOR_CHASSIS = "#1a1a1a"
COLOR_PANEL = "#252525"
COLOR_BEZEL = "#333333"
COLOR_GROOVE = "#111111"
COLOR_PHOSPHOR = "#00e640"
COLOR_AMBER = "#e8960c"
COLOR_CREAM = "#ddd0b8"
COLOR_CREAM_DIM = "#7a7060"
COLOR_GOLD = "#c89040"
COLOR_RED = "#cc3333"
COLOR_GREEN = "#33cc33"
COLOR_LOCKED = COLOR_PHOSPHOR
COLOR_CLOSE = COLOR_AMBER
COLOR_FAR = COLOR_RED

LOCK_THRESHOLD = 5.0
CLOSE_THRESHOLD = 15.0
LISSAJOUS_POINTS = 1200

PHOSPHOR_COLORS = {
    "Green":  ("#00e640", "#007a22", "#003d11"),
    "Amber":  ("#ffaa00", "#995500", "#4d2a00"),
    "Blue":   ("#4488ff", "#2244aa", "#112255"),
    "White":  ("#e0e0e0", "#808080", "#404040"),
}


class ExerciserView:
    """JI exerciser as an embeddable view.

    The host wires up tab visibility: call ``start()`` when this tab
    becomes active and ``stop()`` when it's hidden or the app is
    closing. Settings live in ``settings["exerciser_settings"]``; the
    view reads on construction and writes back via ``save_settings()``.
    """

    def __init__(self, parent, root, settings):
        self.root = root
        self.settings = settings
        ex = settings.setdefault("exerciser_settings", {})

        # State (initialized from settings, falling back to defaults)
        self.root_note = int(ex.get("root_note", 0))
        self.octave = int(ex.get("octave", 3))
        self.transposition = ex.get("transposition", "Concert (C)")
        self.drone_on = False  # Always off at startup — audible default would be rude
        self.drone_voicing = ex.get("drone_voicing", "root")
        self.drone_type = ex.get("drone_type", "rich")
        self.drone_volume = float(ex.get("drone_volume", 0.3))
        self.show_et_diff = tk.BooleanVar(value=bool(ex.get("show_et_diff", True)))

        # Input options
        self.instrument = tk.StringVar(value=ex.get("instrument", "Auto"))
        self.input_device = tk.StringVar(value="Default")

        # Scope display options
        self.scope_color = tk.StringVar(value=ex.get("scope_color", "Green"))
        self.scope_trails = tk.IntVar(value=int(ex.get("scope_trails", 1)))
        self.scope_thickness = tk.IntVar(value=int(ex.get("scope_thickness", 2)))
        self.scope_points = tk.IntVar(value=int(ex.get("scope_points", 300)))

        # Audio engine (created up-front so settings dialogs can list
        # devices, but the input stream isn't started until start()).
        self.engine = AudioEngine()
        self.engine.set_instrument(self.instrument.get())
        self.engine.set_drone(
            freq=note_freq(self.root_note, self.octave),
            voicing=self.drone_voicing,
            dtype=self.drone_type,
            volume=self.drone_volume,
        )

        # Animation-loop bookkeeping
        self._running = False
        self._scope_after_id = None
        self._analysis_after_id = None

        # Build UI inside the host-provided parent (no Tk root creation)
        self._frame = tk.Frame(parent, bg=COLOR_CHASSIS)
        self._frame.pack(fill="both", expand=True)
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  Public lifecycle (called by main.py on tab switch / app close)
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            self.engine.start()
        except RuntimeError as e:
            # No sounddevice / no input device. The UI still renders;
            # everything just shows "no signal" until audio comes back.
            print(f"Exerciser audio error: {e}")
        self._update_scope()
        self._update_analysis()

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._scope_after_id is not None:
            try:
                self.root.after_cancel(self._scope_after_id)
            except Exception:
                pass
            self._scope_after_id = None
        if self._analysis_after_id is not None:
            try:
                self.root.after_cancel(self._analysis_after_id)
            except Exception:
                pass
            self._analysis_after_id = None
        try:
            self.engine.stop()
        except Exception:
            pass

    def save_settings(self):
        """Push UI state into self.settings so the host can persist it."""
        self.settings["exerciser_settings"] = {
            "root_note": self.root_note,
            "octave": self.octave,
            "transposition": self.transposition,
            "drone_voicing": self.drone_voicing,
            "drone_type": self.drone_type,
            "drone_volume": self.drone_volume,
            "show_et_diff": bool(self.show_et_diff.get()),
            "instrument": self.instrument.get(),
            "scope_color": self.scope_color.get(),
            "scope_trails": int(self.scope_trails.get()),
            "scope_thickness": int(self.scope_thickness.get()),
            "scope_points": int(self.scope_points.get()),
        }

    def populate_menu(self, menubar):
        """Add the Drone + Exerciser-options menus to the host menubar.

        Called when the tab becomes active so the menus only appear
        while the exerciser is visible (mirrors SSC's tab-specific
        menu pattern)."""
        # -- Drone menu --
        drone_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Drone", menu=drone_menu)

        self._sound_var = tk.StringVar(value=self.drone_type)
        sound_menu = tk.Menu(drone_menu, tearoff=0)
        drone_menu.add_cascade(label="Sound", menu=sound_menu)
        for val, label in [("sine", "Sine"), ("rich", "Rich (harmonics)")]:
            sound_menu.add_radiobutton(
                label=label, variable=self._sound_var, value=val,
                command=self._on_sound_changed,
            )

        self._voicing_var = tk.StringVar(value=self.drone_voicing)
        voicing_menu = tk.Menu(drone_menu, tearoff=0)
        drone_menu.add_cascade(label="Voicing", menu=voicing_menu)
        for val, label in [
            ("root", "Root"), ("fifth", "Root + Fifth"),
            ("major", "Major Triad"), ("minor", "Minor Triad"),
        ]:
            voicing_menu.add_radiobutton(
                label=label, variable=self._voicing_var, value=val,
                command=self._on_voicing_changed,
            )

        # -- Exerciser options menu --
        options_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Exerciser Options", menu=options_menu)

        input_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Input", menu=input_menu)

        inst_menu = tk.Menu(input_menu, tearoff=0)
        input_menu.add_cascade(label="Instrument", menu=inst_menu)
        for name, preset in INSTRUMENT_PRESETS.items():
            desc = preset[4]
            inst_menu.add_radiobutton(
                label=f"{name}  ({desc})",
                variable=self.instrument, value=name,
                command=self._on_instrument_changed,
            )

        self._device_menu = tk.Menu(input_menu, tearoff=0)
        input_menu.add_cascade(label="Input Device", menu=self._device_menu)
        self._refresh_device_menu()
        input_menu.add_command(
            label="Refresh Devices", command=self._refresh_device_menu,
        )

        scope_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Scope Display", menu=scope_menu)

        color_menu = tk.Menu(scope_menu, tearoff=0)
        scope_menu.add_cascade(label="Phosphor Color", menu=color_menu)
        for color_name in PHOSPHOR_COLORS:
            color_menu.add_radiobutton(
                label=color_name, variable=self.scope_color, value=color_name,
            )

        thick_menu = tk.Menu(scope_menu, tearoff=0)
        scope_menu.add_cascade(label="Trace Thickness", menu=thick_menu)
        for w in [1, 2, 3, 4]:
            thick_menu.add_radiobutton(
                label=f"{w}px", variable=self.scope_thickness, value=w,
            )

        trail_menu = tk.Menu(scope_menu, tearoff=0)
        scope_menu.add_cascade(label="Trails", menu=trail_menu)
        for t, label in [(0, "None"), (1, "1 trail"), (2, "2 trails"), (3, "3 trails")]:
            trail_menu.add_radiobutton(
                label=label, variable=self.scope_trails, value=t,
            )

        res_menu = tk.Menu(scope_menu, tearoff=0)
        scope_menu.add_cascade(label="Resolution", menu=res_menu)
        for pts, label in [(150, "Low"), (300, "Medium"), (500, "High"), (800, "Ultra")]:
            res_menu.add_radiobutton(
                label=label, variable=self.scope_points, value=pts,
            )

        options_menu.add_checkbutton(
            label="Show ET Difference", variable=self.show_et_diff,
        )

    # ------------------------------------------------------------------ #
    #  UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        # Top strip
        top = tk.Frame(self._frame, bg=COLOR_CHASSIS, height=36)
        top.pack(fill="x")
        top.pack_propagate(False)

        tk.Label(
            top, text="JustATuner — JI Exerciser", font=("Helvetica", 13, "bold"),
            fg=COLOR_GOLD, bg=COLOR_CHASSIS,
        ).pack(side="left", padx=(20, 8), pady=6)
        tk.Label(
            top, text="Drone + pitch + Lissajous", font=("Helvetica", 9),
            fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
        ).pack(side="left", pady=(10, 6))

        tk.Frame(self._frame, bg=COLOR_GOLD, height=1).pack(fill="x", padx=15)

        body = tk.Frame(self._frame, bg=COLOR_CHASSIS)
        body.pack(fill="both", expand=True, padx=10, pady=(8, 4))

        left_col = tk.Frame(body, bg=COLOR_CHASSIS)
        left_col.pack(side="left", fill="both", expand=True)

        self._build_scope_panel(left_col)
        self._build_drone_row(left_col)
        self._build_interval_panel(body)

        tk.Frame(self._frame, bg=COLOR_GROOVE, height=1).pack(fill="x", padx=15)

        controls = tk.Frame(self._frame, bg=COLOR_PANEL)
        controls.pack(fill="x", padx=10, pady=(4, 8), ipady=4)

        self._build_note_controls(controls)
        tk.Frame(controls, bg=COLOR_GROOVE, width=1).pack(
            side="left", fill="y", padx=8, pady=4
        )
        self._build_status_section(controls)

    def _build_scope_panel(self, parent):
        frame = tk.Frame(parent, bg=COLOR_CHASSIS)
        frame.pack(expand=True, pady=(5, 2))

        tk.Label(
            frame, text="LISSAJOUS", font=("Helvetica", 8, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
        ).pack(pady=(0, 2))

        self.scope = RoundScope(frame, size=380, bg=COLOR_CHASSIS)
        self.scope.pack()

        self.ratio_label = tk.Label(
            frame, text="", font=("Courier", 10, "bold"),
            fg=COLOR_PHOSPHOR, bg=COLOR_CHASSIS,
        )
        self.ratio_label.pack(pady=(2, 0))

    def _build_drone_row(self, parent):
        row = tk.Frame(parent, bg=COLOR_CHASSIS)
        row.pack(pady=(2, 4))

        # DRONE switch — a labeled two-position rocker. Click OFF or ON
        # to set; the active side lights up amber (off) or red (on) like
        # a vintage console toggle.
        switch_frame = tk.Frame(row, bg=COLOR_GROOVE, bd=2, relief="sunken")
        switch_frame.pack(side="left", padx=8)
        tk.Label(
            switch_frame, text="DRONE", font=("Helvetica", 7, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_GROOVE,
        ).pack(side="top", pady=(2, 0))
        positions = tk.Frame(switch_frame, bg=COLOR_GROOVE)
        positions.pack(side="top", pady=(1, 2), padx=2)
        self.drone_off_btn = tk.Button(
            positions, text="OFF", width=4,
            font=("Helvetica", 9, "bold"),
            relief="flat", bd=0, cursor="hand2",
            command=lambda: self._set_drone(False),
        )
        self.drone_off_btn.pack(side="left", padx=(0, 1))
        self.drone_on_btn = tk.Button(
            positions, text="ON", width=4,
            font=("Helvetica", 9, "bold"),
            relief="flat", bd=0, cursor="hand2",
            command=lambda: self._set_drone(True),
        )
        self.drone_on_btn.pack(side="left")
        self._update_drone_switch()

        tk.Label(
            row, text="VOL", font=("Helvetica", 7, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
        ).pack(side="left", padx=(8, 2))

        self.vol_scale = tk.Scale(
            row, from_=0, to=100, orient="horizontal", length=100,
            showvalue=False, bd=0, highlightthickness=0,
            bg=COLOR_CHASSIS, fg=COLOR_CREAM_DIM,
            troughcolor=COLOR_BEZEL, activebackground=COLOR_GOLD,
            command=self._on_volume_changed,
        )
        self.vol_scale.set(int(self.drone_volume * 100))
        self.vol_scale.pack(side="left", padx=(0, 8))

        tk.Label(
            row, text="OCT", font=("Helvetica", 7, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
        ).pack(side="left", padx=(8, 2))

        self._octave_btns = []
        for o in range(2, 6):
            btn = tk.Button(
                row, text=str(o), width=2,
                font=("Helvetica", 9, "bold"),
                relief="flat", bd=0, cursor="hand2",
                command=lambda v=o: self._set_octave(v),
            )
            btn.pack(side="left", padx=1)
            self._octave_btns.append((o, btn))
        self._update_octave_buttons()

    def _build_interval_panel(self, parent):
        frame = tk.Frame(parent, bg=COLOR_PANEL, padx=10, pady=5)
        frame.pack(side="right", fill="both", expand=True, padx=(4, 5), pady=5)

        self.interval_label = tk.Label(
            frame, text="- - -", font=("Helvetica", 32, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        )
        self.interval_label.pack(pady=(20, 2))

        self.interval_ratio = tk.Label(
            frame, text="", font=("Courier", 16),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        )
        self.interval_ratio.pack(pady=(0, 10))

        self.meter = tk.Canvas(
            frame, bg=COLOR_PANEL, highlightthickness=0, height=80,
        )
        self.meter.pack(fill="x", padx=10, pady=5)

        self.lock_label = tk.Label(
            frame, text="", font=("Helvetica", 14, "bold"),
            fg=COLOR_PANEL, bg=COLOR_PANEL,
        )
        self.lock_label.pack(pady=(2, 5))

        self.played_label = tk.Label(
            frame, text="Play a note...", font=("Helvetica", 11),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        )
        self.played_label.pack(pady=(10, 2))

        self.et_label = tk.Label(
            frame, text="", font=("Helvetica", 10),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        )
        self.et_label.pack(pady=(0, 5))

        self.et_check = tk.Checkbutton(
            frame, text="Show ET difference", variable=self.show_et_diff,
            font=("Helvetica", 9), fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
            selectcolor=COLOR_CHASSIS, activebackground=COLOR_PANEL,
            activeforeground=COLOR_CREAM,
        )
        self.et_check.pack(pady=(0, 5))

        self.instrument_label = tk.Label(
            frame, text=f"Input: {self.instrument.get()}", font=("Helvetica", 8),
            fg=COLOR_AMBER, bg=COLOR_PANEL,
        )
        self.instrument_label.pack(side="bottom", pady=(0, 5))

        tk.Label(
            frame, text="\U0001F3A7 Headphones recommended",
            font=("Helvetica", 7), fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        ).pack(side="bottom", pady=(0, 2))

    def _build_note_controls(self, parent):
        frame = tk.Frame(parent, bg=COLOR_PANEL)
        frame.pack(side="left", padx=8, pady=4)

        row1 = tk.Frame(frame, bg=COLOR_PANEL)
        row1.pack(fill="x")

        tk.Label(
            row1, text="ROOT", font=("Helvetica", 8, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        ).pack(side="left", padx=(0, 8))

        self.note_buttons = []
        for i, name in enumerate(NOTE_NAMES):
            btn = tk.Button(
                row1, text=name, width=3, font=("Helvetica", 9, "bold"),
                relief="flat", bd=0, cursor="hand2",
                command=lambda idx=i: self._select_root(idx),
            )
            btn.pack(side="left", padx=1)
            self.note_buttons.append(btn)

        random_btn = tk.Button(
            row1, text="⚄", font=("Helvetica", 12),
            relief="flat", bd=0, cursor="hand2",
            bg=COLOR_GOLD, fg=COLOR_CHASSIS, width=2,
            activebackground="#daa050", activeforeground=COLOR_CHASSIS,
            command=self._random_root,
        )
        random_btn.pack(side="left", padx=(6, 0))

        row2 = tk.Frame(frame, bg=COLOR_PANEL)
        row2.pack(fill="x", pady=(4, 0))

        tk.Label(
            row2, text="TRANSPOSE", font=("Helvetica", 8),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        ).pack(side="left")
        self.trans_var = tk.StringVar(value=self.transposition)
        trans_menu = ttk.Combobox(
            row2, textvariable=self.trans_var,
            values=list(TRANSPOSITIONS.keys()), state="readonly", width=12,
        )
        trans_menu.pack(side="left", padx=4)
        trans_menu.bind("<<ComboboxSelected>>", self._on_transposition_changed)

        self._update_note_buttons()

    def _build_status_section(self, parent):
        frame = tk.Frame(parent, bg=COLOR_PANEL)
        frame.pack(side="left", fill="x", expand=True, padx=8, pady=4)

        tk.Label(
            frame, text="DRONE", font=("Helvetica", 8, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        ).pack(anchor="w")

        self.drone_status = tk.Label(
            frame, text="Stopped", font=("Helvetica", 10),
            fg=COLOR_CREAM_DIM, bg=COLOR_PANEL,
        )
        self.drone_status.pack(anchor="w", pady=(2, 0))

    # ------------------------------------------------------------------ #
    #  Event handlers
    # ------------------------------------------------------------------ #

    def _select_root(self, idx):
        self.root_note = idx
        self._update_note_buttons()
        self._update_drone_freq()

    def _random_root(self):
        self.root_note = random.randint(0, 11)
        self._update_note_buttons()
        self._update_drone_freq()

    def _on_transposition_changed(self, event=None):
        self.transposition = self.trans_var.get()
        self._update_note_buttons()

    def _set_drone(self, on):
        """Move the DRONE switch to OFF (on=False) or ON (on=True)."""
        if self.drone_on == on:
            return
        self.drone_on = on
        self._update_drone_switch()
        self.engine.set_drone(on=on)
        if on:
            self.drone_status.config(text="Playing", fg=COLOR_GREEN)
        else:
            self.drone_status.config(text="Stopped", fg=COLOR_CREAM_DIM)

    def _update_drone_switch(self):
        """Sync the OFF/ON button styling to self.drone_on."""
        if self.drone_on:
            # ON side lit (red), OFF side dim
            self.drone_off_btn.config(bg=COLOR_BEZEL, fg=COLOR_CREAM_DIM,
                                       activebackground=COLOR_BEZEL,
                                       activeforeground=COLOR_CREAM_DIM)
            self.drone_on_btn.config(bg="#5c2e2e", fg=COLOR_RED,
                                      activebackground="#7a3a3a",
                                      activeforeground=COLOR_RED)
        else:
            # OFF side lit (amber), ON side dim
            self.drone_off_btn.config(bg="#5c4a2e", fg=COLOR_AMBER,
                                       activebackground="#7a6038",
                                       activeforeground=COLOR_AMBER)
            self.drone_on_btn.config(bg=COLOR_BEZEL, fg=COLOR_CREAM_DIM,
                                      activebackground=COLOR_BEZEL,
                                      activeforeground=COLOR_CREAM_DIM)

    def _on_volume_changed(self, val):
        self.drone_volume = int(val) / 100.0
        self.engine.set_drone(volume=self.drone_volume)

    def _set_octave(self, val):
        self.octave = val
        self._update_octave_buttons()
        self._update_drone_freq()

    def _on_sound_changed(self):
        self.drone_type = self._sound_var.get()
        self.engine.set_drone(dtype=self.drone_type)

    def _on_voicing_changed(self):
        self.drone_voicing = self._voicing_var.get()
        self.engine.set_drone(voicing=self.drone_voicing)

    def _on_instrument_changed(self):
        name = self.instrument.get()
        self.engine.set_instrument(name)
        self.instrument_label.config(text=f"Input: {name}")

    def _on_input_device_changed(self, device_index):
        self.engine.set_input_device(device_index)
        if device_index is None:
            self.input_device.set("Default")
        else:
            for idx, name in list_input_devices():
                if idx == device_index:
                    self.input_device.set(name)
                    break

    def _refresh_device_menu(self):
        if not hasattr(self, "_device_menu"):
            return
        self._device_menu.delete(0, "end")
        self._device_menu.add_radiobutton(
            label="System Default",
            variable=self.input_device, value="Default",
            command=lambda: self._on_input_device_changed(None),
        )
        self._device_menu.add_separator()
        for idx, name in list_input_devices():
            self._device_menu.add_radiobutton(
                label=name,
                variable=self.input_device, value=name,
                command=lambda i=idx: self._on_input_device_changed(i),
            )

    # ------------------------------------------------------------------ #
    #  UI state updates
    # ------------------------------------------------------------------ #

    def _update_note_buttons(self):
        offset = TRANSPOSITIONS.get(self.transposition, 0)
        for i, btn in enumerate(self.note_buttons):
            written_idx = (i + offset) % 12
            btn.config(text=NOTE_NAMES[written_idx])
            if i == self.root_note:
                btn.config(bg=COLOR_GOLD, fg=COLOR_CHASSIS)
            else:
                btn.config(bg=COLOR_BEZEL, fg=COLOR_CREAM)

    def _update_octave_buttons(self):
        for val, btn in self._octave_btns:
            if val == self.octave:
                btn.config(bg=COLOR_GOLD, fg=COLOR_CHASSIS)
            else:
                btn.config(bg=COLOR_BEZEL, fg=COLOR_CREAM)

    def _update_drone_freq(self):
        freq = note_freq(self.root_note, self.octave)
        self.engine.set_drone(freq=freq)

    # ------------------------------------------------------------------ #
    #  Animation loops
    # ------------------------------------------------------------------ #

    def _update_scope(self):
        if not self._running:
            return
        root_freq = note_freq(self.root_note, self.octave)
        self._draw_lissajous(root_freq)
        self._scope_after_id = self.root.after(SCOPE_MS, self._update_scope)

    def _update_analysis(self):
        if not self._running:
            return
        freq, confidence = self.engine.get_pitch()
        root_freq = note_freq(self.root_note, self.octave)

        if freq is not None and confidence > 0.2:
            result = analyze_interval(freq, root_freq)
            if result:
                self._draw_interval(result, freq)
            else:
                self._draw_idle()
        else:
            self._draw_idle()

        self._analysis_after_id = self.root.after(ANALYSIS_MS, self._update_analysis)

    # ------------------------------------------------------------------ #
    #  Drawing
    # ------------------------------------------------------------------ #

    def _get_phosphor(self):
        return PHOSPHOR_COLORS.get(self.scope_color.get(), PHOSPHOR_COLORS["Green"])

    def _draw_lissajous(self, root_freq):
        scope = self.scope

        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()

        scope.delete("trace")
        cx, cy, r = scope.get_draw_area()
        trace_r = r * 0.82

        max_pts = self.scope_points.get()
        ref, mic = self.engine.get_lissajous_data(root_freq, LISSAJOUS_POINTS)

        ref_max = np.max(np.abs(ref))
        mic_max = np.max(np.abs(mic))
        if ref_max > 0.001:
            ref = ref / ref_max
        if mic_max > 0.001:
            mic = mic / mic_max
        else:
            mic = np.zeros_like(ref)

        step = max(1, len(ref) // max_pts)
        ref = ref[::step]
        mic = mic[::step]

        xs = cx + (ref * trace_r)
        ys = cy - (mic * trace_r)

        points = np.empty(len(xs) * 2)
        points[0::2] = xs
        points[1::2] = ys
        pts = points.tolist()

        phosphor_bright, phosphor_mid, phosphor_dim = self._get_phosphor()
        trail_count = self.scope_trails.get()
        thickness = self.scope_thickness.get()

        trail_colors = [phosphor_dim, phosphor_mid]
        if hasattr(self, "_liss_history"):
            for i, old_pts in enumerate(self._liss_history):
                if i >= trail_count:
                    break
                if len(old_pts) > 4:
                    tc = trail_colors[min(i, len(trail_colors) - 1)]
                    scope.create_line(
                        *old_pts, fill=tc, width=max(1, thickness - 1),
                        tags="trace",
                    )

        if len(pts) > 4:
            scope.create_line(
                *pts, fill=phosphor_bright, width=thickness, tags="trace",
            )

        if not hasattr(self, "_liss_history"):
            self._liss_history = []
        self._liss_history.insert(0, pts)
        if len(self._liss_history) > 3:
            self._liss_history = self._liss_history[:3]

        scope.draw_mask()

    def _draw_interval(self, result, played_freq):
        interval = result["interval"]
        cents_off = result["cents_off"]
        abs_cents = abs(cents_off)

        if abs_cents <= LOCK_THRESHOLD:
            color = COLOR_LOCKED
            status = "█ LOCKED █"
        elif abs_cents <= CLOSE_THRESHOLD:
            color = COLOR_CLOSE
            status = ""
        else:
            color = COLOR_FAR
            status = ""

        self.interval_label.config(text=interval["name"], fg=color)

        ratio_text = f'{interval["ratio"][0]}:{interval["ratio"][1]}'
        self.interval_ratio.config(text=ratio_text, fg=COLOR_CREAM)
        self.ratio_label.config(text=ratio_text, fg=self._get_phosphor()[0])

        self._draw_meter(cents_off, color)
        self.lock_label.config(text=status, fg=color)

        note_name, note_oct = freq_to_note_name(played_freq)
        note_idx = NOTE_NAMES.index(note_name) if note_name in NOTE_NAMES else 0
        written_idx = transpose_note_name(note_idx, self.transposition)
        written_name = NOTE_NAMES[written_idx]
        self.played_label.config(
            text=f"Playing: {written_name}{note_oct}  ({played_freq:.1f} Hz)",
            fg=COLOR_CREAM,
        )

        if self.show_et_diff.get():
            et_diff = interval["et_diff"]
            sign = "+" if et_diff > 0 else ""
            self.et_label.config(
                text=f"JI {interval['short']} is {sign}{et_diff:.1f}¢ from ET",
                fg=COLOR_AMBER,
            )
        else:
            self.et_label.config(text="")

    def _draw_meter(self, cents_off, color):
        self.meter.delete("all")
        mw = self.meter.winfo_width() or 300
        mh = self.meter.winfo_height() or 80
        cx = mw // 2
        abs_cents = abs(cents_off)

        meter_left = 20
        meter_right = mw - 20
        meter_y = mh // 2
        meter_w = meter_right - meter_left

        self.meter.create_rectangle(
            meter_left, meter_y - 6, meter_right, meter_y + 6,
            fill=COLOR_CHASSIS, outline=COLOR_BEZEL,
        )
        self.meter.create_line(
            cx, meter_y - 12, cx, meter_y + 12,
            fill=COLOR_CREAM, width=2,
        )

        for cents_mark in [-50, -25, -15, -5, 5, 15, 25, 50]:
            x = cx + (cents_mark / 50.0) * (meter_w / 2)
            tick_h = 8 if abs(cents_mark) in (25, 50) else 5
            self.meter.create_line(
                x, meter_y - tick_h, x, meter_y + tick_h,
                fill=COLOR_CREAM_DIM, width=1,
            )

        self.meter.create_text(
            meter_left, meter_y + 20, text="-50¢",
            font=("Courier", 7), fill=COLOR_CREAM_DIM, anchor="w",
        )
        self.meter.create_text(
            cx, meter_y + 20, text="0",
            font=("Courier", 7), fill=COLOR_CREAM, anchor="center",
        )
        self.meter.create_text(
            meter_right, meter_y + 20, text="+50¢",
            font=("Courier", 7), fill=COLOR_CREAM_DIM, anchor="e",
        )
        self.meter.create_text(
            meter_left + 10, meter_y - 18, text="♭ FLAT",
            font=("Helvetica", 7), fill=COLOR_CREAM_DIM, anchor="w",
        )
        self.meter.create_text(
            meter_right - 10, meter_y - 18, text="SHARP ♯",
            font=("Helvetica", 7), fill=COLOR_CREAM_DIM, anchor="e",
        )

        clamped = max(-50, min(50, cents_off))
        needle_x = cx + (clamped / 50.0) * (meter_w / 2)

        self.meter.create_line(
            needle_x, meter_y - 14, needle_x, meter_y + 14,
            fill=color, width=3,
        )
        if abs_cents <= LOCK_THRESHOLD:
            self.meter.create_oval(
                needle_x - 5, meter_y - 5, needle_x + 5, meter_y + 5,
                fill=color, outline="",
            )

        direction = "♯" if cents_off > 0 else "♭" if cents_off < 0 else ""
        self.meter.create_text(
            cx, mh - 5, text=f"{direction} {abs_cents:.1f}¢",
            font=("Courier", 12, "bold"), fill=color, anchor="s",
        )

    def _draw_idle(self):
        self.interval_label.config(text="- - -", fg=COLOR_CREAM_DIM)
        self.interval_ratio.config(text="", fg=COLOR_CREAM_DIM)
        self.ratio_label.config(text="")
        self.lock_label.config(text="", fg=COLOR_PANEL)

        self.meter.delete("all")
        mw = self.meter.winfo_width() or 300
        mh = self.meter.winfo_height() or 80
        self.meter.create_text(
            mw // 2, mh // 2, text="Awaiting signal...",
            font=("Helvetica", 10), fill=COLOR_CREAM_DIM,
        )

        offset = TRANSPOSITIONS.get(self.transposition, 0)
        written_idx = (self.root_note + offset) % 12
        root_name = NOTE_NAMES[written_idx]
        concert_name = NOTE_NAMES[self.root_note]

        if self.transposition == "Concert (C)":
            root_text = f"Root: {concert_name}{self.octave}"
        else:
            root_text = f"Root: {root_name} (concert {concert_name}{self.octave})"
        self.played_label.config(text=root_text, fg=COLOR_CREAM_DIM)
        self.et_label.config(text="")
