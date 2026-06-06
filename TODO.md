# JustATuner TODO

Outstanding work, roughly prioritized. v1.0.0 shipped 2026-06-04.

## Near-term

### Ship v1.1.0 — mic fix + GPU renderer + sample persistence + CI bump

Four things landed on `beta` since v1.0.0; they ship together as **v1.1.0** (asap):

1. **macOS microphone fix** — v1.0.0's `.app` shipped without `NSMicrophoneUsageDescription`, so macOS silently denied mic access (tuner wheels never move, drone analyzer gets no input). The SSC extraction had dropped SSC's `_patch_macos_plist()` step; `build.py` now restores it and CI asserts the key via `plutil -extract`.
2. **GPU strobe renderer** — *the big one.* v1.0.0 shipped CPU-only: the extraction brought `tuner/view.py`'s GPU integration but not the Rust crate or build wiring, so **every user except the dev** (who had a stray local `tuner_render` install) got the canvas fallback. Now `tuner_renderer/` is copied from SSC, maturin-built in CI on all three platforms, and bundled via `build.py`'s `--hidden-import` capability check. Verified locally: the crate builds clean (release wheel produced in 71s).
3. **Drone sample persistence** — `exerciser_settings["last_sample_path"]` remembers the last loaded/recorded sample and reloads it on launch (falls back to the rich synth if the file is gone). Recordings auto-save to `<config dir>/recordings/last_recording.wav`; new **Drone > Sample > Save Sample As...** exports a loaded or recorded sample to a WAV.
4. **CI `softprops/action-gh-release` v1 → v2** — Node 20 removal (Sept 2026).

Release mechanics:
- ✅ `APP_VERSION` bumped to 1.1.0 in `config.py` + `installer.iss`.
- Write `release_notes_v1.1.0.md`.
- README: note the macOS first-launch mic prompt (click **Allow**); mention GPU strobe rendering.
- Merge `beta` → `main`, then `gh release create v1.1.0`.
- Interim for mac users still on v1.0.0 (mic): launch once via an Automator "Run Shell Script" app (`nohup /Applications/JustATuner.app/Contents/MacOS/JustATuner >/dev/null 2>&1 &`) so the app inherits mic permission from the shell — or just wait for v1.1.0.

## Iterative (Garden is marked beta for a reason)

### Garden visualizer tuning

Constants at the top of `_draw_garden` in `exerciser/view.py` are the obvious knobs:

- `GARDEN_PLANT_BASE_SPEED` (0.45) — pixels/frame for a fresh main stem
- `GARDEN_PLANT_BASE_LIFE` (400) — frames a main stem lives
- `GARDEN_DEPTH_DECAY_SPEED / WIDTH / LIFE` — vigor inheritance per generation
- `GARDEN_BRANCH_FAN` (28°) — angle children spawn at relative to parent
- `GARDEN_HUE_PER_FRAME` (0.00045) — color cycle speed
- `GARDEN_LEAF_INTERVAL` (22) — average frames between leaf drops
- `GARDEN_FIREFLY_CAP / BASE_RATE / LIFE` — firefly population behavior

Tweak these based on what feels right in real playing sessions, not from synthetic tests.

### Garden visualizer feature stretches

Open ideas from `memory/garden_visualizer.md`:

- **Sample-based plant texture** — when a WAV sample drone is loaded, derive the rib's FFT shape from the sample itself instead of mic input, so the visible plant matches the drone's character
- **Day/night cycle** — slow ambient brightness shift over ~10 minutes (inherited vision from the JustATone Rust pivot)
- **Vibrato-driven branch curvature** — a vibrato-y note would make the branch wiggle as it grows
- **Garden archive pane** — small thumbnail strip of past plants that scrolled off-screen, so the treadmill doesn't discard them entirely

## Stretches

### Port the GPU tuner renderer from SSC — ✅ done on beta (v1.1.0)

`tuner_renderer/` copied from SSC (8 source files), Rust toolchain + maturin build added to all three CI runners, bundled via `build.py`'s `--hidden-import tuner_render` capability check, with the canvas fallback in `tuner/view.py` intact. Crate verified to build locally. See the v1.1.0 item at the top.

### Phase vocoder for the WAV-sample drone

Currently sample resampling is linear interpolation — clean within ~one octave of source, but starts aliasing beyond that. A phase vocoder would decouple pitch from playback rate so you could drone a sample-recorded G3 in C5 without chipmunk artifacts.

Discussed in v1.0 design pass and **deliberately deferred** as overkill for the drone use case (users record near the middle of their intended drone range and stay within an octave). Revisit only if real users hit the limitation.

## Done in v1.0.0

- Stroboscopic Tuner + Just Intonation Drone in one Tk window, mic-handoff on tab change
- Six visualizer modes: Lissajous, Waveform, Spectrum, Waterfall, Warp, Garden (beta)
- WAV-sample drone (load file or record from mic) with trim + crossfade for clean looping
- Garden with branching plants, leaves, species-styled flowers, fireflies
- Warm five-layer motor pilot, responsive tuner control bar
- Cross-platform builds (Win installer, macOS .app, Linux binary)
- CLAUDE.md + memory files in `~/.claude/projects/C--code-justatuner/memory/`
