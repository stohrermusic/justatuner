"""Just intonation interval definitions and analysis."""

import math

# Note names (flat convention for wind players)
NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# A4 = 440 Hz reference
A4_FREQ = 440.0
A4_MIDI = 69

# Just intonation intervals with ratios
JI_INTERVALS = [
    {"name": "Unison",      "short": "P1",  "ratio": (1, 1),   "semitones": 0},
    {"name": "Minor 2nd",   "short": "m2",  "ratio": (16, 15), "semitones": 1},
    {"name": "Major 2nd",   "short": "M2",  "ratio": (9, 8),   "semitones": 2},
    {"name": "Minor 3rd",   "short": "m3",  "ratio": (6, 5),   "semitones": 3},
    {"name": "Major 3rd",   "short": "M3",  "ratio": (5, 4),   "semitones": 4},
    {"name": "Perfect 4th", "short": "P4",  "ratio": (4, 3),   "semitones": 5},
    {"name": "Tritone",     "short": "TT",  "ratio": (7, 5),   "semitones": 6},
    {"name": "Perfect 5th", "short": "P5",  "ratio": (3, 2),   "semitones": 7},
    {"name": "Minor 6th",   "short": "m6",  "ratio": (8, 5),   "semitones": 8},
    {"name": "Major 6th",   "short": "M6",  "ratio": (5, 3),   "semitones": 9},
    {"name": "Minor 7th",   "short": "m7",  "ratio": (7, 4),   "semitones": 10},
    {"name": "Major 7th",   "short": "M7",  "ratio": (15, 8),  "semitones": 11},
    {"name": "Octave",      "short": "P8",  "ratio": (2, 1),   "semitones": 12},
]

# Precompute JI cents for each interval
for iv in JI_INTERVALS:
    iv["ji_cents"] = 1200.0 * math.log2(iv["ratio"][0] / iv["ratio"][1])
    iv["et_cents"] = iv["semitones"] * 100.0
    iv["et_diff"] = iv["ji_cents"] - iv["et_cents"]  # How far JI is from ET

# Transposition: concert -> written note offset in semitones
TRANSPOSITIONS = {
    "Concert (C)": 0,
    "Bb":          2,   # Written D sounds concert C
    "Eb":          9,   # Written A sounds concert C
    "F":           7,   # Written G sounds concert C
}


def note_freq(note_index, octave):
    """Get frequency for a note. note_index: 0=C, 1=Db, ..., 11=B."""
    midi = 12 * (octave + 1) + note_index
    return A4_FREQ * 2 ** ((midi - A4_MIDI) / 12.0)


def freq_to_note_name(freq):
    """Convert frequency to nearest note name and octave."""
    if freq <= 0:
        return "?", 0
    midi = 69 + 12 * math.log2(freq / A4_FREQ)
    midi_round = round(midi)
    octave = (midi_round // 12) - 1
    note_idx = midi_round % 12
    return NOTE_NAMES[note_idx], octave


def transpose_note_name(concert_note_idx, transposition_key):
    """Convert concert pitch note index to written note index."""
    offset = TRANSPOSITIONS.get(transposition_key, 0)
    return (concert_note_idx + offset) % 12


def analyze_interval(played_freq, root_freq):
    """Analyze the interval between played note and root.

    Returns dict with:
        interval: the closest JI interval dict
        cents_off: cents deviation from perfect JI (negative = flat, positive = sharp)
        ratio: the actual frequency ratio (normalized to one octave)
        played_cents: the played interval in cents
    """
    if played_freq <= 0 or root_freq <= 0:
        return None

    ratio = played_freq / root_freq

    # Normalize to within one octave (1.0 to 2.0)
    octave_shift = 0
    while ratio < 1.0:
        ratio *= 2.0
        octave_shift -= 1
    while ratio >= 2.0:
        ratio /= 2.0
        octave_shift += 1

    # Convert to cents
    played_cents = 1200.0 * math.log2(ratio)

    # Find closest JI interval
    best = None
    best_diff = float("inf")
    for iv in JI_INTERVALS:
        diff = played_cents - iv["ji_cents"]
        # Wrap around octave boundary
        if diff > 600:
            diff -= 1200
        elif diff < -600:
            diff += 1200
        if abs(diff) < abs(best_diff):
            best_diff = diff
            best = iv

    return {
        "interval": best,
        "cents_off": best_diff,
        "ratio": ratio,
        "played_cents": played_cents,
        "octave_shift": octave_shift,
    }
