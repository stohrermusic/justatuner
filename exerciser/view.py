"""Just-intonation exerciser view — drone + pitch detector + Lissajous CRT.

Adapted from the original JustATone Python prototype's ``main.py``.
The original was a self-contained Tk app; this version is a view that
builds into any parent Tk frame so it can live alongside the strobe
tuner inside JustATuner's notebook.
"""

import colorsys
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

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

        # Visualizer mode + scope display options. The mode dispatches
        # which _draw_* method runs each frame; the color/thickness/etc.
        # settings apply to whichever modes use them.
        _VALID_MODES = ["Lissajous", "Waveform", "Spectrum", "Waterfall"]
        if _HAS_PIL:
            _VALID_MODES.append("Warp")
            _VALID_MODES.append("Garden")
        _saved_mode = ex.get("visualizer_mode", "Lissajous")
        if _saved_mode not in _VALID_MODES:
            # Migrate retired modes (e.g. "Phase Wheel") to the default.
            _saved_mode = "Lissajous"
        self.visualizer_mode = tk.StringVar(value=_saved_mode)
        self._available_modes = tuple(_VALID_MODES)
        self.scope_color = tk.StringVar(value=ex.get("scope_color", "Green"))
        self.scope_trails = tk.IntVar(value=int(ex.get("scope_trails", 1)))
        self.scope_thickness = tk.IntVar(value=int(ex.get("scope_thickness", 2)))
        self.scope_points = tk.IntVar(value=int(ex.get("scope_points", 300)))

        # Persistent canvas items for the Spectrum visualizer. Created
        # lazily on first draw and updated via .coords() each frame —
        # tk hates delete+recreate of many items per frame.
        self._spectrum_items = []

        # Warp visualizer state. Lazily allocated on first draw. The
        # warp uses a numpy framebuffer that each frame is zoomed
        # slightly outward + brightness-decayed, with new audio-
        # driven content painted on top — Ryan Geiss / MilkDrop style.
        self._warp_buffer = None        # numpy uint8 array, shape (N,N,3)
        self._warp_size = 220           # framebuffer side length in pixels
        self._warp_photo = None         # ImageTk.PhotoImage (current frame)
        self._warp_canvas_item = None   # Canvas image item id
        self._warp_t = 0.0              # frame-phase accumulator (for color cycle)

        # Waterfall visualizer state. A rolling stack of FFT frames
        # drawn with perspective so older frames sit further back —
        # gives the classic Geiss-style "flying over a mountain
        # range" effect. Each row stores the magnitudes it was
        # created with AND the hue at that moment, so the slow color
        # cycle reads through history.
        self._waterfall_rows = []       # list of (np.ndarray, color_hex) front→back
        self._waterfall_lines = []      # persistent canvas line item ids, one per row
        self._waterfall_hue = 0.0       # 0..1, advances each frame

        # Garden visualizer state. A print-head ribbon model: each
        # frame, every alive branch stamps the current FFT cross-
        # section perpendicular to its growth direction onto a
        # persistent PIL framebuffer. Branches split on amplitude
        # peaks (L-system style) using golden-angle phyllotaxis and
        # apical dominance (depth-based width/speed decay). When the
        # current plant matures (all branches dead), a new plant
        # spawns to the right; once the canvas fills with plants,
        # the buffer scrolls left treadmill-style.
        self._garden_buffer = None       # PIL Image, the persistent canvas
        self._garden_canvas_item = None  # tk canvas image item id
        self._garden_photo = None        # ImageTk.PhotoImage (kept alive)
        self._garden_plants = []         # list of plant dicts (see _draw_garden)
        self._garden_hue = 0.18          # 0..1, slowly advances
        self._garden_centroid_smooth = 1000.0
        self._garden_size = 280          # framebuffer side length in pixels
        self._garden_next_plant_x = 30.0 # x to seed the next plant at
        self._garden_audio_env = 0.0     # smoothed RMS for branching triggers
        self._garden_last_branch_frame = -999
        self._garden_circle_mask = None  # PIL "L"-mode mask sized to display
        # Fireflies — transient overlay drifting above the garden.
        # Don't write to the persistent buffer (they'd leave trails);
        # composited onto a per-frame copy at display time.
        self._garden_fireflies = []      # list of firefly dicts
        self._garden_firefly_spawn = 0   # cooldown counter

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
            "visualizer_mode": self.visualizer_mode.get(),
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
        for val, label in [
            ("sine", "Sine"),
            ("rich", "Rich (harmonics)"),
            ("sample", "Sample (WAV)"),
        ]:
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

        # Sample submenu — load a WAV from disk, record a new one off
        # the mic, or drop the current sample and return to synth.
        sample_menu = tk.Menu(drone_menu, tearoff=0)
        drone_menu.add_cascade(label="Sample", menu=sample_menu)
        sample_menu.add_command(label="Load WAV File...",
                                command=self._on_load_sample_wav)
        sample_menu.add_command(label="Record New...",
                                command=self._on_record_sample)
        sample_menu.add_separator()
        sample_menu.add_command(label="Clear Sample (back to synth)",
                                command=self._on_clear_sample)

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

        viz_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Visualizer", menu=viz_menu)

        mode_menu = tk.Menu(viz_menu, tearoff=0)
        viz_menu.add_cascade(label="Mode", menu=mode_menu)
        for mode_name in self._available_modes:
            # The displayed label can include qualifiers like "(beta)"
            # while the underlying value stays plain — settings stored
            # in app_settings.json still round-trip cleanly.
            display = mode_name + " (beta)" if mode_name == "Garden" else mode_name
            mode_menu.add_radiobutton(
                label=display, variable=self.visualizer_mode, value=mode_name,
                command=self._on_visualizer_mode_changed,
            )

        color_menu = tk.Menu(viz_menu, tearoff=0)
        viz_menu.add_cascade(label="Phosphor Color", menu=color_menu)
        for color_name in PHOSPHOR_COLORS:
            color_menu.add_radiobutton(
                label=color_name, variable=self.scope_color, value=color_name,
            )

        thick_menu = tk.Menu(viz_menu, tearoff=0)
        viz_menu.add_cascade(label="Trace Thickness", menu=thick_menu)
        for w in [1, 2, 3, 4]:
            thick_menu.add_radiobutton(
                label=f"{w}px", variable=self.scope_thickness, value=w,
            )

        trail_menu = tk.Menu(viz_menu, tearoff=0)
        viz_menu.add_cascade(label="Lissajous Trails", menu=trail_menu)
        for t, label in [(0, "None"), (1, "1 trail"), (2, "2 trails"), (3, "3 trails")]:
            trail_menu.add_radiobutton(
                label=label, variable=self.scope_trails, value=t,
            )

        res_menu = tk.Menu(viz_menu, tearoff=0)
        viz_menu.add_cascade(label="Resolution", menu=res_menu)
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
            top, text="Just Intonation Drone", font=("Helvetica", 13, "bold"),
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

        # Label is dynamic — reflects the active visualizer mode.
        self.scope_mode_label = tk.Label(
            frame, text=self.visualizer_mode.get().upper(),
            font=("Helvetica", 8, "bold"),
            fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
        )
        self.scope_mode_label.pack(pady=(0, 2))

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
        new_type = self._sound_var.get()
        # Picking Sample with no sample loaded -> bounce straight to
        # the file picker. If the user cancels we revert to whatever
        # type was active before.
        if new_type == "sample":
            label, _freq = self.engine.sample_info()
            if label is None:
                if not self._on_load_sample_wav():
                    self._sound_var.set(self.drone_type)
                    return
        self.drone_type = new_type
        self.engine.set_drone(dtype=self.drone_type)

    def _on_load_sample_wav(self):
        """Open a file picker, load the chosen WAV as the drone sample.
        Returns True on success, False on cancel/error."""
        path = filedialog.askopenfilename(
            title="Load WAV sample for drone",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
            parent=self.root,
        )
        if not path:
            return False
        try:
            info = self.engine.load_sample_wav(path)
        except (OSError, ValueError, Exception) as e:
            messagebox.showerror(
                "Couldn't load sample",
                f"Failed to read '{path}':\n\n{e}",
                parent=self.root,
            )
            return False
        # Engine flipped drone_type to "sample" itself; mirror that in
        # the local var + menu selection.
        self.drone_type = "sample"
        self._sound_var.set("sample")
        msg = (f"Loaded {info['label']} ({info['duration_s']:.1f}s @ "
               f"{info['sr']} Hz).\n"
               f"Detected fundamental: {info['freq_hz']:.1f} Hz"
               + ("" if info["pitch_confident"]
                  else " (low confidence — pitch may be off)"))
        messagebox.showinfo("Sample loaded", msg, parent=self.root)
        return True

    def _on_record_sample(self):
        """Pop the recording dialog. On stop, the recorded audio
        replaces the current drone sample."""
        # Sample recording reads from the same input stream that's
        # already running for pitch detection — no separate stream.
        # If the engine isn't running yet, start it so the input
        # callback is firing.
        if not self.engine.running:
            try:
                self.engine.start()
            except Exception as e:
                messagebox.showerror(
                    "Can't record",
                    f"Couldn't open the microphone:\n\n{e}",
                    parent=self.root,
                )
                return
        RecordSampleDialog(self.root, self.engine, on_complete=self._after_record)

    def _after_record(self, info):
        if info is None:
            return  # cancelled or empty
        self.drone_type = "sample"
        self._sound_var.set("sample")
        msg = (f"Recorded {info['duration_s']:.1f}s.\n"
               f"Detected fundamental: {info['freq_hz']:.1f} Hz"
               + ("" if info["pitch_confident"]
                  else " (low confidence — pitch may be off)"))
        messagebox.showinfo("Sample recorded", msg, parent=self.root)

    def _on_clear_sample(self):
        self.engine.clear_sample()
        # Engine reverts drone_type to "rich" inside clear_sample().
        self.drone_type = self.engine.drone_type
        self._sound_var.set(self.drone_type)

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
        mode = self.visualizer_mode.get()
        if mode == "Waveform":
            self._draw_waveform()
        elif mode == "Spectrum":
            self._draw_spectrum()
        elif mode == "Waterfall":
            self._draw_waterfall()
        elif mode == "Warp":
            self._draw_warp()
        elif mode == "Garden":
            self._draw_garden()
        else:
            self._draw_lissajous(root_freq)
        self._scope_after_id = self.root.after(SCOPE_MS, self._update_scope)

    def _on_visualizer_mode_changed(self):
        """Reset per-mode state and refresh the mode label when the user
        picks a different visualizer."""
        mode = self.visualizer_mode.get()
        try:
            self.scope_mode_label.config(text=mode.upper())
        except Exception:
            pass
        # Drop any in-flight Lissajous trail history; nuke cached
        # canvas items for the other modes so the next draw recreates
        # them clean.
        self._liss_history = []
        try:
            self.scope.delete("trace")
            self.scope.delete("bars")
            self.scope.delete("warp")
            self.scope.delete("waterfall")
            self.scope.delete("garden")
        except Exception:
            pass
        self._spectrum_items = []
        self._warp_buffer = None
        self._warp_photo = None
        self._warp_canvas_item = None
        self._waterfall_rows = []
        self._waterfall_lines = []
        self._garden_buffer = None
        self._garden_canvas_item = None
        self._garden_photo = None
        self._garden_plants = []
        self._garden_next_plant_x = 30.0
        self._garden_audio_env = 0.0
        self._garden_last_branch_frame = -999
        self._garden_circle_mask = None
        self._garden_fireflies = []
        self._garden_firefly_spawn = 0

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

    # ------------------------------------------------------------------ #
    #  Waveform visualizer — mic input vs. time
    # ------------------------------------------------------------------ #

    def _draw_waveform(self):
        """Horizontal oscilloscope: mic amplitude across the screen, time
        left → right. Reads pitch stability and tone color at a glance."""
        import time as _time
        scope = self.scope
        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()
        scope.delete("trace")

        cx, cy, r = scope.get_draw_area()
        # Use mic samples from the engine. get_lissajous_data returns
        # (ref, mic) — we just need mic for the waveform.
        max_pts = self.scope_points.get()
        _ref, mic = self.engine.get_lissajous_data(
            note_freq(self.root_note, self.octave),
            num_points=max_pts * 4,
        )
        mic_max = np.max(np.abs(mic))
        if mic_max > 0.001:
            mic = mic / mic_max
        else:
            mic = np.zeros_like(mic)

        n = len(mic)
        step = max(1, n // max_pts)
        mic = mic[::step]
        n = len(mic)

        # Map samples to canvas: x evenly across [cx-r, cx+r], y centered
        # around cy with amplitude scaled to ~70% of the radius so peaks
        # don't graze the bezel.
        xs = np.linspace(cx - r * 0.92, cx + r * 0.92, n)
        ys = cy - mic * (r * 0.7)
        points = np.empty(n * 2)
        points[0::2] = xs
        points[1::2] = ys
        pts = points.tolist()

        phosphor_bright, phosphor_mid, _phosphor_dim = self._get_phosphor()
        thickness = self.scope_thickness.get()

        # Subtle center line so silence reads as a flat line, not nothing.
        scope.create_line(
            cx - r * 0.92, cy, cx + r * 0.92, cy,
            fill=phosphor_mid, width=1, tags="trace",
        )
        if len(pts) > 4:
            scope.create_line(
                *pts, fill=phosphor_bright, width=thickness, tags="trace",
            )
        scope.draw_mask()

    # ------------------------------------------------------------------ #
    #  Spectrum visualizer — FFT bars of mic input
    # ------------------------------------------------------------------ #

    SPECTRUM_NUM_BARS = 32

    def _draw_spectrum(self):
        """FFT magnitude bars over a log frequency axis. Shows harmonic
        balance while you play against the drone — clean tone vs.
        airy / overtone-rich vs. saturated all read distinctly.

        Performance: the bar rectangles + cap lines are created once
        and updated via ``.coords()`` on every frame. delete+recreate
        of dozens of canvas items per frame is the dominant cost in
        Tk's canvas; persistent items keep the spectrum running at
        the same 60 fps as the Lissajous mode.
        """
        scope = self.scope
        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()
        scope.delete("trace")

        cx, cy, r = scope.get_draw_area()
        phosphor_bright, phosphor_mid, _phosphor_dim = self._get_phosphor()
        num_bars = self.SPECTRUM_NUM_BARS

        band_left = cx - r * 0.85
        band_right = cx + r * 0.85
        baseline = cy + r * 0.55
        max_height = r * 1.05
        bar_w = (band_right - band_left) / num_bars

        # Lazily create the persistent canvas items the first time we
        # draw, or after a mode switch wiped them.
        if len(self._spectrum_items) != num_bars:
            scope.delete("bars")
            self._spectrum_items = []
            for i in range(num_bars):
                rect_id = scope.create_rectangle(
                    0, 0, 0, 0,
                    fill=phosphor_mid, outline="", tags="bars",
                )
                cap_id = scope.create_line(
                    0, 0, 0, 0,
                    fill=phosphor_bright, width=1, tags="bars",
                )
                self._spectrum_items.append((rect_id, cap_id))
        else:
            # Repaint in case the phosphor color setting changed.
            for rect_id, cap_id in self._spectrum_items:
                scope.itemconfigure(rect_id, fill=phosphor_mid)
                scope.itemconfigure(cap_id, fill=phosphor_bright)

        # Pull a chunk of mic data via the engine helper.
        _ref, mic = self.engine.get_lissajous_data(
            note_freq(self.root_note, self.octave),
            num_points=2048,
        )
        n = len(mic)
        if n < 64 or np.max(np.abs(mic)) < 0.001:
            # Silence — flatten every bar to the baseline.
            for rect_id, cap_id in self._spectrum_items:
                scope.coords(rect_id, 0, baseline, 0, baseline)
                scope.coords(cap_id, 0, baseline, 0, baseline)
            scope.draw_mask()
            return

        # FFT magnitude. Hann window first so leakage doesn't smear
        # single tones into adjacent bins.
        window = np.hanning(n)
        spectrum = np.abs(np.fft.rfft(mic * window))
        freqs = np.fft.rfftfreq(n, 1.0 / self.engine.sr)

        # Log frequency axis from 60 Hz to 4 kHz — wide enough for any
        # sax / wind / vocal fundamental + a few harmonics, tight
        # enough to give each bar visible width.
        f_lo, f_hi = 60.0, 4000.0
        log_edges = np.logspace(np.log10(f_lo), np.log10(f_hi), num_bars + 1)

        # Vectorized bucketing: np.digitize maps each bin to its bar
        # index in one C call, then np.maximum.reduceat collapses each
        # contiguous run of bins into a single max. Faster than the
        # 32-iteration Python loop the previous version used.
        bar_idx = np.digitize(freqs, log_edges) - 1
        valid = (bar_idx >= 0) & (bar_idx < num_bars)
        if not np.any(valid):
            scope.draw_mask()
            return
        bar_mags = np.zeros(num_bars)
        for i in range(num_bars):
            sel = bar_idx == i
            if np.any(sel):
                bar_mags[i] = spectrum[sel].max()

        # Normalize and apply a soft sqrt curve so quiet partials are
        # visible without the fundamental pinning the top.
        max_mag = bar_mags.max() if bar_mags.max() > 0 else 1.0
        bar_mags = np.sqrt(bar_mags / max_mag)

        # Update bar positions via .coords() — no allocations.
        for i, m in enumerate(bar_mags):
            x0 = band_left + i * bar_w + 1
            x1 = band_left + (i + 1) * bar_w - 1
            y0 = baseline - m * max_height
            rect_id, cap_id = self._spectrum_items[i]
            scope.coords(rect_id, x0, y0, x1, baseline)
            scope.coords(cap_id, x0, y0, x1, y0)

        scope.draw_mask()

    # ------------------------------------------------------------------ #
    #  Warp visualizer — Geiss-style feedback / MilkDrop vibes
    # ------------------------------------------------------------------ #

    def _draw_warp(self):
        """Frame-to-frame feedback warp. Each frame the previous frame
        is zoomed slightly outward + brightness-decayed, then new
        audio-driven content is painted on top. The result is a
        recursive, hypnotic visualization that responds to amplitude
        + pitch + harmonic content. Ryan Geiss / MilkDrop vibes,
        without the GPU shader stack."""
        if not _HAS_PIL:
            return

        scope = self.scope
        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()
        scope.delete("trace")
        scope.delete("bars")

        cx, cy, r = scope.get_draw_area()
        N = self._warp_size
        center = N // 2

        # ---- Lazy framebuffer setup ----
        if self._warp_buffer is None:
            self._warp_buffer = np.zeros((N, N, 3), dtype=np.uint8)

        # ---- Pull a chunk of audio for this frame's reactivity ----
        _ref, mic = self.engine.get_lissajous_data(
            note_freq(self.root_note, self.octave),
            num_points=1024,
        )
        if len(mic) == 0:
            mic = np.zeros(64, dtype=np.float32)
        amp = float(np.sqrt(np.mean(mic * mic))) if len(mic) else 0.0
        peak = float(np.max(np.abs(mic))) if len(mic) else 0.0

        # ---- Feedback step: zoom prev frame slightly outward + decay ----
        # PIL's resize is C-implemented and very fast. We resize the
        # buffer up by a few pixels then crop back to N×N, which makes
        # everything march outward from the center — the classic
        # feedback "tunnel" effect. Decay multiplier dims the previous
        # frame so old content gradually fades rather than persisting
        # forever.
        prev = Image.fromarray(self._warp_buffer, mode="RGB")
        zoom_px = max(3, int(3 + amp * 12))
        zoomed = prev.resize((N + zoom_px, N + zoom_px), Image.BILINEAR)
        off = zoom_px // 2
        prev = zoomed.crop((off, off, off + N, off + N))
        # Decay: multiply the array. 0.94 leaves a smooth trail; lower
        # makes it fade quicker. The np path is faster than ImageEnhance.
        arr = np.asarray(prev, dtype=np.uint16)
        arr = (arr * 240) >> 8   # ≈ ×0.9375, integer-only, fast
        arr = arr.astype(np.uint8)

        # ---- Paint new audio-driven content ----
        img = Image.fromarray(arr, mode="RGB")
        draw = ImageDraw.Draw(img)

        phosphor_bright, phosphor_mid, _phosphor_dim = self._get_phosphor()
        # Convert hex -> RGB tuple once per frame.
        def _hex_to_rgb(h):
            h = h.lstrip('#')
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        bright_rgb = _hex_to_rgb(phosphor_bright)
        mid_rgb = _hex_to_rgb(phosphor_mid)

        # Advance phase. The visible spirograph-ish pattern is driven
        # by self._warp_t scaling against the detected pitch and audio
        # phase. Slower advance = slower rotation.
        self._warp_t += 0.06 + amp * 0.4

        # Radius modulated by amplitude — louder = larger figures.
        base_r = N * 0.18 + amp * N * 0.35
        # Number of audio "petals" drawn this frame. Always at least
        # a few so silence still has a faint pulse; scales up with
        # signal strength.
        n_petals = 6 + int(peak * 30)

        for i in range(n_petals):
            phase = self._warp_t + i * (2 * np.pi / n_petals)
            # Outer point
            x = center + base_r * np.cos(phase)
            y = center + base_r * np.sin(phase)
            # Sub-point swept by a faster phase — creates the
            # interweaving spirograph look.
            sub_phase = self._warp_t * 1.7 + i * 0.5
            x2 = center + base_r * 0.55 * np.cos(sub_phase)
            y2 = center + base_r * 0.55 * np.sin(sub_phase)
            # Line between them. Bright fill on top of the decayed
            # backdrop blooms over successive frames as the warp
            # smears it outward.
            draw.line([(x, y), (x2, y2)], fill=bright_rgb, width=2)
            # Single dot at the outer point for accent.
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=bright_rgb)

        # Center pulse — a soft fill that catches amplitude beats.
        pulse_r = 3 + amp * 12
        draw.ellipse(
            [center - pulse_r, center - pulse_r,
             center + pulse_r, center + pulse_r],
            fill=mid_rgb,
        )

        # ---- Store back to buffer + push to canvas ----
        self._warp_buffer = np.asarray(img, dtype=np.uint8)

        # Resize to the scope's inner draw area. NEAREST keeps it
        # cheap; the warp's natural softness hides the blockiness.
        display_size = int(r * 2 * 0.95)
        display_img = img.resize((display_size, display_size), Image.BILINEAR)
        # Round off the corners with a circular alpha mask so the
        # square image doesn't protrude past the CRT bezel.
        mask = self._get_garden_circle_mask(display_size)
        rgba = display_img.convert("RGBA")
        rgba.putalpha(mask)
        self._warp_photo = ImageTk.PhotoImage(rgba)
        if self._warp_canvas_item is None:
            self._warp_canvas_item = scope.create_image(
                cx, cy, image=self._warp_photo, tags="warp",
            )
        else:
            scope.itemconfigure(self._warp_canvas_item, image=self._warp_photo)
            scope.coords(self._warp_canvas_item, cx, cy)

        scope.draw_mask()
        # Make sure the warp image sits beneath the bezel ring (which
        # draw_mask raises) but above the graticule so the audio
        # content isn't fighting with the grid.
        try:
            scope.tag_raise("warp", "graticule")
            scope.tag_raise("bezel_ring", "warp")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Waterfall visualizer — 3D spectrum, flying over a mountain range
    # ------------------------------------------------------------------ #

    WATERFALL_NUM_ROWS = 50
    WATERFALL_NUM_BARS = 40

    def _draw_waterfall(self):
        """Rolling stack of FFT frames drawn with perspective. The
        newest spectrum lands at the front of the screen; each frame
        every previous spectrum gets pushed back and shrunk + raised
        toward a vanishing point. Result reads as a 3D landscape
        flying past — the Geiss / MilkDrop waterfall-spectrum mode.

        Each row also remembers the hue it was created at, so the
        slow color cycle reads through the historical depth: front
        rows are recent colors, back rows are older colors."""
        scope = self.scope
        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()
        scope.delete("trace")
        scope.delete("bars")

        cx, cy, r = scope.get_draw_area()
        N_ROWS = self.WATERFALL_NUM_ROWS
        N_BARS = self.WATERFALL_NUM_BARS

        # Lazy first-time setup. Pre-fill the row buffer with flat
        # zero rows so the data structure is always full size, and
        # create one persistent canvas line per depth slot.
        if not self._waterfall_lines:
            for _ in range(N_ROWS):
                self._waterfall_rows.append((np.zeros(N_BARS), "#000000"))
            for _ in range(N_ROWS):
                line_id = scope.create_line(
                    0, 0, 0, 0, fill="#000000", width=1, tags="waterfall",
                )
                self._waterfall_lines.append(line_id)

        # ---- Compute new spectrum ----
        _ref, mic = self.engine.get_lissajous_data(
            note_freq(self.root_note, self.octave),
            num_points=1024,
        )
        new_row = np.zeros(N_BARS)
        if len(mic) >= 64 and np.max(np.abs(mic)) > 0.001:
            n = len(mic)
            window = np.hanning(n)
            spectrum = np.abs(np.fft.rfft(mic * window))
            freqs = np.fft.rfftfreq(n, 1.0 / self.engine.sr)
            f_lo, f_hi = 60.0, 4000.0
            log_edges = np.logspace(np.log10(f_lo), np.log10(f_hi), N_BARS + 1)
            bar_idx = np.digitize(freqs, log_edges) - 1
            for i in range(N_BARS):
                sel = bar_idx == i
                if np.any(sel):
                    new_row[i] = spectrum[sel].max()
            max_mag = new_row.max() if new_row.max() > 0 else 1.0
            new_row = np.sqrt(new_row / max_mag)

        # ---- Advance hue cycle ----
        # ~0.4° per frame at 60fps = full color wheel every ~150 frames
        # (~2.5s). Slow enough to read through the mountain range
        # rather than strobe.
        self._waterfall_hue = (self._waterfall_hue + 0.0011) % 1.0
        new_color = self._hsv_to_hex(self._waterfall_hue, 0.95, 1.0)

        # ---- Push new row, evict oldest ----
        self._waterfall_rows.insert(0, (new_row, new_color))
        if len(self._waterfall_rows) > N_ROWS:
            self._waterfall_rows.pop()

        # ---- Render all rows with perspective ----
        # Iterate back-to-front so newer rows draw on top of older
        # ones — gives the correct occlusion for the mountain-range
        # look.
        baseline_y = cy + r * 0.55
        vanish_y = cy - r * 0.55
        front_half_width = r * 0.92
        back_half_width = r * 0.18      # the vanishing-line width
        front_height = r * 0.75         # tallest peak at the front
        back_height = r * 0.15          # tallest peak at the back

        for depth_from_back in range(N_ROWS):
            # depth_from_back: 0 = oldest (back), N_ROWS-1 = newest (front)
            front_depth = N_ROWS - 1 - depth_from_back
            row_mags, row_color = self._waterfall_rows[front_depth]
            line_id = self._waterfall_lines[front_depth]
            z = front_depth / max(1, N_ROWS - 1)  # 0 = newest, 1 = oldest

            # Perspective: as z grows, the row narrows and rises.
            # A small ease so the front rows feel more pronounced.
            z_eased = z ** 0.8
            row_half_width = front_half_width + (back_half_width - front_half_width) * z_eased
            row_y_base = baseline_y + (vanish_y - baseline_y) * z_eased
            row_height = front_height + (back_height - front_height) * z_eased

            x_step = (2 * row_half_width) / max(1, N_BARS - 1)
            coords = []
            for i, m in enumerate(row_mags):
                x = cx - row_half_width + i * x_step
                y = row_y_base - m * row_height
                coords.append(x)
                coords.append(y)

            try:
                scope.coords(line_id, *coords)
                scope.itemconfigure(line_id, fill=row_color)
            except tk.TclError:
                pass

        scope.draw_mask()
        # Sit the waterfall above the graticule but below the bezel
        # ring so the round mask still trims the edges.
        try:
            scope.tag_raise("waterfall", "graticule")
            scope.tag_raise("bezel_ring", "waterfall")
        except Exception:
            pass

    @staticmethod
    def _hsv_to_hex(h, s, v):
        """HSV (0..1 each) → #RRGGBB hex string."""
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"

    # ------------------------------------------------------------------ #
    #  Garden visualizer — branching audio-driven plants
    # ------------------------------------------------------------------ #

    # Tuning constants. Lifted out so the values are easy to tweak when
    # we see how the plants actually grow in real playing.
    GARDEN_PLANT_BASE_SPEED = 0.45      # pixels/frame for a fresh main stem
    GARDEN_PLANT_BASE_WIDTH = 22.0      # rib extent (pixels) for a main stem
    GARDEN_PLANT_BASE_LIFE = 400        # frames a main stem can live
    GARDEN_DEPTH_DECAY_SPEED = 0.78     # each generation = this × parent's speed
    GARDEN_DEPTH_DECAY_WIDTH = 0.62     # each generation = this × parent's width
    GARDEN_DEPTH_DECAY_LIFE = 0.55      # each generation = this × parent's life
    GARDEN_MAX_DEPTH = 4                # generations before a tip stops branching
    GARDEN_GOLDEN_ANGLE = 137.5077640500378 * (np.pi / 180.0)  # radians
    GARDEN_BRANCH_FAN = 28 * (np.pi / 180.0)  # ± angle of children from parent
    GARDEN_HUE_PER_FRAME = 0.00045      # slow rainbow cycle for the ribbon
    GARDEN_LEAF_INTERVAL = 22           # avg frames between leaf drops on a branch
    GARDEN_LEAF_MIN_DEPTH = 1           # main stem doesn't get leaves; sub-branches do
    GARDEN_FIREFLY_CAP = 14             # max concurrent fireflies
    GARDEN_FIREFLY_BASE_RATE = 60       # base frames-per-spawn at silence
    GARDEN_FIREFLY_LIFE = 420           # frames a firefly lives (~7s at 60fps)
    # Flower shape vocabulary — each plant picks one species-style at
    # spawn time, so every flower on the plant matches and the garden
    # reads as a mix of species rather than a parade of identical
    # blooms.
    GARDEN_PETAL_SHAPES = ("round", "teardrop", "ray", "spade")
    GARDEN_PETAL_COUNTS = (3, 5, 5, 6, 7, 8, 9, 13)  # Fibonacci-weighted

    def _draw_garden(self):
        """Draw the audio-driven branching garden.

        Each plant is a tree of "branches"; each branch carries a print
        head that advances one step per frame and stamps the current FFT
        cross-section perpendicular to its growth direction. Branches
        split into 2 children on amplitude peaks, with child width /
        speed / life decayed (apical dominance) and rotated relative to
        the parent by ±GARDEN_BRANCH_FAN around a golden-angle-rotated
        axis (phyllotaxis). When all branches in a plant have died, a
        new plant seeds to the right; once the buffer fills, the whole
        canvas scrolls left treadmill-style.

        Persistent PIL framebuffer — once pixels are deposited they
        stay, so the visible plant is literally the accumulated record
        of every audio frame that built it.
        """
        if not _HAS_PIL:
            return
        scope = self.scope
        if not scope._bezel_drawn:
            scope.draw_bezel()
            scope.draw_graticule()
        scope.delete("trace")
        scope.delete("bars")

        cx, cy, r = scope.get_draw_area()
        N = self._garden_size

        # ---- Lazy buffer setup ----
        if self._garden_buffer is None:
            self._garden_buffer = Image.new("RGB", (N, N), (0, 0, 0))
        if not self._garden_plants:
            self._spawn_garden_plant()

        # ---- Pull audio features ----
        _ref, mic = self.engine.get_lissajous_data(
            note_freq(self.root_note, self.octave), num_points=1024,
        )
        if len(mic) >= 64:
            rms = float(np.sqrt(np.mean(mic * mic)))
            peak = float(np.max(np.abs(mic)))
            spectrum_bars, centroid_hz = self._garden_spectrum(mic)
        else:
            rms, peak = 0.0, 0.0
            spectrum_bars = np.zeros(self.GARDEN_NUM_BARS)
            centroid_hz = self._garden_centroid_smooth

        # Smooth the audio env so a single popping sample doesn't fire
        # spurious branches; smooth the centroid so the drift reads as
        # gentle leaning rather than jitter.
        self._garden_audio_env = 0.85 * self._garden_audio_env + 0.15 * rms
        self._garden_centroid_smooth = (
            0.96 * self._garden_centroid_smooth + 0.04 * centroid_hz
        )
        # Centroid → drift: warm/low (200-600 Hz) leans left, bright/high
        # (2000+ Hz) leans right. Mapped to ±0.15 rad/frame on the head
        # direction, gentle by design.
        cnorm = (np.log2(max(50.0, self._garden_centroid_smooth) / 100.0)
                 / np.log2(40.0))   # 0..1ish across 100 Hz..4 kHz
        drift = (cnorm - 0.5) * 0.06    # radians per frame, ± 0.03

        # Hue ticks forward regardless of playing — gives the garden a
        # slow rainbow signature so plants from different "eras" of the
        # session look distinguishable.
        self._garden_hue = (self._garden_hue + self.GARDEN_HUE_PER_FRAME) % 1.0
        hue_now = self._garden_hue

        # ---- Step every alive branch in the current plant ----
        draw = ImageDraw.Draw(self._garden_buffer)
        plant = self._garden_plants[-1]
        any_alive = False
        for branch in plant["branches"]:
            if not branch["alive"]:
                continue
            self._garden_step_branch(
                branch, draw, spectrum_bars, drift,
                self._garden_audio_env, hue_now, plant,
            )
            if branch["alive"]:
                any_alive = True

        # ---- Audio-triggered branching ----
        # Peak amplitude above a moving threshold AND not too recently
        # after the previous branch event = a new branching tick. We
        # split the currently-most-vigorous tip into 2 children.
        plant["frames_alive"] += 1
        frames_since_branch = plant["frames_alive"] - self._garden_last_branch_frame
        if (peak > 0.04
                and peak > 1.7 * self._garden_audio_env
                and frames_since_branch > 25
                and any_alive):
            self._garden_branch_tip(plant, hue_now)
            self._garden_last_branch_frame = plant["frames_alive"]

        # Volume modulates growth: louder play = branches advance
        # faster. Handled by multiplying speed inside _garden_step_branch.

        # ---- If current plant is finished, spawn a new one ----
        if not any_alive:
            self._spawn_garden_plant()
            # If we ran past the right edge, scroll the buffer left so
            # the new plant has room — treadmill mode kicks in.
            if self._garden_next_plant_x > N - 50:
                self._garden_scroll_left(int(N * 0.4))

        # ---- Fireflies (transient — not painted into the persistent
        # buffer so they don't leave trails). Step every active one,
        # spawn new ones based on a per-frame budget that's faster
        # when there's sustained playing.
        self._garden_step_fireflies(self._garden_audio_env)

        # ---- Push the buffer to the scope canvas ----
        # Composite fireflies onto a copy of the persistent buffer so
        # they're transient (no trails into the plant material). Then
        # resize to the scope's inner draw area and mask to a circle
        # so the corners don't poke past the bezel ring. The mask is
        # cached by size since the scope area doesn't change.
        composite = self._garden_buffer.copy()
        if self._garden_fireflies:
            self._garden_render_fireflies(composite)
        display_size = int(r * 2 * 0.95)
        display_img = composite.resize(
            (display_size, display_size), Image.BILINEAR,
        )
        mask = self._get_garden_circle_mask(display_size)
        # Compose onto a black RGBA so the masked-out corners are
        # transparent — the dark CRT screen underneath will show
        # through them.
        rgba = display_img.convert("RGBA")
        rgba.putalpha(mask)
        self._garden_photo = ImageTk.PhotoImage(rgba)
        if self._garden_canvas_item is None:
            self._garden_canvas_item = scope.create_image(
                cx, cy, image=self._garden_photo, tags="garden",
            )
        else:
            scope.itemconfigure(self._garden_canvas_item, image=self._garden_photo)
            scope.coords(self._garden_canvas_item, cx, cy)

        scope.draw_mask()
        try:
            scope.tag_raise("garden", "graticule")
            scope.tag_raise("bezel_ring", "garden")
        except Exception:
            pass

    GARDEN_NUM_BARS = 18

    def _get_garden_circle_mask(self, size):
        """Return a PIL 'L'-mode circular alpha mask sized `size×size`,
        cached so we don't rebuild it every frame."""
        if (self._garden_circle_mask is not None
                and self._garden_circle_mask.size == (size, size)):
            return self._garden_circle_mask
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse(
            [0, 0, size - 1, size - 1], fill=255,
        )
        self._garden_circle_mask = mask
        return mask

    def _garden_spectrum(self, mic):
        """Return (bars, centroid_hz). Bars are log-bucketed FFT mags,
        normalized 0..1. Centroid is amplitude-weighted mean frequency.
        """
        n = len(mic)
        if n < 64 or np.max(np.abs(mic)) < 0.0005:
            return np.zeros(self.GARDEN_NUM_BARS), self._garden_centroid_smooth
        window = np.hanning(n)
        spectrum = np.abs(np.fft.rfft(mic * window))
        freqs = np.fft.rfftfreq(n, 1.0 / self.engine.sr)
        f_lo, f_hi = 80.0, 4000.0
        # Spectral centroid (real Hz value).
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if np.any(mask) and spectrum[mask].sum() > 1e-6:
            centroid_hz = float(
                (freqs[mask] * spectrum[mask]).sum() / spectrum[mask].sum()
            )
        else:
            centroid_hz = self._garden_centroid_smooth
        # Log-bucketed bars for the rib profile.
        log_edges = np.logspace(np.log10(f_lo), np.log10(f_hi),
                                 self.GARDEN_NUM_BARS + 1)
        bar_idx = np.digitize(freqs, log_edges) - 1
        bars = np.zeros(self.GARDEN_NUM_BARS)
        for i in range(self.GARDEN_NUM_BARS):
            sel = bar_idx == i
            if np.any(sel):
                bars[i] = spectrum[sel].max()
        peak = bars.max() if bars.max() > 0 else 1.0
        bars = np.sqrt(bars / peak)   # soft curve, brings up quiet partials
        return bars, centroid_hz

    def _spawn_garden_plant(self):
        """Seed a new plant at the next garden slot."""
        N = self._garden_size
        x = self._garden_next_plant_x
        y = N - 8.0   # rooted near the bottom
        # Per-plant flower style — fixed for the lifetime of the plant
        # so all blooms on a single stem match like a real species.
        flower_style = {
            "n_petals": random.choice(self.GARDEN_PETAL_COUNTS),
            "shape": random.choice(self.GARDEN_PETAL_SHAPES),
            "petal_aspect": random.uniform(0.7, 1.8),     # outer-radial vs side width
            "center_ratio": random.uniform(0.25, 0.65),   # center disc / flower radius
            "petal_overlap": random.uniform(0.9, 1.25),   # >1 = petals overlap their neighbors
            "size_scale": random.uniform(0.85, 1.3),      # overall scale relative to branch width
            "center_hue_offset": random.choice([0.5, 0.5, 0.33, 0.17]),  # mostly complementary
            "petal_rotation": random.uniform(0.0, np.pi), # starting angle so flowers point varied directions
            "secondary_bloom_rate": random.choice([0.0, 0.0, 0.0008, 0.0015]),
        }
        plant = {
            "frames_alive": 0,
            "flower_style": flower_style,
            "branches": [{
                "x": x, "y": y,
                "angle": -np.pi / 2,    # straight up
                "speed": self.GARDEN_PLANT_BASE_SPEED,
                "width": self.GARDEN_PLANT_BASE_WIDTH,
                "life": self.GARDEN_PLANT_BASE_LIFE,
                "depth": 0,
                "age": 0,
                "alive": True,
                "rotation_index": 0,   # for golden-angle phyllotaxis
                "leaf_cooldown": self.GARDEN_LEAF_INTERVAL,
                "leaf_side": 1,        # alternates ±1 each drop
            }],
        }
        self._garden_plants.append(plant)
        # Keep the plant list bounded so we don't grow memory forever.
        if len(self._garden_plants) > 8:
            self._garden_plants.pop(0)
        # Step the next-plant cursor to the right.
        self._garden_next_plant_x += 40.0

    def _garden_step_branch(self, branch, draw, spectrum_bars, drift,
                            audio_env, hue, plant):
        """Advance one branch by one frame, stamping its rib."""
        # Aging + dominance check
        branch["age"] += 1
        if branch["age"] >= branch["life"]:
            # Reached natural end of life — bloom a flower at the tip
            # before dying. Tips that get killed by going off-canvas or
            # by being branched away don't flower; only natural deaths
            # do, so flowers visually mark the ends of branches that
            # got to grow to maturity.
            self._garden_draw_flower(branch, draw, hue, plant["flower_style"])
            branch["alive"] = False
            return

        # Direction curves with audio centroid drift, with a slight
        # bias upward (negative y) so branches don't run straight
        # sideways indefinitely.
        upward_bias = 0.0
        if abs(branch["angle"] + np.pi / 2) > 0.7:
            # Branch is tilted >40° off vertical — nudge back toward up
            upward_bias = -0.01 * np.sign(branch["angle"] + np.pi / 2)
        branch["angle"] += drift * (1.0 - 0.4 * branch["depth"]) + upward_bias

        # Speed scales with volume — louder = faster growth (Matt's ask)
        speed = branch["speed"] * (1.0 + 1.5 * audio_env)

        # Advance the print-head
        dx = np.cos(branch["angle"]) * speed
        dy = np.sin(branch["angle"]) * speed
        branch["x"] += dx
        branch["y"] += dy

        # Off-canvas check
        N = self._garden_size
        if (branch["x"] < 2 or branch["x"] > N - 2
                or branch["y"] < 2 or branch["y"] > N - 2):
            branch["alive"] = False
            return

        # Stamp the rib perpendicular to direction. The FFT bars define
        # the intensity profile across the rib width.
        perp_x = -np.sin(branch["angle"])
        perp_y = np.cos(branch["angle"])
        width = branch["width"]
        # Color: cycle through hue with saturation a bit lower than the
        # waterfall (plants look better with muted tones than pure
        # rainbow). Brightness ties to current audio so quiet playing
        # produces fainter pixels.
        bright = min(1.0, 0.45 + audio_env * 2.5)
        r_, g_, b_ = colorsys.hsv_to_rgb(hue, 0.78, bright)
        base_color = (int(r_ * 255), int(g_ * 255), int(b_ * 255))

        n_bars = self.GARDEN_NUM_BARS
        for i, mag in enumerate(spectrum_bars):
            # Symmetric profile: bar i maps to ±offset from centerline.
            offset_units = (i + 0.5) / n_bars   # 0..1
            for sign in (-1.0, 1.0):
                offset = sign * offset_units * (width * 0.5) * (0.4 + 0.6 * mag)
                px = branch["x"] + perp_x * offset
                py = branch["y"] + perp_y * offset
                # Intensity along the rib — peaks bright, valleys dim.
                inten = 0.35 + 0.65 * mag
                color = (
                    int(base_color[0] * inten),
                    int(base_color[1] * inten),
                    int(base_color[2] * inten),
                )
                # Composite over whatever's already there (max-blend
                # so we never DARKEN existing pixels — the plant only
                # gets brighter as more material accumulates).
                self._garden_set_pixel(px, py, color)

        # Also brighten the centerline so the stem reads clearly even
        # when the FFT happens to be quiet.
        stem_color = (
            int(base_color[0] * 0.9),
            int(base_color[1] * 0.9),
            int(base_color[2] * 0.9),
        )
        self._garden_set_pixel(branch["x"], branch["y"], stem_color)

        # Leaf drops — only for sub-branches (depth ≥ 1), so the main
        # stem stays clean. Cooldown decrements each frame and a leaf
        # is drawn on alternating sides when it hits zero.
        if branch["depth"] >= self.GARDEN_LEAF_MIN_DEPTH:
            branch["leaf_cooldown"] -= 1
            if branch["leaf_cooldown"] <= 0:
                self._garden_draw_leaf(branch, draw, hue)
                # Add a touch of jitter so leaves don't land at exact
                # multiples of the interval. ±25% of nominal.
                jitter = random.randint(-self.GARDEN_LEAF_INTERVAL // 4,
                                         self.GARDEN_LEAF_INTERVAL // 4)
                branch["leaf_cooldown"] = self.GARDEN_LEAF_INTERVAL + jitter
                branch["leaf_side"] *= -1

        # Secondary blooms — some plant species sprout extra flowers
        # along their branches mid-life, not just at the terminal tip.
        # The chance is set per-plant in flower_style and is zero for
        # most species (so terminal-only blooms remain the norm).
        sec_rate = plant["flower_style"].get("secondary_bloom_rate", 0.0)
        if (sec_rate > 0
                and branch["depth"] >= 1
                and branch["age"] > 12
                and random.random() < sec_rate):
            self._garden_draw_flower(branch, draw, hue, plant["flower_style"],
                                     scale=0.6)

    def _garden_draw_leaf(self, branch, draw, hue):
        """Paint a small teardrop-shaped leaf attached to the branch at
        its current print-head position, on the alternating side.

        Leaf orientation is roughly perpendicular to the branch
        direction, with the apex pointing slightly forward (toward the
        growth direction) so it looks like it's catching light. Size
        scales with branch width."""
        L = max(4.0, branch["width"] * 0.85)        # leaf length
        W = max(2.5, L * 0.55)                       # leaf max width
        # Perpendicular to branch, on the assigned side.
        perp_x = -np.sin(branch["angle"]) * branch["leaf_side"]
        perp_y = np.cos(branch["angle"]) * branch["leaf_side"]
        # Forward direction (along branch) — used to tilt the apex.
        fwd_x = np.cos(branch["angle"])
        fwd_y = np.sin(branch["angle"])
        # Base attaches at branch; tip extends outward + slightly forward.
        bx, by = branch["x"], branch["y"]
        tip_x = bx + perp_x * L + fwd_x * (L * 0.25)
        tip_y = by + perp_y * L + fwd_y * (L * 0.25)
        # Two side points define the teardrop's widest cross-section
        # at ~40% from the base.
        side_along_x = perp_x * (W * 0.5)
        side_along_y = perp_y * (W * 0.5)
        mid_x = bx + perp_x * (L * 0.4) + fwd_x * (L * 0.08)
        mid_y = by + perp_y * (L * 0.4) + fwd_y * (L * 0.08)
        # Polygon: base — mid+fwd-perp — tip — mid-fwd-perp — base.
        # The perpendicular split here creates the teardrop's pointed
        # tip and bulbous middle.
        leaf_perp_x = -np.sin(branch["angle"])
        leaf_perp_y = np.cos(branch["angle"])
        spread_x = leaf_perp_x * (W * 0.5)
        spread_y = leaf_perp_y * (W * 0.5)
        pts = [
            (bx, by),
            (mid_x + spread_x, mid_y + spread_y),
            (tip_x, tip_y),
            (mid_x - spread_x, mid_y - spread_y),
        ]
        # Color: green-leaning hue. Take the current hue and pull it
        # toward green by averaging with 0.33 (green in HSV space).
        leaf_hue = (hue * 0.4 + 0.33 * 0.6) % 1.0
        r_, g_, b_ = colorsys.hsv_to_rgb(leaf_hue, 0.75, 0.85)
        fill = (int(r_ * 255), int(g_ * 255), int(b_ * 255))
        # PIL.ImageDraw.polygon doesn't honor max-blend, so it'll
        # overwrite — for leaves that's fine, they sit on top of the
        # background ribbon.
        try:
            draw.polygon(pts, fill=fill, outline=fill)
        except Exception:
            pass

    def _garden_draw_flower(self, branch, draw, hue, style, scale=1.0):
        """Paint a bloom at the branch's current position using the
        plant's species-style (petal count, shape, aspect, center).

        `scale` lets the caller draw smaller secondary blooms along
        a branch's length without changing the species look.
        """
        cx_, cy_ = branch["x"], branch["y"]
        # Flower size scales with branch width AND the plant's
        # size_scale modifier AND the optional secondary-bloom scale.
        flower_r = max(4.0, branch["width"] * 0.9
                       * style.get("size_scale", 1.0)
                       * scale)
        n_petals = max(3, int(style.get("n_petals", 6)))
        shape = style.get("shape", "round")
        aspect = style.get("petal_aspect", 1.0)
        center_ratio = style.get("center_ratio", 0.4)
        overlap = style.get("petal_overlap", 1.0)
        rotation = style.get("petal_rotation", 0.0)
        center_hue_off = style.get("center_hue_offset", 0.5)

        # Petal sizing: outer "length" of each petal vs side "width".
        center_r = flower_r * center_ratio
        petal_len = (flower_r - center_r) * overlap
        # Side width sized so a "round" shape with aspect=1 reproduces
        # roughly the previous look.
        petal_w = petal_len / max(0.4, aspect)

        # Colors
        r_, g_, b_ = colorsys.hsv_to_rgb(hue, 0.85, 0.95)
        petal_color = (int(r_ * 255), int(g_ * 255), int(b_ * 255))
        rc, gc, bc = colorsys.hsv_to_rgb(
            (hue + center_hue_off) % 1.0, 0.85, 0.95,
        )
        center_color = (int(rc * 255), int(gc * 255), int(bc * 255))

        try:
            for i in range(n_petals):
                a = rotation + i * (2 * np.pi / n_petals)
                # Petal midpoint sits between center and the outer
                # circumference so the visible shape spans both sides.
                mid_dist = center_r + petal_len * 0.5
                px = cx_ + np.cos(a) * mid_dist
                py = cy_ + np.sin(a) * mid_dist
                self._draw_petal(draw, px, py, a, petal_len, petal_w,
                                  shape, petal_color, cx_, cy_, center_r)
            # Center disc on top of all petals
            draw.ellipse(
                [cx_ - center_r, cy_ - center_r,
                 cx_ + center_r, cy_ + center_r],
                fill=center_color, outline=center_color,
            )
        except Exception:
            pass

    def _draw_petal(self, draw, mid_x, mid_y, angle, length, width,
                    shape, color, center_x, center_y, center_r):
        """Paint a single petal centered at (mid_x, mid_y), pointing
        radially outward at `angle`. Different shapes produce visibly
        different plants."""
        # Unit vectors along the radial direction and perpendicular.
        rx, ry = np.cos(angle), np.sin(angle)
        px, py = -ry, rx

        # Inner anchor (closer to flower center) and outer tip.
        inner_x = center_x + rx * center_r
        inner_y = center_y + ry * center_r
        outer_x = center_x + rx * (center_r + length)
        outer_y = center_y + ry * (center_r + length)
        half_w = width * 0.5

        if shape == "round":
            # Bounding-box ellipse oriented radially. PIL's ellipse is
            # axis-aligned, so for non-trivial rotations we approximate
            # with a quad polygon — the radial direction is the long
            # axis, perpendicular is the short axis.
            pts = [
                (inner_x + px * half_w * 0.6, inner_y + py * half_w * 0.6),
                (outer_x + px * half_w * 0.5, outer_y + py * half_w * 0.5),
                (outer_x - px * half_w * 0.5, outer_y - py * half_w * 0.5),
                (inner_x - px * half_w * 0.6, inner_y - py * half_w * 0.6),
            ]
            draw.polygon(pts, fill=color, outline=color)
            # A little bulge at the tip — overdraws a small ellipse
            # axis-aligned, which reads as rounded since petals are
            # small.
            draw.ellipse(
                [outer_x - half_w * 0.5, outer_y - half_w * 0.5,
                 outer_x + half_w * 0.5, outer_y + half_w * 0.5],
                fill=color, outline=color,
            )
        elif shape == "teardrop":
            # Pointed at the OUTER end, wide at the inner end — opposite
            # of the leaf orientation.
            mid_along_x = center_x + rx * (center_r + length * 0.4)
            mid_along_y = center_y + ry * (center_r + length * 0.4)
            pts = [
                (inner_x + px * half_w, inner_y + py * half_w),
                (mid_along_x + px * half_w * 1.05, mid_along_y + py * half_w * 1.05),
                (outer_x, outer_y),
                (mid_along_x - px * half_w * 1.05, mid_along_y - py * half_w * 1.05),
                (inner_x - px * half_w, inner_y - py * half_w),
            ]
            draw.polygon(pts, fill=color, outline=color)
        elif shape == "ray":
            # Thin elongated rays — daisy / sunflower vibe.
            thin = half_w * 0.45
            pts = [
                (inner_x + px * thin, inner_y + py * thin),
                (outer_x + px * thin, outer_y + py * thin),
                (outer_x - px * thin, outer_y - py * thin),
                (inner_x - px * thin, inner_y - py * thin),
            ]
            draw.polygon(pts, fill=color, outline=color)
        elif shape == "spade":
            # Wider near the tip, narrow at the base — points outward
            # like a tulip / spade outline.
            mid_x_ = center_x + rx * (center_r + length * 0.65)
            mid_y_ = center_y + ry * (center_r + length * 0.65)
            pts = [
                (inner_x + px * half_w * 0.45, inner_y + py * half_w * 0.45),
                (mid_x_ + px * half_w * 1.15, mid_y_ + py * half_w * 1.15),
                (outer_x, outer_y),
                (mid_x_ - px * half_w * 1.15, mid_y_ - py * half_w * 1.15),
                (inner_x - px * half_w * 0.45, inner_y - py * half_w * 0.45),
            ]
            draw.polygon(pts, fill=color, outline=color)

    def _garden_set_pixel(self, x, y, color):
        """Max-blend a pixel into the garden buffer. Out-of-bounds is
        silently ignored."""
        if self._garden_buffer is None:
            return
        N = self._garden_size
        ix, iy = int(x), int(y)
        if 0 <= ix < N and 0 <= iy < N:
            existing = self._garden_buffer.getpixel((ix, iy))
            blended = (
                max(existing[0], color[0]),
                max(existing[1], color[1]),
                max(existing[2], color[2]),
            )
            self._garden_buffer.putpixel((ix, iy), blended)

    def _garden_branch_tip(self, plant, hue):
        """Find the most vigorous alive tip and split it into 2 children.

        Child angles: ± GARDEN_BRANCH_FAN from a parent-axis-rotated-by-
        golden-angle direction. The rotation_index advances each branch
        event so successive children spread around the parent rather
        than stacking on one side (phyllotaxis)."""
        # Pick the most vigorous tip (highest remaining life × width)
        alive = [b for b in plant["branches"] if b["alive"]]
        if not alive:
            return
        parent = max(alive, key=lambda b: (b["life"] - b["age"]) * b["width"])
        if parent["depth"] >= self.GARDEN_MAX_DEPTH:
            return

        # Phyllotaxis rotation index applied to the fan direction.
        rot = (parent["rotation_index"] + 1) * self.GARDEN_GOLDEN_ANGLE
        # We project the golden-angle rotation into 2D by treating it as
        # a small additional twist applied to the fan center.
        fan_center = parent["angle"] + 0.15 * np.sin(rot)

        children = []
        for sign in (-1.0, 1.0):
            child = {
                "x": parent["x"],
                "y": parent["y"],
                "angle": fan_center + sign * self.GARDEN_BRANCH_FAN,
                "speed": parent["speed"] * self.GARDEN_DEPTH_DECAY_SPEED,
                "width": parent["width"] * self.GARDEN_DEPTH_DECAY_WIDTH,
                "life": int(parent["life"] * self.GARDEN_DEPTH_DECAY_LIFE),
                "depth": parent["depth"] + 1,
                "age": 0,
                "alive": True,
                "rotation_index": parent["rotation_index"] + 1,
                "leaf_cooldown": self.GARDEN_LEAF_INTERVAL,
                "leaf_side": 1,
            }
            children.append(child)
        # The parent stops growing — its children carry the apex forward.
        # This is the apical-dominance trick: one main shoot at any given
        # depth, then it branches and the new shoots inherit the role.
        parent["alive"] = False
        plant["branches"].extend(children)

    def _garden_scroll_left(self, px):
        """Treadmill-scroll the garden buffer left by `px` pixels so a
        new plant has room on the right."""
        if self._garden_buffer is None:
            return
        N = self._garden_size
        shifted = Image.new("RGB", (N, N), (0, 0, 0))
        cropped = self._garden_buffer.crop((px, 0, N, N))
        shifted.paste(cropped, (0, 0))
        self._garden_buffer = shifted
        # Shift the active branches and the next-plant cursor along.
        for plant in self._garden_plants:
            for b in plant["branches"]:
                b["x"] -= px
                if b["x"] < 0:
                    b["alive"] = False
        self._garden_next_plant_x -= px
        # Drift fireflies along with the scroll so they don't appear to
        # snap relative to the garden under them.
        for ff in self._garden_fireflies:
            ff["x"] -= px

    def _garden_step_fireflies(self, audio_env):
        """Update positions, flicker phase, and lifetimes of all
        fireflies. Spawn new ones based on a per-frame budget that
        scales with sustained playing volume."""
        N = self._garden_size

        # Spawn — base rate at silence, faster when sustained playing
        # gives the audio envelope a nonzero floor.
        self._garden_firefly_spawn -= 1
        if self._garden_firefly_spawn <= 0:
            if len(self._garden_fireflies) < self.GARDEN_FIREFLY_CAP:
                self._spawn_garden_firefly()
            # Loudness shortens the spawn cooldown by up to 4×.
            rate = self.GARDEN_FIREFLY_BASE_RATE / max(0.25, 1.0 + audio_env * 6.0)
            self._garden_firefly_spawn = int(rate * random.uniform(0.6, 1.4))

        # Step
        alive = []
        for ff in self._garden_fireflies:
            ff["age"] += 1
            if ff["age"] >= ff["life"]:
                continue
            # Small random impulse + damping = brownian drift with
            # smoothness. Upward bias keeps fireflies from sinking out
            # the bottom over time.
            ff["vx"] = ff["vx"] * 0.92 + random.uniform(-0.18, 0.18)
            ff["vy"] = ff["vy"] * 0.92 + random.uniform(-0.18, 0.18) - 0.025
            ff["x"] += ff["vx"]
            ff["y"] += ff["vy"]
            ff["phase"] += ff["flicker_rate"]
            # Kill if it wandered out of bounds.
            if (ff["x"] < -4 or ff["x"] > N + 4
                    or ff["y"] < -4 or ff["y"] > N + 4):
                continue
            alive.append(ff)
        self._garden_fireflies = alive

    def _spawn_garden_firefly(self):
        """Drop a new firefly at a random point in the upper 60% of the
        canvas."""
        N = self._garden_size
        ff = {
            "x": random.uniform(20, N - 20),
            "y": random.uniform(N * 0.10, N * 0.65),
            "vx": random.uniform(-0.3, 0.3),
            "vy": random.uniform(-0.15, 0.05),
            "phase": random.uniform(0, 2 * np.pi),
            "flicker_rate": random.uniform(0.10, 0.20),
            "age": 0,
            "life": int(self.GARDEN_FIREFLY_LIFE * random.uniform(0.7, 1.2)),
            "hue": random.uniform(0.11, 0.18),    # narrow yellow-green band
        }
        self._garden_fireflies.append(ff)

    def _garden_render_fireflies(self, target_img):
        """Paint every alive firefly onto `target_img` (the per-frame
        composite). Each firefly is a 3-layer glow stack: bright core,
        mid halo, dim outer halo — same trick the motor pilot uses.
        Brightness modulates with the flicker phase and a fade in/out
        at the start and end of life."""
        draw = ImageDraw.Draw(target_img)
        for ff in self._garden_fireflies:
            # Flicker: sine wave around a mid brightness.
            flick = 0.55 + 0.45 * np.sin(ff["phase"])
            # Lifetime fade — first 30 frames fade in, last 30 fade out.
            fade_in = min(1.0, ff["age"] / 30.0)
            fade_out = min(1.0, (ff["life"] - ff["age"]) / 30.0)
            life_env = max(0.0, min(fade_in, fade_out))
            intensity = flick * life_env
            if intensity < 0.05:
                continue
            x, y = ff["x"], ff["y"]
            # Three concentric layers like the motor pilot's glow stack.
            for radius, weight in ((2.6, 0.35), (1.6, 0.65), (0.8, 1.0)):
                a = intensity * weight
                # Hue → RGB at the firefly's own warm yellow-green.
                r_, g_, b_ = colorsys.hsv_to_rgb(ff["hue"], 0.65, a)
                color = (int(r_ * 255), int(g_ * 255), int(b_ * 255))
                if color == (0, 0, 0):
                    continue
                try:
                    draw.ellipse(
                        [x - radius, y - radius, x + radius, y + radius],
                        fill=color, outline=color,
                    )
                except Exception:
                    pass

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


# ----- Sample recording dialog -----

class RecordSampleDialog(tk.Toplevel):
    """Modal-ish recording window. Tells the audio engine to start
    capturing input frames on open, polls the elapsed-duration counter
    while open, and on Stop installs the captured audio as the engine's
    drone sample. Cancel discards the capture.

    A 1.5-second hold-off after open before the Stop button arms,
    so a quick double-click on "Record New" can't immediately stop
    a recording that just started.
    """

    HOLD_OFF_MS = 1500

    def __init__(self, parent, engine, on_complete=None):
        super().__init__(parent)
        self.engine = engine
        self._on_complete = on_complete
        self._stopped = False

        self.title("Record drone sample")
        self.configure(bg=COLOR_CHASSIS)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        body = tk.Frame(self, bg=COLOR_CHASSIS, padx=24, pady=20)
        body.pack()

        tk.Label(
            body, text="● RECORDING", font=("Helvetica", 18, "bold"),
            fg=COLOR_RED, bg=COLOR_CHASSIS,
        ).pack(pady=(0, 4))

        tk.Label(
            body, text=(
                "Hold a single sustained note — a long tone or drone.\n"
                "Aim for at least 2 seconds. Click Stop & Use when done."
            ),
            font=("Helvetica", 9), fg=COLOR_CREAM_DIM, bg=COLOR_CHASSIS,
            justify="center",
        ).pack(pady=(0, 10))

        self.time_label = tk.Label(
            body, text="0.0 s", font=("Courier", 22, "bold"),
            fg=COLOR_AMBER, bg=COLOR_CHASSIS,
        )
        self.time_label.pack(pady=(0, 12))

        btns = tk.Frame(body, bg=COLOR_CHASSIS)
        btns.pack(pady=(4, 0))

        self.stop_btn = tk.Button(
            btns, text="Stop & Use", width=12,
            font=("Helvetica", 10, "bold"),
            bg="#2e5c30", fg=COLOR_GREEN,
            activebackground="#3a7a3c", activeforeground=COLOR_GREEN,
            relief="flat", bd=0, cursor="hand2",
            state="disabled",
            command=self._on_stop_and_use,
        )
        self.stop_btn.pack(side="left", padx=4)

        cancel_btn = tk.Button(
            btns, text="Cancel", width=12,
            font=("Helvetica", 10),
            bg=COLOR_BEZEL, fg=COLOR_CREAM,
            activebackground="#444444", activeforeground=COLOR_CREAM,
            relief="flat", bd=0, cursor="hand2",
            command=self._on_cancel,
        )
        cancel_btn.pack(side="left", padx=4)

        # Kick off the recording. The dialog's poll loop reads the
        # elapsed duration from the engine and updates the label.
        self.engine.record_start()
        self.after(self.HOLD_OFF_MS, self._arm_stop)
        self.after(50, self._poll)

    def _arm_stop(self):
        try:
            self.stop_btn.config(state="normal")
        except tk.TclError:
            pass

    def _poll(self):
        if self._stopped:
            return
        try:
            dur = self.engine.recorded_duration_s()
            self.time_label.config(text=f"{dur:.1f} s")
        except Exception:
            pass
        self.after(50, self._poll)

    def _on_stop_and_use(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            info = self.engine.record_stop_and_use()
        except Exception as e:
            messagebox.showerror(
                "Recording failed",
                f"Something went wrong saving the recording:\n\n{e}",
                parent=self,
            )
            info = None
        self.destroy()
        if self._on_complete:
            self._on_complete(info)

    def _on_cancel(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            self.engine.record_cancel()
        except Exception:
            pass
        self.destroy()
        if self._on_complete:
            self._on_complete(None)
