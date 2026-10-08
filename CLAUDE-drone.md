# JustATuner — just intonation drone

*The drone engine (synth, WAV samples, recording, persistence, drone-bleed cancellation and the room table, progressions), the six visualizer modes, and the garden's architecture. Companion to CLAUDE.md; same rules, same voice. Edited in the same commit as the code it describes.*

## Exerciser engine (`exerciser/engine.py`)

Drone synthesizer + mic input + pitch detection in one class. Two independent rates: `in_sr` (mic; YIN, drone cancellation, Lissajous reference sine, recording) and `sr` (drone output; oscillator phase increments, sample playback rate). Input health is checked on the `get_pitch()` timer by `_check_input_health()`: if the input callback has been silent for `INPUT_STALE_S` (1.5 s) or the stream never opened, it reopens, paced by `INPUT_RETRY_S` (3 s) so an absent mic doesn't hammer PortAudio. `input_error` (None when healthy) drives the drone tab's **MIC** status line via `ExerciserView._update_mic_status`.

`_rebuild_oscillators` builds a per-voice list `_osc_freqs = [(freq, amp), ...]` driven by the current voicing (one of the eleven just-ratio chords in `VOICINGS`) and sound type:

- **sine**: one oscillator per voice
- **rich**: 8 partials per voice — the fundamental plus harmonics 2–8 at decreasing amplitude (8 / 16 / 24 oscillators for root / fifth / triad voicings)
- **sample**: one playhead per voice through the loaded `_drone_sample` buffer

`synthetic_hz` (default None) is the same test/CI hook `TunerEngine` has: `start()` opens no microphone, `get_pitch()` feeds a harmonic-rich tone through the callback's own path (`_push_input`), health checks stand down, and `input_open()` tells the MIC lamp the source is live.

**Drone-bleed cancellation** (`monitoring`, Exerciser Options > Monitoring, persisted; default "speakers"). The app generates the drone, so each sine/rich partial arrives at the mic as the same tone with one complex gain. When the drone starts, changes note, voicing or type, `_bleed_reset()` starts a listen: `BLEED_SETTLE_S` (0.4 s) for the sound to reach the mic, then `BLEED_LISTEN_S` (3 s) of Hann-windowed projections of the input ring onto every partial (`_bleed_project`), then `_bleed_fit()` gives each partial a gain at `_bleed_tref` and a phase-drift rate (the mic and speaker clocks differ by a few ppm). While listening `get_pitch()` returns no pitch and the view's DRONE line says "Listening to the room…". Once ready, `_cancel_drone` subtracts the predicted bleed and tracks the gains with a 4 s time constant only while no pitch has been detected for `BLEED_PAUSE_S`, so a held unison is never learned as bleed. "headphones" skips all of it; a WAV-sample drone keeps the old ±4 Hz notch (`_notch_drone`). All timing is in input-sample time (`_in_total`), so `test_drone_cancel` runs a simulated room faster than real time. `tools/measure_bleed.py` runs the same thing on real devices and prints per-partial level, drift and what the tab would read.

**The room table** (2026-10-07). The synth renders from a voice set (`_synth`) that the output callback swaps in from `_synth_pending` at a block boundary, crossfading over the first block (`CHORD_XFADE_FRAMES`) so a chord change does not click, and recording the output sample index at which the new phases started from zero (`epoch`, on `_out_total`). Every listen banks, per partial frequency, the amplitude and the phase relative to that epoch (`_room`, `_room_store`), plus one clock-difference number for the session (`_room_ppm`, from the partials' drift rates). A chord whose partials are all in the table (`room_known`) skips the listen: after the settle, `_room_derive` rebuilds the gains from the table and the new epoch. The table is cleared whenever a stream reopens. `VOICINGS` holds eleven just-ratio chords with `VOICING_LABELS` (menu) and `VOICING_SYMBOLS` (notation).

**Progressions** (`exerciser/progression.py`, the editor in `exerciser/progression_ui.py`, transport and plumbing in `ExerciserView._prog_*`). `Progression` = name + `Step`s (root, voicing, length) + mode (`bars` at a BPM with beats per bar, `seconds`, `manual` on a key) ; notation `C | F | G7:2 | Am` via `parse_steps` / `format_steps`; `PRESETS`; the user's own in `progressions.json` in the config folder. `ProgressionPlayer` is ticked from `_update_analysis` with `time.monotonic()`: in speakers mode it sounds each distinct chord not yet in the room until `bleed_status()` is "ready", then a count-in (one bar / two seconds; none in manual), then steps on time or on `next()`; `apply_chord` is the view's `_prog_apply_chord` (root button, voicing, engine). The manual-advance key is a Tk keysym (`advance_key`, default `space`), bound with `bind_all` and ignored while a text field has focus. Both the last progression and the key persist in `exerciser_settings`. MIDI entry is on the roadmap (needs a native MIDI library proven in CI first).

For sample mode, `_render_sample_voices` runs in the audio callback and per-voice computes the playback rate as `(target_freq / sample_freq) * (sample_sr / output_sr)`, advances a float playhead through the sample buffer with wrap, interpolates with a Catmull-Rom cubic (4-tap; taps wrap mod-N across the crossfaded loop boundary), sums all voices, normalizes. Was 2-tap linear before v1.1.1 — cubic is audibly cleaner when a sample is pitched well away from its source note.

## WAV-sample drone (`_install_sample` in `exerciser/engine.py`)

Loaded WAV files and live recordings both go through `_install_sample`, which does three things before storing the buffer:

1. **Trim attack + release** — up to 200ms from each end, capped at 10% of total length. Drops onset and decay so the looping region is steady-state.
2. **Pitch detection** — YIN on a 2-second window centered on the trimmed middle (fmin 55, so A1 is in range). Used both for the per-voice playback rate AND for sizing the crossfade. Falls back to A4 (440 Hz) at low confidence.
3. **Period-aligned linear crossfade at the loop boundary** (since 2026-10-06; see the traps for what the equal-power version did) — the sample is trimmed to a whole number of periods of the detected pitch, and the last L samples become `tail * (1 - t) + head * t` where L is a whole number of periods too (4, fewer under the 150 ms / 25 % caps, 64-sample floor). Head and tail of a steady tone are then in phase, the level stays flat through the fade, and the mod-wrap from index L-1 to 0 in `_render_sample_voices` lands on the next sample of the waveform.

`_read_wav_file` at the bottom of the module handles 16/24/32-bit PCM through the stdlib `wave` module and 32/64-bit IEEE-float WAVs through `_read_float_wav` (a small RIFF reader, because `wave` refuses format tag 3). Stereo is downmixed to mono by averaging.

## Recording

`record_start()` / `record_stop_and_use()` / `record_cancel()` work with the existing input stream — the input callback appends each frame to `_recording_chunks` while `_recording` is True. The recording UI in `RecordSampleDialog` (`exerciser/view.py`) polls `engine.recorded_duration_s()` for the elapsed counter. 1.5-second hold-off on the Stop button so an accidental double-click can't immediately abort.

## Sample persistence

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
