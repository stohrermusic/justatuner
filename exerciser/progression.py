"""Chord progressions for the drone: the model, the text notation, presets,
persistence, and the player state machine. Pure Python, no tkinter; the
drone tab's view owns the timer that ticks the player and applies chords.

Notation: chords separated by spaces or bars, root letter with # or b,
then an optional quality symbol (see engine.VOICING_SYMBOLS: "" major,
"m" minor, "7" dominant, "maj7", "m7", "sus4", "sus2", "dim", "aug",
"1" root only, "5" root + fifth) and an optional ":length" (bars in bars
mode, seconds in seconds mode; ignored in manual mode). Examples:

    C | F | G7 | C            I-IV-V-I, one bar each
    Dm7 G7 Cmaj7:2            ii-V-I, the I held two bars
"""
import json
import os
import re

from exerciser.engine import VOICING_SYMBOLS
from exerciser.intervals import NOTE_NAMES

MODES = ("bars", "seconds", "manual")

_ROOT_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SYMBOL_TO_VOICING = {sym: name for name, sym in VOICING_SYMBOLS.items()}
_CHORD_RE = re.compile(r"^([A-Ga-g])([#b]?)([A-Za-z0-9]*?)(?::(\d+(?:\.\d+)?))?$")


class Step:
    __slots__ = ("root", "voicing", "length")

    def __init__(self, root, voicing="major", length=1.0):
        self.root = int(root) % 12
        self.voicing = voicing
        self.length = float(length)

    def symbol(self, transposition_offset=0):
        """"G7", "Dm", "Cmaj7" in written pitch for the player's instrument."""
        return NOTE_NAMES[(self.root + transposition_offset) % 12] + VOICING_SYMBOLS[self.voicing]

    def __eq__(self, other):
        return isinstance(other, Step) and (self.root, self.voicing, self.length) == (other.root, other.voicing, other.length)

    def __repr__(self):
        return f"Step({self.symbol()}:{self.length:g})"


class Progression:
    def __init__(self, name, steps, mode="bars", bpm=90, beats_per_bar=4):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        self.name = name
        # Copies: a progression built from a preset's steps must not change
        # the preset when its lengths are edited (the tour did exactly that).
        self.steps = [Step(s.root, s.voicing, s.length) for s in steps]
        self.mode = mode
        self.bpm = float(bpm)
        self.beats_per_bar = int(beats_per_bar)

    def step_seconds(self, step):
        """How long a step sounds in the timed modes (None in manual mode)."""
        if self.mode == "bars":
            return step.length * self.beats_per_bar * 60.0 / self.bpm
        if self.mode == "seconds":
            return step.length
        return None

    def count_in_seconds(self):
        """One bar in bars mode, two seconds in seconds mode, none in manual."""
        if self.mode == "bars":
            return self.beats_per_bar * 60.0 / self.bpm
        if self.mode == "seconds":
            return 2.0
        return 0.0

    def distinct_chords(self):
        """(root, voicing) pairs in first-appearance order: what speakers
        mode has to calibrate before playing."""
        seen = []
        for s in self.steps:
            key = (s.root, s.voicing)
            if key not in seen:
                seen.append(key)
        return seen

    def to_dict(self):
        return {"name": self.name, "text": format_steps(self.steps), "mode": self.mode,
                "bpm": self.bpm, "beats_per_bar": self.beats_per_bar}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("name", "Untitled"), parse_steps(d.get("text", "")), d.get("mode", "bars"),
                   d.get("bpm", 90), d.get("beats_per_bar", 4))


def parse_chord(token):
    """One chord token -> Step. Raises ValueError naming the token."""
    m = _CHORD_RE.match(token.strip())
    if not m:
        raise ValueError(f"can't read chord {token!r}")
    letter, accidental, quality, length = m.groups()
    root = _ROOT_INDEX[letter.upper()] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    if quality not in _SYMBOL_TO_VOICING:
        raise ValueError(f"unknown chord type {quality!r} in {token!r} "
                         f"(known: {', '.join(repr(s) for s in sorted(_SYMBOL_TO_VOICING) if s)})")
    return Step(root % 12, _SYMBOL_TO_VOICING[quality], float(length) if length else 1.0)


def parse_steps(text):
    """"C | F | G7:2 | C" -> [Step, ...]. Bars and whitespace both separate."""
    tokens = [t for t in re.split(r"[\s|,]+", text.strip()) if t]
    return [parse_chord(t) for t in tokens]


def format_steps(steps):
    return " | ".join(s.symbol() + (f":{s.length:g}" if s.length != 1.0 else "") for s in steps)


PRESETS = [
    Progression("I - IV - V - I in C", parse_steps("C | F | G | C")),
    Progression("ii - V - I in C", parse_steps("Dm7 | G7 | Cmaj7:2")),
    Progression("Pop  I - V - vi - IV", parse_steps("C | G | Am | F")),
    Progression("12-bar blues in F", parse_steps("F7 F7 F7 F7 Bb7 Bb7 F7 F7 C7 Bb7 F7 C7"), bpm=100),
    Progression("Cycle of fifths", parse_steps("C F Bb Eb Ab Db Gb B E A D G"), bpm=80),
    Progression("Minor  i - VI - III - VII", parse_steps("Am | F | C | G")),
]


def progressions_path(config_dir):
    return os.path.join(config_dir, "progressions.json")


def load_progressions(config_dir):
    """The user's saved progressions (never the presets). A missing or
    unreadable file is an empty list, never an exception."""
    try:
        with open(progressions_path(config_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for d in data.get("progressions", []):
            try:
                out.append(Progression.from_dict(d))
            except (ValueError, TypeError, AttributeError):
                continue
        return out
    except (OSError, ValueError):
        return []


def save_progressions(config_dir, progressions):
    with open(progressions_path(config_dir), "w", encoding="utf-8") as f:
        json.dump({"progressions": [p.to_dict() for p in progressions]}, f, indent=2)


class ProgressionPlayer:
    """Drives the drone through a progression.

    The view calls tick(now) on its timer and supplies apply_chord(root,
    voicing), which sets the tab's root and voicing (so the buttons follow)
    and the engine's drone. States: calibrating (speakers mode: each
    distinct chord is sounded once until the engine reports its bleed
    cancelled), countin, playing, stopped. All clocks are the caller's
    `now` seconds, so tests run with a fake clock.
    """

    def __init__(self, progression, engine, apply_chord):
        self.prog = progression
        self.engine = engine
        self.apply_chord = apply_chord
        self.state = "stopped"
        self.index = 0
        self.loops = 0
        self._cal = []
        self._cal_index = 0
        self._t_step = 0.0
        self._t_countin = 0.0

    # -- control --

    def start(self, now):
        if not self.prog.steps:
            raise ValueError("the progression has no chords")
        self.index = 0
        self.loops = 0
        if self.engine.monitoring == "speakers" and self.engine.drone_type != "sample":
            self._cal = [c for c in self.prog.distinct_chords()
                         if not self._known(c)]
        else:
            self._cal = []
        if self._cal:
            self.state = "calibrating"
            self._cal_index = 0
            self.apply_chord(*self._cal[0])
        else:
            self._begin_countin(now)

    def stop(self):
        self.state = "stopped"

    def next(self, now):
        """Advance one step (the manual-mode key, or a skip while timed)."""
        if self.state != "playing":
            return
        self.index += 1
        if self.index >= len(self.prog.steps):
            self.index = 0
            self.loops += 1
        self._t_step = now
        self.apply_chord(self.prog.steps[self.index].root, self.prog.steps[self.index].voicing)

    def tick(self, now):
        if self.state == "calibrating":
            if self.engine.bleed_status() == "ready":
                self._cal_index += 1
                if self._cal_index < len(self._cal):
                    self.apply_chord(*self._cal[self._cal_index])
                else:
                    self._begin_countin(now)
        elif self.state == "countin":
            if now - self._t_countin >= self.prog.count_in_seconds():
                self.state = "playing"
                self._t_step = now
                self.apply_chord(self.prog.steps[0].root, self.prog.steps[0].voicing)
        elif self.state == "playing" and self.prog.mode != "manual":
            if now - self._t_step >= self.prog.step_seconds(self.prog.steps[self.index]):
                self.next(now)

    # -- for the UI --

    def info(self, now, transposition_offset=0):
        """What to show: state, current and next chord, progress, count-in."""
        d = {"state": self.state, "index": self.index, "loops": self.loops,
             "current": "", "next": "", "remaining": None, "fraction": 0.0, "countin": None,
             "cal_index": self._cal_index, "cal_total": len(self._cal)}
        steps = self.prog.steps
        if self.state == "calibrating" and self._cal:
            d["current"] = Step(*self._cal[min(self._cal_index, len(self._cal) - 1)]).symbol(transposition_offset)
        elif self.state == "countin":
            total = self.prog.count_in_seconds()
            elapsed = now - self._t_countin
            if self.prog.mode == "bars":
                beat = 60.0 / self.prog.bpm
                d["countin"] = min(self.prog.beats_per_bar, int(elapsed / beat) + 1)
            else:
                d["countin"] = max(1, int(total - elapsed) + 1)
            d["current"] = steps[0].symbol(transposition_offset)
            d["next"] = steps[1 % len(steps)].symbol(transposition_offset) if len(steps) > 1 else ""
        elif self.state == "playing":
            d["current"] = steps[self.index].symbol(transposition_offset)
            d["next"] = steps[(self.index + 1) % len(steps)].symbol(transposition_offset)
            total = self.prog.step_seconds(steps[self.index])
            if total:
                elapsed = now - self._t_step
                d["remaining"] = max(0.0, total - elapsed)
                d["fraction"] = min(1.0, elapsed / total)
        return d

    # -- internal --

    def _known(self, chord):
        root, voicing = chord
        from exerciser.engine import VOICINGS
        from exerciser.intervals import note_freq
        base = note_freq(root, self._octave())
        freqs = []
        for ratio, _ in VOICINGS[voicing]:
            f = base * ratio
            if self.engine.drone_type == "rich":
                freqs += [f * n for n in range(1, 9)]
            else:
                freqs.append(f)
        return self.engine.room_known(freqs)

    def _octave(self):
        import math
        # The drone's current octave, from its frequency (the view keeps the
        # octave; the player only needs it to name frequencies).
        midi = 69 + 12 * math.log2(self.engine.drone_freq / 440.0)
        return int(round(midi)) // 12 - 1

    def _begin_countin(self, now):
        self.state = "countin"
        self._t_countin = now
        if self.prog.count_in_seconds() <= 0:
            self.state = "playing"
            self._t_step = now
            self.apply_chord(self.prog.steps[0].root, self.prog.steps[0].voicing)
