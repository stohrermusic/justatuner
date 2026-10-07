"""Concise in-app user guide for JustATuner.

One scrollable Toplevel with two sections, one per tab. Plain text,
short paragraphs. Content lives here (not in a README) so users can
read it without leaving the app.
"""

import tkinter as tk
from tkinter import ttk


GUIDE_BG = "#1a1a1a"
GUIDE_FG = "#ddd0b8"
GUIDE_HEADING = "#c89040"
GUIDE_DIM = "#7a7060"


SECTIONS = [
    ("Stroboscopic Tuner", [
        "12 spinning wheels, one per chromatic pitch class. When you "
        "play a note, the wheel for that note effectively stands still "
        "— it drifts right if you're sharp, left if you're flat.",
        "",
        "The wheel has seven concentric rings, one per octave. The "
        "ring matching the octave you're playing lights up brightly; "
        "the other rings stay dim. This lets the same display work "
        "for low bari notes and high soprano notes without changing "
        "anything.",
        "",
        "Read the strobe like this: locked = perfectly in tune. "
        "Drifting one stripe per second ≈ 1 cent off. The faster the "
        "drift, the further out of tune.",
        "",
        "Controls:",
        "  • SENS: input sensitivity. Raise it if a faint note isn't "
        "lighting any wheel; lower it if room noise lights wheels you "
        "didn't play.",
        "  • BRIGHT: overall display brightness.",
        "  • FPS: refresh rate. 60 fps is fine on any laptop; 90 or "
        "120 is smoother if your machine can handle it.",
        "  • A=: reference pitch. 440 Hz is standard; some ensembles "
        "tune to 441 or 442.",
        "  • KEY: transposition. Pick your horn's key and the wheel "
        "labels switch to written pitch (e.g. tenor in B♭ shows D "
        "when you play concert C).",
        "  • NOTE bias (per-wheel): shifts individual pitch classes a "
        "few cents for systematic intonation adjustments.",
        "  • OCT bias (per-ring): shifts each octave's reference, "
        "useful when an instrument's octaves drift.",
        "",
        "Tip: the VU meter on the right shows the closest pitch class "
        "and how flat / sharp you are. Use it for quick check-ins; "
        "use the wheels for the fine work.",
    ]),
    ("Just Intonation Drone", [
        "Plays a drone in any root note. You play along; the meter "
        "shows you the just-intonation interval you're hitting and "
        "how close it is to perfect.",
        "",
        "Just intonation tunes intervals to whole-number frequency "
        "ratios — a major third is 5:4, a perfect fifth is 3:2, and "
        "so on. Equal temperament (what pianos use) is a compromise "
        "that lets you play in any key but makes every interval "
        "slightly out. Locking to JI against a drone trains your ear "
        "to hear the difference.",
        "",
        "How to use it:",
        "  • Set ROOT to the key you want to practice in. The drone "
        "plays that note continuously.",
        "  • Flip the DRONE switch to ON. Adjust VOL so it sits "
        "comfortably under your playing.",
        "  • Play notes against the drone. The big display names the "
        "interval you're hitting (Major 3rd, Perfect 5th, etc.) and "
        "the meter shows cents off.",
        "  • LOCKED means you're within 5 cents of perfect JI. The "
        "meter turns green. Yellow = close, red = work to do.",
        "",
        "Sound / voicing (Drone menu): try the major or minor triad "
        "voicings to practice locking thirds and fifths against a "
        "stable chord.",
        "",
        "Octave: which octave the drone plays in. Lower octaves (2-3) "
        "are easier to lock against; higher (4-5) work for ear "
        "training in the playing range.",
        "",
        "Transpose: same as the tuner — shifts the note labels to "
        "match your horn's key.",
        "",
        "Visualizers (Options > Visualizer > Mode): six ways to see "
        "what's happening on the round green CRT:",
        "  • Lissajous (default) — interference between your note and "
        "the drone. A stable shape = the ratio is locked. A spinning "
        "shape = close but not exact. A blur = far off.",
        "  • Waveform — classic oscilloscope, mic input across the "
        "screen. Reads pitch stability and tone color at a glance.",
        "  • Spectrum — FFT bars showing your harmonic balance while "
        "you play against the drone. Watch how clean / airy / "
        "saturated your tone reads.",
        "  • Waterfall — rolling 3D spectrum. Each FFT frame lands at "
        "the front and gets pushed back toward a vanishing point as "
        "the next frame arrives, so what builds up reads as a "
        "landscape flying past. Colors cycle slowly through the rainbow "
        "so older mountains carry the hue they were born with. The "
        "Geiss / MilkDrop waterfall mode in tk.",
        "  • Warp — feedback visualization in the Ryan Geiss / "
        "MilkDrop tradition. Each frame zooms slightly outward and "
        "fades the previous one while painting new audio-reactive "
        "shapes on top, so what you see is a recursive blooming "
        "pattern that pulses with your playing. Not analytical — "
        "just a hypnotic backdrop for long practice sessions.",
        "  • Garden (beta) — branching plants that grow as you play. "
        "Each branch is a print head that stamps the current FFT "
        "cross-section perpendicular to its growth direction; "
        "amplitude peaks trigger branch splits (L-system style); "
        "spectral centroid drives a slow lateral drift so warm "
        "playing leans one way and bright playing the other. "
        "Sub-branches drop teardrop leaves on alternating sides; "
        "branches that reach maturity bloom flowers at their tips, "
        "with each plant rolling its own species-style (petal count, "
        "shape, center size) at spawn time. Yellow-green fireflies "
        "drift above the garden, spawning faster when you sustain "
        "notes. When one plant matures a new one seeds beside it, "
        "and once the canvas fills, the garden treadmills along to "
        "make room. Marked beta because the visual tuning will keep "
        "evolving as we use it.",
        "",
        "Show ET Difference: when on, the meter shows how far the "
        "just-intonation interval sits from equal temperament. Useful "
        "for understanding why some intervals (like the JI major "
        "third) feel different from the piano version.",
    ]),
    ("Progressions", [
        "The drone can move through a chord progression on its own, so "
        "you practise intonation while the harmony changes under you. "
        "Drone > Progression... opens the editor; the PROG row under the "
        "DRONE switch starts, stops and skips.",
        "",
        "Pick a preset (I-IV-V-I, ii-V-I, a twelve-bar blues, the cycle "
        "of fifths...) or type your own: a root letter with # or b, a "
        "chord type, and an optional :length, separated by bars. For "
        "example  C | F | G7:2 | Am. Chord types: nothing for major, m, "
        "7 (the harmonic seventh, 7:4), maj7, m7, sus4, sus2, dim, aug, "
        "1 for the root alone, 5 for root and fifth. The pickers add a "
        "chord to the line for you. Save keeps it under its name; Use "
        "puts it on the tab.",
        "",
        "Timing: bars at a tempo (each chord's length is in bars), "
        "seconds per chord, or manual, where a key you choose advances "
        "to the next chord whenever you are ready (default: the space "
        "bar; click the key button in the editor and press the key you "
        "want). Timed modes give you a one-bar or two-second count-in; "
        "the PROG row shows the current chord, the next one, and the "
        "time left. Chords are shown in your written key when TRANSPOSE "
        "is set.",
        "",
        "With speakers (Exerciser Options > Monitoring), starting a "
        "progression first sounds each chord once while the app listens "
        "to the room, a few seconds per chord, then plays through with "
        "no further pauses. Stay quiet during that part. A chord the "
        "app has already heard in this session needs no second listen.",
    ]),
    ("General", [
        "Only one tab uses the microphone at a time. Switching tabs "
        "hands the mic from one engine to the other.",
        "",
        "Input device: pick a specific mic from the Input menu in "
        "either tab.",
        "",
        "Speakers or headphones (Exerciser Options > Monitoring): with "
        "speakers, the drone leaks into the mic, so whenever the drone "
        "starts or changes note the app listens to the room for a few "
        "seconds (the DRONE status says so) and then cancels the drone "
        "from what the mic hears. Stay quiet during the listen. With "
        "headphones there is nothing to cancel, so choose Headphones "
        "and there is no listen at all. A WAV-sample drone can't be "
        "cancelled this way; use headphones with it.",
        "",
        "Settings persist between sessions in app_settings.json "
        "under your platform's config directory (%APPDATA%, "
        "~/Library/Application Support, or ~/.config).",
    ]),
]


def open_user_guide(root):
    """Open the user guide. Reuses an existing window if one is open."""
    if getattr(open_user_guide, "_existing", None) is not None:
        try:
            existing = open_user_guide._existing
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        except tk.TclError:
            open_user_guide._existing = None

    top = tk.Toplevel(root)
    top.title("JustATuner — User Guide")
    top.geometry("720x680")
    top.configure(bg=GUIDE_BG)
    open_user_guide._existing = top

    def _on_close():
        open_user_guide._existing = None
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", _on_close)

    # Scrollable text area
    container = tk.Frame(top, bg=GUIDE_BG)
    container.pack(fill="both", expand=True, padx=12, pady=12)

    text = tk.Text(
        container, wrap="word", bd=0, highlightthickness=0,
        bg=GUIDE_BG, fg=GUIDE_FG, padx=12, pady=12,
        font=("Helvetica", 11),
    )
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)

    text.tag_configure(
        "heading", font=("Helvetica", 16, "bold"),
        foreground=GUIDE_HEADING, spacing3=8, spacing1=12,
    )
    text.tag_configure(
        "body", spacing3=6,
    )

    for title, paragraphs in SECTIONS:
        text.insert("end", title + "\n", "heading")
        for p in paragraphs:
            text.insert("end", p + "\n", "body")
        text.insert("end", "\n")

    text.configure(state="disabled")

    btn_row = tk.Frame(top, bg=GUIDE_BG)
    btn_row.pack(fill="x", padx=12, pady=(0, 12))
    tk.Button(
        btn_row, text="Close", command=_on_close,
        bg="#333333", fg=GUIDE_FG, relief="flat", bd=0, padx=12,
    ).pack(side="right")
