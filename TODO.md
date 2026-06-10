# JustATuner TODO

Outstanding work, roughly prioritized. v1.0.0 shipped 2026-06-04.

## Near-term

### v1.1.0 — shipped 2026-06-06

Four things shipped together in **v1.1.0** (binaries on the [release page](https://github.com/stohrermusic/justatuner/releases/tag/v1.1.0)):

1. **macOS microphone fix** — v1.0.0's `.app` shipped without `NSMicrophoneUsageDescription`, so macOS silently denied mic access (tuner wheels never move, drone analyzer gets no input). The SSC extraction had dropped SSC's `_patch_macos_plist()` step; `build.py` now restores it and CI asserts the key via `plutil -extract`.
2. **GPU strobe renderer** — *the big one.* v1.0.0 shipped CPU-only: the extraction brought `tuner/view.py`'s GPU integration but not the Rust crate or build wiring, so **every user except the dev** (who had a stray local `tuner_render` install) got the canvas fallback. Now `tuner_renderer/` is copied from SSC, maturin-built in CI on all three platforms, and bundled via `build.py`'s `--hidden-import` capability check. Verified locally: the crate builds clean (release wheel produced in 71s).
3. **Drone sample persistence** — `exerciser_settings["last_sample_path"]` remembers the last loaded/recorded sample and reloads it on launch (falls back to the rich synth if the file is gone). Recordings auto-save to `<config dir>/recordings/last_recording.wav`; new **Drone > Sample > Save Sample As...** exports a loaded or recorded sample to a WAV.
4. **CI `softprops/action-gh-release` v1 → v2** — Node 20 removal (Sept 2026).

✅ Released: `APP_VERSION` 1.1.0, release notes written, merged `beta` → `main`, all three platform binaries attached. CI caught (and we fixed) a Linux-only `libx11-dev` link gap on the first `beta` push, before the release.

### v1.1.1 — shipped 2026-06-10

More extraction-gap fixes + polish, headlined by the macOS launch-crash fix. **Shipped without a launch test on real Apple Silicon** — no Mac hardware available; the fix removes the crashing code path entirely (canvas-only on macOS), but the first mac user report is the real confirmation. If a mac user still reports a launch crash, get the OS crash report (Console.app → Crash Reports) — app.log won't capture native crashes.

- **macOS: GPU renderer crashed the app at launch** — *ship this asap.* Tk Aqua's `winfo_id()` returns an internal `MacDrawable` pointer, not an NSView; `tuner_renderer` handed it to wgpu's Metal backend, which segfaults in `objc_msgSend` during surface creation — a native crash the Python fallback can't catch. v1.1.0 was the first release to bundle the renderer on macOS *and* the tuner tab is the default tab, so the v1.1.0 mac zip most likely crashes on launch (the release notes told v1.0.0 mac users to upgrade into it, for the mic fix). Fixed three ways: `tuner/view.py` never imports `tuner_render` on darwin, `build.py` never bundles it on darwin, CI no longer Rust-builds on the macOS runner. Macs are canvas-only by design now (docs updated). SSC ships the same renderer — **check whether SSC's macOS build has the same crash** (handoff prompt was written for an SSC-repo Claude session, 2026-06-10).
- **macOS: Cmd-Q never saved settings** — Cmd-Q / app-menu Quit fire `::tk::mac::Quit`, which exits without running the `WM_DELETE_WINDOW` handler, so `_on_close` (and settings save) never ran on the standard mac quit path. Fixed: `main.py` routes `::tk::mac::Quit` through `_on_close` on darwin.
- **Exerciser engine: guarded stream stop()** — `AudioEngine.stop()` now swallows PortAudioError from `stop()`/`close()` (device vanished mid-session, e.g. Bluetooth disconnect) so tab switches and app close still complete. Mirrors `TunerEngine.stop()`.
- **Tuner Settings menu** — `_tuner_open_settings` (stripe/faceplate color, brightness, octave boost, input-device picker, on-screen FPS toggle) existed but nothing opened it; the extraction dropped SSC's `Tuner > Settings...` menu wiring. Now wired via `TunerView.populate_menu()`.
- **Error logging** — rotating `app.log` + `sys.excepthook` + Tk `report_callback_exception` + Help > Open Log File. Another SSC-parity gap: the app ships `--windowed`, so prints went nowhere and Tk swallowed callback exceptions, leaving user crashes untraceable. (Catches Python errors, not native wgpu/Metal crashes — those need the OS crash report.)
- **Drone sample: cubic interpolation** — Catmull-Rom 4-tap replaces linear in `_render_sample_voices` for cleaner pitch-shifting. Increment 1 of the sample-quality work (see "Sample pitch-shifting quality" under Stretches).

Known macOS polish, not release-blocking: hardcoded 44.1 kHz streams (CoreAudio usually resamples, but a Bluetooth mic can refuse — retry with the device's `default_samplerate` would be cheap insurance), and the maximize fallback sizes the window to the full screen so the bottom edge can sit behind the Dock.

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

### Sample pitch-shifting quality — octave mipmaps (researched 2026-06-09, deferred)

**Problem.** `_render_sample_voices` resamples each drone voice by advancing a float playhead at `rate = (target_freq / sample_freq) * (sample_sr / output_sr)`. Beyond ~an octave from the source pitch this degrades two ways: (1) **aliasing** on upward shifts — the interpolator is a weak anti-alias filter, so partials above the new Nyquist fold back; (2) the natural **formant / "chipmunk" shift**. The use case that makes this matter: users loading **arbitrary existing WAV files** and droning them at **any octave** (not just tones recorded near the drone pitch).

**Already done (v1.1.x, `beta` — commit `095afc0`).** Swapped 2-tap linear interpolation for 4-tap **Catmull-Rom cubic** in `_render_sample_voices`. Removes interpolation grit everywhere; cleanly handles down-shifts and modest shifts. Does *not* anti-alias large upward shifts — cubic is a better interpolator, not an anti-alias filter.

**Approaches weighed and rejected:**
- **Phase vocoder** — the reflexive answer, but wrong here. It decouples pitch from *duration*, which is irrelevant for a looping drone. A vanilla PV still chipmunks (formants move with pitch); formant-preserving PV is the hard part — real-time multi-voice FFT, phase coherence, transient/loop handling. Multi-day, artifact-prone. No.
- **Additive / harmonic resynthesis** — would reuse the `rich`-synth oscillator bank, gives exact pitch with zero aliasing and optional formant hold. BUT it assumes a clean *harmonic* tone; it would wreck arbitrary/noisy/inharmonic WAVs (pads, voices, field recordings) by collapsing them to a buzzy harmonic series. Wrong for the "any WAV" use case. No.
- **Formant preservation in general** — *not wanted.* Deliberately pitching a sample and hearing its timbre move is normal, expected sampler behavior — part of the fun. The actual defect is digital aliasing, not the formant shift.

**Chosen direction (if revisited): octave mipmaps** — the standard hardware-sampler technique. Anti-aliased resampling that preserves the sample's real character (no synthesis). ≈ **half a day, moderate, low-risk** — the heavy work is offline at load, so the audio callback stays cheap.

1. **Build the pyramid (offline, in `_install_sample`):** ~3–4 levels, each = previous level low-passed then downsampled 2×. Lowpass = windowed-sinc FIR via `np.convolve` (no scipy needed). Two subtleties: filter **circularly** so the seamless loop survives each level, and carry the existing loop crossfade down each level. Memory ≈ 2× the sample (levels halve).
2. **Pick the level per voice (real-time, in `_render_sample_voices`):** `level = clamp(floor(log2(rate)), 0, maxlevel)`. Upshifts read an already-band-limited copy; downshifts use level 0. ~3 lines.
3. **Refactor the playhead — the key trick:** store each voice's playhead as a **normalized phase in [0, 1)** (fraction of the loop), not an absolute sample index. Then advance-per-output-sample = `rate / N_original` (**level-independent**), and read index at level L = `phase × len(level_L)`. That makes switching levels mid-note seamless. ~20–30 line rewrite of the render loop.

**Risks (all manageable):** lowpass quality (too weak → no benefit; too strong → dull samples); keeping the loop seamless at every level (circular filtering + the existing crossfade); clean transitions when a voice crosses a level boundary (the normalized phase handles it; an inter-level crossfade — "trilinear" style — is available if ever needed, but a drone won't need it).

**Verify when built:** before/after **spectral check** on an up-shifted render (high-frequency energy above the fundamental's harmonics should drop vs cubic-only) — not just "it runs"; plus seamless level transitions (no clicks as `rate` crosses a boundary) and no loop regressions (finite/bounded, still seamless).

**Do we need it?** Only matters for large *upward* shifts. Cubic already nails down-shifts and modest shifts. Worth the half-day if users pitch arbitrary WAVs up a lot (the stated use case); skippable if they mostly stay near or below source pitch.

## Done in v1.0.0

- Stroboscopic Tuner + Just Intonation Drone in one Tk window, mic-handoff on tab change
- Six visualizer modes: Lissajous, Waveform, Spectrum, Waterfall, Warp, Garden (beta)
- WAV-sample drone (load file or record from mic) with trim + crossfade for clean looping
- Garden with branching plants, leaves, species-styled flowers, fireflies
- Warm five-layer motor pilot, responsive tuner control bar
- Cross-platform builds (Win installer, macOS .app, Linux binary)
- CLAUDE.md + memory files in `~/.claude/projects/C--code-justatuner/memory/`
