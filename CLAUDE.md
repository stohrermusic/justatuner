# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JustATuner is a free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one Tk window:

- **Stroboscopic Tuner** — a 12-wheel chromatic strobe-style tuner, extracted from [Stohrer Sax Shop Companion][ssc] where it grew up in real saxophone repair shops. Optional Rust/wgpu GPU renderer on Windows/Linux, with Tk canvas fallback; macOS is canvas-only (Tk Aqua has no per-widget NSView for wgpu to draw into).
- **Just Intonation Drone** — drone synthesizer (sine / rich / WAV sample) with live JI interval analysis and six visualizer modes including a Geiss-style waterfall and an audio-driven branching garden. Originally the [JustATone][jat] Python prototype, preserved here after that project pivoted to a Rust/bevy generative-art garden.

[ssc]: https://github.com/stohrermusic/Stohrer-Sax-Shop-Companion
[jat]: https://github.com/stohrermusic/justatone

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

Dependencies: `numpy`, `sounddevice`, `pillow`, `pyinstaller` (for building). The GUI uses Python's built-in `tkinter`. Requires Python 3.11+.

There is no test suite yet. The app is verified by running it with a microphone and a pair of headphones.

## Building Executables

```bash
# Build for current platform (Win/Linux: single binary, macOS: .app bundle)
python build.py

# Clean and rebuild
python build.py --clean
```

PyInstaller picks up the `tuner/`, `exerciser/`, and `audio_utils.py` packages via the import graph from `main.py` — no `--add-data` needed for source. Pillow's native libraries get bundled automatically (~5–10 MB).

**GPU tuner renderer**: `build.py` adds `--hidden-import tuner_render` only when that extension is importable, so a *local* `python build.py` bundles the GPU renderer only if you've built and installed it first:

```bash
pip install maturin
python -m maturin build --release --manifest-path tuner_renderer/Cargo.toml
pip install --find-links tuner_renderer/target/wheels tuner_render
```

CI does this on the Windows and Linux runners (Rust via `dtolnay/rust-toolchain@stable`); the macOS runner skips it because macOS is canvas-only (see Per-Platform Constraints). Without the extension the build is canvas-only and `tuner/view.py` falls back at runtime — which is exactly how v1.0.0 silently shipped CPU-only.

**macOS microphone permission**: on macOS the build runs `_patch_macos_plist()` after PyInstaller, injecting `NSMicrophoneUsageDescription` into `dist/JustATuner.app/Contents/Info.plist`. macOS *silently* denies mic access to any app that doesn't declare it — the tuner wheels never move and the drone analyzer sees no input — and PyInstaller doesn't add the key. This mirrors SSC's `build.py`; the SSC extraction originally dropped the step (restored on `beta`). CI asserts the key is present via `plutil -extract`, so a regression fails the macOS build.

## Module Structure

```
main.py                 → Tk root + two-tab Notebook + on_tab_changed engine swap
config.py               → DEFAULT_SETTINGS, settings I/O, per-platform config dir
audio_utils.py          → AudioRingBuffer (shared by both audio engines)
user_guide.py           → Help > User Guide content + window
build.py                → PyInstaller wrapper

tuner/
  engine.py             → TunerEngine (FFT pitch detection, phase tracking,
                          ReferencePlayer); no tkinter dependency
  view.py               → TunerView (the SSC TunerTabMixin refactored into a
                          standalone class that takes parent + root + settings
                          in its constructor); StrobeWheel canvas renderer

exerciser/
  engine.py             → AudioEngine (drone synth, mic input, YIN pitch
                          detection, WAV-sample drone with trim+crossfade,
                          recording capture); _read_wav_file at module bottom
  intervals.py          → JI ratios + analyze_interval + note_freq
  pitch.py              → YIN pitch detection (used by both the engine's
                          mic-pitch path AND the sample-pitch-detection path)
  widgets.py            → RoundScope (canvas-based round CRT widget)
  view.py               → ExerciserView (drone tab UI), RecordSampleDialog,
                          all six visualizer mode draw methods

tuner_renderer/         → Rust/wgpu GPU strobe renderer (pyo3 extension,
                          built with maturin into the `tuner_render` module).
                          tuner/view.py imports it on Windows/Linux; falls
                          back to the canvas renderer when absent. Never
                          imported on macOS (winfo_id() is not an NSView —
                          see Per-Platform Constraints). Copied from SSC.

installer.iss           → Inno Setup script for Windows installer
.github/workflows/
  build.yml             → CI: matrix builds Win + macOS ARM + Linux on push
                          to main/beta + release + workflow_dispatch
```

## Key Design Patterns

**Engine ↔ View separation**: both `tuner/engine.py` and `exerciser/engine.py` are pure audio + math, no tkinter. The corresponding `*/view.py` modules own the UI and ask the engine for data each frame via lightweight getters. This is the same split SSC uses, and is why the tuner engine ports cleanly between SSC and JustATuner — only the view changes.

**Tab-aware audio**: only the active notebook tab's engine has an open sounddevice InputStream. `main.py`'s `_on_tab_changed` stops one and starts the other. Critical because the OS sometimes refuses two concurrent opens on the same input device on macOS.

**Tab-specific menus**: each tab rebuilds the menubar when it becomes active. The exerciser contributes Drone / Exerciser Options menus; the tuner contributes a **Tuner** menu whose **Settings…** entry opens `_tuner_open_settings` (stripe/faceplate color, ring + overall brightness, octave boost, input-device picker, on-screen FPS toggle). Some tuner controls are also inline (sensitivity, reference pitch, transposition, waveform). The Tuner menu's wiring was missing until v1.1.x — the dialog existed but nothing opened it (an extraction gap).

**Settings persistence**: `config.load_settings()` does a two-level deep merge with `DEFAULT_SETTINGS` so old config files survive new keys being added. Save happens on app close in `JustATunerApp._on_close` via both views' `save_settings()` methods.

## Audio Engines

### Tuner engine (`tuner/engine.py`)

12 chromatic pitch classes, each with seven concentric rings (one per octave). FFT-based pitch detection with per-pitch-class phase tracking — phase deviation drives the stroboscopic rotation effect. Magnitude normalization is gated: `max_mag` must exceed `threshold * 1.5` before normalizing to 0–1, otherwise all magnitudes are zeroed. This prevents sensitive mics from showing wheel activity on room noise.

Audio stream health monitoring via `AudioRingBuffer.is_stale()` — if no new audio data arrives for ~1 second, the engine restarts the sounddevice stream. Recovers from silent callback death on Windows.

### Exerciser engine (`exerciser/engine.py`)

Drone synthesizer + mic input + pitch detection in one class. `_rebuild_oscillators` builds a per-voice list `_osc_freqs = [(freq, amp), ...]` driven by the current voicing (root / root+fifth / major / minor) and sound type:

- **sine**: one oscillator per voice
- **rich**: one oscillator per voice plus 8 harmonics each (decreasing amplitude)
- **sample**: one playhead per voice through the loaded `_drone_sample` buffer

For sample mode, `_render_sample_voices` runs in the audio callback and per-voice computes the playback rate as `(target_freq / sample_freq) * (sample_sr / output_sr)`, advances a float playhead through the sample buffer with wrap, linear-interpolates between adjacent samples, sums all voices, normalizes.

### WAV-sample drone (`_install_sample` in `exerciser/engine.py`)

Loaded WAV files and live recordings both go through `_install_sample`, which does three things before storing the buffer:

1. **Trim attack + release** — up to 200ms from each end, capped at 10% of total length. Drops onset and decay so the looping region is steady-state.
2. **Pitch detection** — YIN on a 2-second window centered on the trimmed middle. Used both for the per-voice playback rate AND for sizing the crossfade. Falls back to A4 (440 Hz) at low confidence.
3. **Equal-power crossfade at the loop boundary** — last N samples become `tail * cos(πi/2N) + head * sin(πi/2N)` where N is min(4 periods, 150ms, 25% of sample). Constant-RMS curves so there's no energy dip across the boundary. Result: the mod-wrap from index L-1 to 0 in `_render_sample_voices` is seamless for any sustained tone.

`_read_wav_file` at the bottom of the module handles 16/24/32-bit PCM and 32-bit float WAVs (probes the first 1024 samples on 4-byte width to distinguish int32 from float32). Stereo is downmixed to mono by averaging.

### Recording

`record_start()` / `record_stop_and_use()` / `record_cancel()` work with the existing input stream — the input callback appends each frame to `_recording_chunks` while `_recording` is True. The recording UI in `RecordSampleDialog` (`exerciser/view.py`) polls `engine.recorded_duration_s()` for the elapsed counter. 1.5-second hold-off on the Stop button so an accidental double-click can't immediately abort.

### Sample persistence

The active drone sample survives a restart. `ExerciserView` tracks the current sample's source path in `self._current_sample_path` and writes it to `exerciser_settings["last_sample_path"]` in `save_settings()`. On construction, if the saved `drone_type` is `"sample"` and the path still exists, it reloads via `engine.load_sample_wav()`; a missing/unreadable file falls back to the `rich` synth so the drone still sounds. Loaded WAVs persist by their own path; recordings (in-memory only) are auto-saved to `<config dir>/recordings/last_recording.wav` in `_after_record` so they have a path to remember. `engine.save_sample_wav(path)` writes the current sample as 16-bit PCM mono and backs both that auto-save and the **Drone > Sample > Save Sample As...** export.

## Visualizer Modes (JI Drone tab)

All six modes are draw methods on `ExerciserView`, dispatched from `_update_scope`. The render target is the `RoundScope` canvas widget (`exerciser/widgets.py`) — a `tk.Canvas` with a circular bezel + graticule drawn once and a `draw_mask()` z-order trick that keeps the bezel ring above content.

| Mode | Implementation | Cost |
|------|----------------|------|
| **Lissajous** | `tk.Canvas` lines, drone reference sine vs mic input | Cheap; ~3 lines/frame |
| **Waveform** | Canvas line; mic samples scaled to ±70% radius | Cheap |
| **Spectrum** | Persistent canvas rectangles + cap lines, updated via `coords()` | Critical that items are persistent — recreating them per frame is what made the original implementation feel slow |
| **Waterfall** | 50 persistent canvas lines, each one polyline of FFT magnitudes with perspective transform; new row pushed to front each frame | Each row stores its sprout-time hue, so the slow color cycle reads through history |
| **Warp** | PIL framebuffer (220×220 RGB), zoom outward each frame + integer multiply decay + new audio-driven shapes via ImageDraw, pushed to canvas via `ImageTk.PhotoImage` | Circular alpha mask applied at display so corners don't poke past the bezel |
| **Garden (beta)** | PIL framebuffer (280×280), branching plants with print-head ribbon stamping, leaves, species-styled flowers, and transient firefly overlay | See [Garden architecture](#garden-visualizer-architecture) below |

**Persistent canvas items rule**: any visualizer that draws many shapes per frame must create them once and update via `.coords()` + `.itemconfigure()`. Spectrum and Waterfall were both written this way after Spectrum's first version felt slow. Tk hates `delete()` + `create_*()` churn.

**PIL framebuffer rule**: Warp and Garden both apply a circular alpha mask before pushing to the canvas so their square framebuffers don't visibly protrude past the round bezel ring. The mask is cached by display size in `_get_garden_circle_mask` and shared between the two modes.

**Settings migration**: invalid `visualizer_mode` values (e.g. "Phase Wheel" from the brief period that mode existed) fall back to "Lissajous" on load. See `_VALID_MODES` in `ExerciserView.__init__`.

## Garden Visualizer Architecture

The most involved visualizer. Sits in `_draw_garden` and a cluster of helpers (`_spawn_garden_plant`, `_garden_step_branch`, `_garden_branch_tip`, `_garden_draw_leaf`, `_garden_draw_flower`, `_draw_petal`, `_garden_scroll_left`, `_garden_step_fireflies`, `_spawn_garden_firefly`, `_garden_render_fireflies`).

### Print-head ribbon model

Each plant is a tree of "branches"; each branch has a print-head position (`x`, `y`), direction (`angle`), `speed`, `width`, `life`, `depth`, and a `rotation_index` for phyllotaxis. Per frame, every alive branch:

1. Ages by 1; if `age >= life`, blooms a flower and dies
2. Curves its direction by `drift` (from smoothed spectral centroid) + small bias toward vertical
3. Advances its position by `speed * (1 + 1.5 * audio_env)` in the direction angle
4. Stamps the current FFT cross-section as a symmetric rib perpendicular to the direction
5. Drops a leaf if depth ≥ 1 and the leaf cooldown hit zero (alternating sides via `leaf_side`)
6. Rolls a small per-frame chance of secondary bloom (most species have rate 0)

### Branching (L-system + golden angle + apical dominance)

Branching is triggered by audio amplitude peaks above 1.7× the smoothed envelope, with a 25-frame minimum gap between events. When triggered, `_garden_branch_tip` finds the most vigorous alive tip (max `(life-age) * width`), splits it into 2 children at `±GARDEN_BRANCH_FAN` from the parent direction (with a small golden-angle twist to vary which sides children take), and kills the parent.

Each child inherits:
- speed ← parent × `GARDEN_DEPTH_DECAY_SPEED` (0.78)
- width ← parent × `GARDEN_DEPTH_DECAY_WIDTH` (0.62)
- life  ← parent × `GARDEN_DEPTH_DECAY_LIFE`  (0.55)
- depth ← parent + 1

This is the apical-dominance idea: the original lineage's vigor is parceled out to children, who get successively smaller and shorter-lived. After `GARDEN_MAX_DEPTH` (4) generations, tips just keep extending without further splits.

### Per-plant flower species

Each plant rolls a `flower_style` dict at spawn time so all of its blooms match like a real species. Style axes:

- `n_petals`: weighted from `(3, 5, 5, 6, 7, 8, 9, 13)` — Fibonacci-heavy, 5 doubled because pentamerous flowers dominate in nature
- `shape`: `"round"` | `"teardrop"` | `"ray"` | `"spade"` — four petal silhouettes drawn as quad/quintuple polygons in `_draw_petal` (PIL's `ellipse` is axis-aligned so anything non-trivially rotated has to be a polygon)
- `petal_aspect`: 0.7–1.8 ratio of radial length to side width
- `center_ratio`: 0.25–0.65 fraction of flower radius taken by the contrasting center disc
- `petal_overlap`: 0.9–1.25 — >1 makes neighbors touch
- `size_scale`: 0.85–1.3 overall flower size modifier
- `center_hue_offset`: complementary (0.5), triad (0.33), or analog (0.17), weighted toward complementary
- `petal_rotation`: random starting angle so n-fold symmetry isn't always pointing up
- `secondary_bloom_rate`: small per-frame chance (0..0.0015) of extra mid-branch flowers at 60% size — most species have rate 0

Terminal flowers only fire at natural end-of-life (`age >= life`). Branches killed by going off-canvas or by being branched away don't flower — flowers visually mark branches that grew to maturity.

### Garden composition

When all branches in the current plant die, `_spawn_garden_plant` seeds a new plant `40px` to the right. Up to 8 plant records kept in memory; oldest dropped beyond that. When `_garden_next_plant_x` runs past the right edge, `_garden_scroll_left` shifts the framebuffer (and all branch x-coordinates AND the next-plant cursor AND every firefly's x-coordinate) left by 40% of canvas width — treadmill scroll.

### Fireflies (transient overlay)

Yellow-green dots that drift above the garden, spawning faster when sustained playing pumps `_garden_audio_env`. State per firefly: `x`, `y`, `vx`, `vy`, `phase`, `flicker_rate`, `age`, `life`, `hue`. Cap at 14 concurrent.

Per frame: `_garden_step_fireflies` decrements a spawn cooldown and adds a new firefly when it hits 0. Then steps each one — random brownian-style impulse + damping + slight upward bias + phase advance. Kills any that wander out of bounds.

**Fireflies are NOT written to the persistent buffer** (they'd leave trails). Instead, `_draw_garden` copies the persistent buffer each frame and `_garden_render_fireflies` paints them onto the copy as a transient overlay. Each firefly is rendered as a three-layer concentric glow stack (same trick as the tuner motor pilot), with brightness flickering via `0.55 + 0.45 * sin(phase)` and a fade-in/fade-out envelope at the start and end of life.

### Audio mappings (Garden)

| Audio feature | Where it goes |
|---|---|
| FFT log-bucketed magnitudes (18 bars) | Rib intensity profile across each branch's width |
| Spectral centroid (smoothed) | Lateral drift on all branch directions (warm leans left, bright leans right) |
| Smoothed RMS (`audio_env`) | Branch growth speed multiplier + firefly spawn rate boost |
| Peak amplitude vs envelope | Branching trigger (>1.7× threshold + 25-frame gap) |
| Hue accumulator (audio-independent) | Color cycle so old vs new plant material is visually distinct |

## Window Behavior

App opens **maximized** on every platform: `state('zoomed')` on Windows, `attributes('-zoomed', True)` on Linux/X11, screen-sized geometry fallback on macOS (Aqua has no programmatic maximize). The fallback geometry is the screen size + position (0, 0); the user can drag/resize from there.

## Tab-Specific Menu

`main.py`'s `_rebuild_menubar(is_tuner)` builds a fresh menubar on every tab change. Both views expose `populate_menu(menubar)` to contribute their tab's menus — Tuner ▸ Settings… for the tuner, Drone / Exerciser Options for the exerciser.

## Branching Strategy

- **`main`**: Stable release branch. Tagged versions live here. Merges from `beta` when features are tested and ready.
- **`beta`**: Active development branch. New features land here first. CI builds run on both branches so beta pushes get the same Win/macOS/Linux validation main does.
- Same pattern as Stohrer Sax Shop Companion.

## Versioning

`APP_VERSION` in `config.py` is the manual source of truth — bump it when preparing a release. Also update `installer.iss`'s build-comment example and create a matching `release_notes_vX.Y.Z.md` file. The `AppId` GUID in `installer.iss` is stable across releases — **do not change** it or Windows will install upgrades in parallel instead of replacing.

Release notes file format mirrors what landed for v0.9.0 and v1.0.0: a "What's new since vX.Y.Z" section at the top (when applicable), then the standard feature lists, then Installs and Known limitations sections. Screenshots embed via `https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/{tuner,drone}.png` URLs.

## Release Process

```bash
# 1. Bump version in config.py and installer.iss
# 2. Write release_notes_vX.Y.Z.md
# 3. Commit on beta and push
git push origin beta

# 4. Merge beta into main
git checkout main
git pull --ff-only
git merge --no-ff beta -m "Merge beta into main: vX.Y.Z release"
git push origin main

# 5. Create the release — triggers CI on the `release` event, which
#    attaches all three platform binaries to the release page
gh release create vX.Y.Z --target main --title "JustATuner vX.Y.Z" \
    --notes-file release_notes_vX.Y.Z.md
```

## CI/CD (GitHub Actions)

Single workflow at `.github/workflows/build.yml`. Three matrix entries:

- **`windows-latest`** — Python 3.11, `pip install -r requirements.txt`, `python build.py`, then Inno Setup (`choco install innosetup`) wraps `dist\JustATuner.exe` into `JustATuner-Windows-Setup-{APP_VERSION}.exe`. Only the installer is published; the bare `.exe` is not.
- **`macos-latest`** — Apple Silicon. Same Python install, `python build.py` produces `dist/JustATuner.app`, zipped to `JustATuner-macOS.zip`.
- **`ubuntu-latest`** — `apt-get install libportaudio2`, then build, rename to `JustATuner-Linux`.

Before the PyInstaller step, the Windows and Linux runners install the Rust toolchain (`dtolnay/rust-toolchain@stable`) and `maturin build` the `tuner_renderer/` crate, then `pip install` the resulting `tuner_render` wheel so `build.py` bundles the GPU strobe renderer. Adds a Rust compile (~1–2 min/runner) to those builds. The macOS runner skips the Rust steps entirely — macOS is canvas-only (see Per-Platform Constraints).

Triggers: push to `main` or `beta`, release `created`, manual `workflow_dispatch`. On release events, the `softprops/action-gh-release@v2` step attaches each platform's artifact to the release page (bumped from `@v1`, which ran on the soon-to-be-removed Node 20).

## Config File Location

User settings live in `app_settings.json` at:

| Platform | Location |
|----------|----------|
| Windows | `%APPDATA%\JustATuner\` |
| macOS | `~/Library/Application Support/JustATuner/` |
| Linux | `$XDG_CONFIG_HOME/JustATuner/` (or `~/.config/JustATuner/`) |

Schema lives in `config.py`'s `DEFAULT_SETTINGS`. Anything read at runtime MUST exist in `DEFAULT_SETTINGS` — the merge in `load_settings` only preserves keys that already appear in the defaults, so runtime-only keys silently disappear on next launch.

Top-level keys: `tuner_settings` (dict), `exerciser_settings` (dict), `audio_input_device` (int or None), `active_tab` (str — "tuner" or "exerciser").

## Per-Platform Constraints

- **Apple Silicon only on macOS** — `sounddevice`'s Intel wheel doesn't reliably bundle PortAudio. JustATuner is audio-only, so an Intel build with no audio isn't worth shipping. README points Intel Mac users at `brew install portaudio` + From-Source.
- **No code signing on any platform**. Windows uses SmartScreen "Run anyway" + UAC; macOS needs `xattr -cr` to clear the quarantine flag; Linux needs `chmod +x`. README documents all three.
- **macOS mic permission must be declared in the bundle**. `build.py`'s `_patch_macos_plist()` adds `NSMicrophoneUsageDescription` to the `.app` Info.plist post-build; without it macOS silently denies microphone access. v1.0.0 shipped without it (an extraction regression) — fixed in v1.1.0.
- **GPU tuner renderer is built in CI** (v1.1.0+), **Windows and Linux only**. The Rust/wgpu `tuner_render` crate lives in `tuner_renderer/` (copied from SSC); maturin builds it on those runners and `build.py`'s `--hidden-import` capability check bundles it, with `tuner/view.py` falling back to the Tk canvas renderer when it's absent. **v1.0.0 shipped without it** — the extraction brought over the Python integration in `tuner/view.py` but not the crate or the build wiring, so end users got canvas-only while a stray local `tuner_render` install masked the gap in dev. Fixed in v1.1.0.
- **macOS is canvas-only — never load `tuner_render` on darwin.** Tk Aqua draws all widgets into a single NSView per toplevel, and `winfo_id()` returns an internal `MacDrawable` pointer ("the value has no meaning outside Tk" — Tk docs), not an NSView. `tuner_renderer/src/platform.rs` treats the handle as an NSView, so wgpu's Metal backend segfaults in `objc_msgSend` during surface creation — a native crash the Python `except` fallback in `tuner/view.py` can never catch. Three layers enforce this: `tuner/view.py` skips the `tuner_render` import on darwin, `build.py` skips the `--hidden-import` on darwin, and CI skips the Rust build on the macOS runner. The v1.1.0 macOS zip shipped with the renderer bundled and likely crashed at launch. Even a real NSView wouldn't be enough: a CAMetalLayer on the shared view would paint over the entire window, so a macOS GPU path would need a dedicated subview managed natively (plus Retina scale handling).
- **Cmd-Q must be routed through `_on_close`.** On macOS, Cmd-Q and the app menu's Quit fire Tk's `::tk::mac::Quit`, which by default exits the process without running the `WM_DELETE_WINDOW` handler — settings would silently never save. `main.py` registers `root.createcommand("::tk::mac::Quit", self._on_close)` on darwin.

## Relationship to Stohrer Sax Shop Companion

JustATuner started as a "what if the SSC tuner was its own free app for musicians who aren't repair techs" question. The strobe tuner half is a direct extraction of `tuner_engine.py`, `audio_utils.py`, and `tuner_tab.py`, with `TunerTabMixin` refactored into a standalone `TunerView` class that takes `(parent, root, settings)` in its constructor instead of pulling them from `self`. Tuner bugfixes that land in SSC should be ported here when relevant; this app doesn't import from SSC at runtime — the files are duplicated, by design, so the two projects can evolve independently.

The JI Drone half was the original JustATone Python prototype (still in `C:\code\justatone` as legacy files alongside the now-current Rust/bevy garden visualizer). Brought over wholesale and adapted: `AudioEngine`, `intervals.py`, `pitch.py`, `widgets.py` are essentially unchanged from the prototype; `view.py` is rebuilt as an embeddable Frame.

The garden visualizer in this app is a fresh take on the garden vision from the JustATone Rust pivot — done in Tk + PIL instead of bevy + wgpu. Different stack, same spirit.
