"""Progression model, notation, presets, persistence and the player — no
audio, no display, a fake clock."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JUSTATUNER_CONFIG_DIR"] = tempfile.mkdtemp(prefix="jat-prog-test-")

from exerciser.engine import VOICING_SYMBOLS  # noqa: E402
from exerciser.progression import (  # noqa: E402
    PRESETS, Progression, ProgressionPlayer, Step, format_steps, load_progressions,
    parse_chord, parse_steps, save_progressions,
)

passed = 0
failed = 0


def test(name, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


# ============================================
print("\n--- Notation ---")
s = parse_steps("C | F | G7:2 | C")
test("'C | F | G7:2 | C' parses to four steps", len(s) == 4)
test("roots C F G C", [x.root for x in s] == [0, 5, 7, 0])
test("qualities major major dom7 major", [x.voicing for x in s] == ["major", "major", "dom7", "major"])
test("lengths 1 1 2 1", [x.length for x in s] == [1.0, 1.0, 2.0, 1.0])
test("format round-trips", format_steps(s) == "C | F | G7:2 | C")
test("whitespace and commas also separate", len(parse_steps("Dm7 G7, Cmaj7")) == 3)
test("sharps and flats: F# is 6, Bb is 10, Cb is 11, B# is 0",
     [parse_chord(t).root for t in ("F#", "Bb", "Cb", "B#")] == [6, 10, 11, 0])
test("lower-case roots accepted", parse_chord("am").root == 9 and parse_chord("am").voicing == "minor")
test("every chord symbol parses back to its voicing",
     all(parse_chord("C" + sym).voicing == name for name, sym in VOICING_SYMBOLS.items()))
test("fractional length 'C:0.5'", parse_chord("C:0.5").length == 0.5)
for bad in ("H", "Cmaj9", "C:", "7", ""):
    try:
        parse_chord(bad)
        test(f"{bad!r} is rejected", False)
    except ValueError as e:
        test(f"{bad!r} is rejected ({e})", True)
test("Step symbol in written pitch: concert C for a Bb horn is D", Step(0, "major").symbol(2) == "D")
test("Step symbol: Dm7, Gaug", Step(2, "min7").symbol() == "Dm7" and Step(7, "aug").symbol() == "Gaug")

# ============================================
print("\n--- Timing ---")
p = Progression("t", parse_steps("C:2 | F"), mode="bars", bpm=120, beats_per_bar=4)
test("bars mode: 2 bars at 120 bpm, 4/4 = 4.0 s; 1 bar = 2.0 s",
     p.step_seconds(p.steps[0]) == 4.0 and p.step_seconds(p.steps[1]) == 2.0)
test("bars mode count-in is one bar (2.0 s)", p.count_in_seconds() == 2.0)
p2 = Progression("t", parse_steps("C:3 | F:1.5"), mode="seconds")
test("seconds mode: lengths are seconds; count-in 2 s",
     p2.step_seconds(p2.steps[0]) == 3.0 and p2.step_seconds(p2.steps[1]) == 1.5 and p2.count_in_seconds() == 2.0)
p3 = Progression("t", parse_steps("C | F"), mode="manual")
test("manual mode: no step length, no count-in", p3.step_seconds(p3.steps[0]) is None and p3.count_in_seconds() == 0.0)
try:
    Progression("t", [], mode="sideways")
    test("unknown mode rejected", False)
except ValueError:
    test("unknown mode rejected", True)
test("distinct chords in first-appearance order",
     Progression("t", parse_steps("C F C G7 F")).distinct_chords() == [(0, "major"), (5, "major"), (7, "dom7")])

# ============================================
print("\n--- Presets and persistence ---")
test(f"{len(PRESETS)} presets, all with steps and a name",
     len(PRESETS) >= 5 and all(p.steps and p.name for p in PRESETS))
blues = next(p for p in PRESETS if "blues" in p.name.lower())
test("12-bar blues has 12 steps, all sevenths", len(blues.steps) == 12 and all(s.voicing == "dom7" for s in blues.steps))
d = tempfile.mkdtemp(prefix="jat-prog-")
test("no file: empty list", load_progressions(d) == [])
mine = [Progression("Mine", parse_steps("Cmaj7 | Am7 | Dm7 | G7"), mode="seconds", bpm=72, beats_per_bar=3),
        Progression("Two", parse_steps("E | A"), mode="manual")]
save_progressions(d, mine)
back = load_progressions(d)
test("save/load round-trips names, steps, mode, bpm, beats",
     [(p.name, p.steps, p.mode, p.bpm, p.beats_per_bar) for p in back]
     == [(p.name, p.steps, p.mode, p.bpm, p.beats_per_bar) for p in mine])
with open(os.path.join(d, "progressions.json"), "w", encoding="utf-8") as f:
    f.write('{"progressions": [{"name": "ok", "text": "C F"}, {"name": "bad", "text": "H7"}]}')
back = load_progressions(d)
test("a bad entry is skipped, the good one loads with defaults",
     len(back) == 1 and back[0].name == "ok" and back[0].mode == "bars" and back[0].bpm == 90)
with open(os.path.join(d, "progressions.json"), "w", encoding="utf-8") as f:
    f.write("{not json")
test("corrupt file: empty list, no exception", load_progressions(d) == [])


# ============================================
print("\n--- Player ---")


class FakeEngine:
    def __init__(self, monitoring="headphones", drone_type="rich", ready_after=3):
        self.monitoring = monitoring
        self.drone_type = drone_type
        self.drone_freq = 130.81
        self.ready_after = ready_after
        self.ticks = 0
        self.known = set()

    def bleed_status(self):
        self.ticks += 1
        return "ready" if self.ticks >= self.ready_after else "listening"

    def room_known(self, freqs):
        return all(round(f, 3) in self.known for f in freqs)


applied = []
eng = FakeEngine()
p = Progression("t", parse_steps("C | F | G7 | C"), mode="bars", bpm=120, beats_per_bar=4)   # 2 s per bar
pl = ProgressionPlayer(p, eng, lambda r, v: applied.append((r, v)))
pl.start(now=0.0)
test("headphones: no calibration, straight to the count-in", pl.state == "countin" and applied == [])
pl.tick(1.9)
test("count-in still running at 1.9 s", pl.state == "countin" and pl.info(1.9)["countin"] == 4)
test("count-in shows beat 1 at 0.1 s", pl.info(0.1)["countin"] == 1)
pl.tick(2.0)
test("at 2.0 s playing step 0, C applied", pl.state == "playing" and applied == [(0, "major")])
pl.tick(3.9)
test("step 0 still sounding at 3.9 s", pl.index == 0)
pl.tick(4.0)
test("at 4.0 s step 1 (F)", pl.index == 1 and applied[-1] == (5, "major"))
pl.tick(6.0)
pl.tick(8.0)
test("steps 2 and 3 at 6 and 8 s", pl.index == 3 and applied[-1] == (0, "major") and applied[-2] == (7, "dom7"))
pl.tick(10.0)
test("loops back to step 0 and counts the loop", pl.index == 0 and pl.loops == 1)
i = pl.info(11.0)
test(f"info: current C, next F, remaining 1.0 s, fraction 0.5 ({i['current']}, {i['next']}, {i['remaining']}, {i['fraction']})",
     i["current"] == "C" and i["next"] == "F" and abs(i["remaining"] - 1.0) < 1e-9 and abs(i["fraction"] - 0.5) < 1e-9)
test("info in written pitch for a Bb horn: D, G", pl.info(11.0, 2)["current"] == "D" and pl.info(11.0, 2)["next"] == "G")
pl.next(11.0)
test("next() skips to F at once", pl.index == 1 and applied[-1] == (5, "major"))
pl.stop()
test("stop", pl.state == "stopped")

applied.clear()
eng = FakeEngine(monitoring="speakers", ready_after=3)
p = Progression("t", parse_steps("C | F | C | G7"), mode="seconds")
pl = ProgressionPlayer(p, eng, lambda r, v: applied.append((r, v)))
pl.start(0.0)
test("speakers: calibrating, first distinct chord sounded", pl.state == "calibrating" and applied == [(0, "major")])
i = pl.info(0.0)
test(f"info while calibrating: C, 0 of 3 ({i['current']}, {i['cal_index']}, {i['cal_total']})",
     i["current"] == "C" and i["cal_index"] == 0 and i["cal_total"] == 3)
for _ in range(2):
    pl.tick(0.1)
test("engine not ready yet: still on the first chord", pl.state == "calibrating" and len(applied) == 1)
pl.tick(0.2)
test("engine ready: second distinct chord (F) sounded", applied[-1] == (5, "major") and pl.info(0.2)["cal_index"] == 1)
eng.ticks = 0
for _ in range(3):
    pl.tick(0.3)
test("third distinct chord (G7)", applied[-1] == (7, "dom7"))
eng.ticks = 0
for _ in range(3):
    pl.tick(0.4)
test("all calibrated: count-in (2 s in seconds mode)", pl.state == "countin")
pl.tick(2.5)
test("playing step 0 after the count-in", pl.state == "playing" and applied[-1] == (0, "major"))
eng2 = FakeEngine(monitoring="speakers")
from exerciser.intervals import note_freq
eng2.known = set(round(note_freq(r, 3) * ratio * n, 3) for r in range(12) for ratio in (1, 5 / 4, 3 / 2, 7 / 4) for n in range(1, 9))
pl2 = ProgressionPlayer(p, eng2, lambda r, v: None)
pl2.start(0.0)
test("speakers with every chord already in the room: no calibration", pl2.state == "countin")

applied.clear()
eng = FakeEngine()
p = Progression("t", parse_steps("C | F"), mode="manual")
pl = ProgressionPlayer(p, eng, lambda r, v: applied.append((r, v)))
pl.start(0.0)
test("manual: playing at once, no count-in", pl.state == "playing" and applied == [(0, "major")])
for t in (10.0, 100.0, 1000.0):
    pl.tick(t)
test("manual: time never advances it", pl.index == 0)
pl.next(1000.0)
test("manual: next() advances", pl.index == 1 and applied[-1] == (5, "major"))
test("manual: info has no remaining time", pl.info(1000.0)["remaining"] is None)
try:
    ProgressionPlayer(Progression("e", []), eng, lambda r, v: None).start(0.0)
    test("empty progression refuses to start", False)
except ValueError:
    test("empty progression refuses to start", True)

# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
