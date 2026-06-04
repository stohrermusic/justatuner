# JustATuner TODO

Outstanding work, roughly prioritized. v1.0.0 shipped 2026-06-04.

## Near-term (low effort, real value)

### Bump `softprops/action-gh-release` v1 → v2

The CI workflow's release-upload step runs on Node 20, which GitHub is removing from runners in September 2026. One-line change in `.github/workflows/build.yml`:

```yaml
uses: softprops/action-gh-release@v2  # was @v1
```

Two `uses:` lines to update (Windows installer upload + Linux/macOS artifact upload). After the bump, trigger a `workflow_dispatch` run (or wait for the next release) to confirm the v2 action behaves the same.

### Sample drone: remember last-loaded WAV across launches

Drone > Sample currently drops the loaded sample on app quit. Reasonable behavior to add:

- Persist the most-recently-loaded WAV's path in `exerciser_settings["last_sample_path"]`
- On launch, if the file still exists and the previous session had Sound = sample, auto-load it
- Skip silently if the file is gone (user moved / deleted it) and fall back to whatever previous sound type they had

Recordings (which aren't on disk) would need an extra step — saving them to a per-user config dir as `recordings/<timestamp>.wav` — if you want recorded samples to persist too.

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

### Port the GPU tuner renderer from SSC

SSC has a Rust/wgpu `tuner_renderer/` crate that delivers 60-120fps strobe wheels via maturin-built pyo3 extension, with automatic canvas fallback. Deliberately deferred from v1.0 to keep the build matrix simple.

If 90/120fps becomes desirable for JustATuner (most people won't care — canvas mode runs fine on any laptop), the port involves:

1. Copy `tuner_renderer/` from SSC verbatim
2. Add `pip install maturin` + Rust toolchain install steps to `.github/workflows/build.yml` for the platforms you want to build it on
3. Maturin-build the wheel and `pip install` it before `python build.py` runs, so PyInstaller picks it up
4. Confirm the `import tuner_render` try/except in `tuner/view.py` correctly falls back to canvas when the extension isn't installed

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
