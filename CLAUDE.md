# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JustATuner is a free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one Tk window:

- **Stroboscopic Tuner** — a 12-wheel chromatic strobe-style tuner, extracted from [Stohrer Sax Shop Companion][ssc] where it grew up in real saxophone repair shops. Optional Rust/wgpu GPU renderer on Windows/Linux, with Tk canvas fallback; macOS is canvas-only (Tk Aqua has no per-widget NSView for wgpu to draw into).
- **Just Intonation Drone** — drone synthesizer (sine / rich / WAV sample) with live JI interval analysis and six visualizer modes including a Geiss-style waterfall and an audio-driven branching garden. Originally the [JustATone][jat] Python prototype, preserved here after that project pivoted to a Rust/bevy generative-art garden.

[ssc]: https://github.com/stohrermusic/Stohrer-Sax-Shop-Companion
[jat]: https://github.com/stohrermusic/justatone

## Traps, each paid for once — do not pay twice

One dated bullet per expensive lesson, phrased as the mechanism, with the gate that now protects it. Newest first.

- **2026-10-06 — The one-neighbour Hann form d = (2a−1)/(a+1) is exact on a steady lobe but biased on a lobe broadened evenly on both sides**, which is what a note decaying during the frame produces: a 20 ms decay on bin 40 read +0.105 bin (4.5 c at A4, 18 c at A2), so a plucked or struck note flicked the strobe. The two-neighbour form d = 2(R−L)/(L+2P+R) reduces to d on a clean lobe and reads the decaying note within 0.002 bin. Found by `test_audio_utils`; gated by the decaying-note check in `test_tuner_engine`. SSC's `hann_peak_freq` still has the one-neighbour form.
- **2026-10-06 — The stdlib `wave` module refuses IEEE-float WAVs ("unknown format: 3"), so a "probe the first 1024 samples as float32" guess in the reader only ever fired on int32 files.** Any int32 file that starts quietly (leading silence) decoded its tone as float bit patterns: NaN and 1e38 into the drone, which `np.clip` passes through. 4-byte PCM is int32; real float files go through `_read_float_wav`. Gated in `test_sample_pipeline`.
- **2026-10-06 — A loop crossfade must be a whole number of periods, and so must the sample; equal-power curves are wrong for correlated signals.** `4 * int(sr/f)` truncated 200.45 to 200 samples (seam 2.8× a normal step), and cos/sin equal-power curves on a steady tone's in-phase head and tail swelled or dipped the level by +3/−4 dB once per loop depending on the sample length, which also pushed a 0.95-normalised recording past full scale. Period-aligned trim plus a period-aligned linear fade: seam 0.026 vs p99 step 0.031, level within ±1.5 dB. Gated in `test_sample_pipeline`.
- **2026-10-06 — YIN's `tau_max = int(sr / fmin)` stops two lags short of fmin's own period**, so a tone at exactly fmin is undetectable: an A1 (55 Hz) sample fell back to 440 and played three octaves off; C2 was missed at a 16 kHz input rate. Now `ceil(sr/fmin) + 2`. Gated in `test_sample_pipeline` and `test_exerciser_engine`.
- **2026-10-06 — `UnicodeDecodeError` is a `ValueError`, not an `OSError` or `JSONDecodeError`**, and it is raised inside `fp.read()` before the JSON parser. `load_settings` caught only the latter two, so a settings file with bytes that aren't UTF-8 stopped the app launching (settings load on the first line of `JustATunerApp.__init__`). Catch `ValueError`. Gated in `test_config`.
- **2026-10-06 — The drone-cancellation notch (±4 Hz round every partial, rectangular window) cannot hide the drone itself**: with speakers the drone reads as a played unison at confidence 0.97 through its own notch's leakage, a just third over the bleeding drone reads −12 c and a fifth −5.5 c. With headphones (no bleed) the notch biases a unison by about +1 c. Wider and Hann-windowed notches were measured and rejected (30–80 c unison bias); no notch loses the third under bleed entirely. "Headphones recommended" in the UI is the honest answer; `test_exerciser_engine` pins the numbers. Also: measure with phase-continuous signals — pushing identical 4096-sample blocks puts a phase jump mid-buffer and produced a false +10 c "bias" first.

- **2026-10-06 — Aqua ignores a `tk.Button`'s `bg`**, so the Tuner Settings colour swatches were blank white buttons on the Mac (first `mac-tour` shots). Swatches are now small `tk.Canvas` widgets with a `<Button-1>` binding; canvas and label backgrounds do render on Aqua.
- **2026-10-06 — Windows' software rasterizer (WARP, "Microsoft Basic Render Driver") reports `device_type == IntegratedGpu` under Dx12**, not `Cpu` (seen on the CI runner's log). The software-adapter check matches it by name as well; llvmpipe on Linux does report `Cpu`.
- **2026-10-06 — The macOS runner's screen is about 1024×768; the WM clamps a larger `geometry()` request.** The tour now sizes its window to the screen and writes the window, screen and requested-content sizes into `tour-done.txt`. What that showed (open, not fixed): at ~975×650 the drone tab's bottom status row (the MIC lamp) is clipped on a Mac — the app's `minsize(960, 620)` is below what the drone tab needs on Aqua. A design call for Matt before changing the layout or the minsize.

- **2026-10-06 — A `tk.StringVar` that only a widget references is garbage-collected, and tkinter unsets the Tcl variable when it goes.** The Tuner Settings combobox stored just the variable *name*; the Python `StringVar` was a local of `_tuner_open_settings`, collected on return, and the Input Device box showed blank (tour screenshot). Keep the var on the dialog (`dlg._mic_var`). Any `textvariable` built inside a function needs an owner that outlives the function.
- **2026-10-06 — A positionless `Toplevel` lands at the screen's top-left, not over the app.** Settings and latency dialogs now set their geometry relative to the root. Seen in the tour, where both covered the wrong window.
- **2026-10-06 — Tk reports logical pixels; a screen grab is physical.** The Python process is not DPI-aware, so on this 250 % laptop `winfo_rootx()` is 2.5× short of the pixel the grab needs, and the first tour pictures were a corner of the browser behind the app. `run_tour()` scales the crop by the grab's width over `winfo_screenwidth()`. Also: a window opened from a background process is not raised; the tour raises it (topmost set then *cleared* — left on, it covered the non-transient user-guide window in its own shot).
- **2026-10-06 — ttk QUEUES `<<NotebookTabChanged>>` for the initial `select()`; it fires on the next event-loop pass, whenever the binding was made.** So "bind after select" does not stop it, and the old bind-then-select-then-call-manually started the engine twice. `_on_tab_changed` ignores an event for the tab that is already active (`_active_tab_id`); `JustATunerApp(autostart=False)` therefore really starts nothing. Gated by `test_tuner_canvas` (the no-mic pass would see a live stream otherwise).
- **2026-10-06 — Constructing the wgpu surface on a frame that is not yet viewable fails `Surface::configure` with "Invalid surface".** The tour's un-maximize + `geometry()` delivered a `<Configure>` before the toplevel was shown. `_tuner_build_wheels_gpu` returns while `winfo_viewable()` is false and the animate loop retries each frame.
- **2026-10-06 — A Rust panic reaches Python as `pyo3_runtime.PanicException`, a `BaseException`; `except Exception` lets it into Tk's callback.** Measured: `isinstance(e, Exception)` is False. Every surface call in `tuner/view.py` catches `BaseException` (re-raising `KeyboardInterrupt`/`SystemExit`) and goes through one `_tuner_gpu_fallback(reason)`; a single bad `render()` is a dropped frame, `GPU_RENDER_FAIL_LIMIT` (30) in a row switch to the canvas; never retry the GPU on the same frame, a failed configure leaves the surface dead. Gated by `test_gpu_tuner` section 4.
- **2026-10-06 — `Limits::downlevel_defaults()` caps textures at 2048 px; a 1400 px frame at 150 % is already past it and `Surface::configure` panics.** Measured on this PC with the old crate: 3500×1500 panicked ("maximum extent for either dimension is 2048"). Now `downlevel_defaults().using_resolution(adapter.limits())` plus `clamp_surface()` on every configure. Gated by `test_gpu_tuner` section 3.
- **2026-10-06 — `PresentMode::Fifo` blocks `render()` on the Tk thread until vsync: 16.67 ms/frame measured.** Mailbox where the surface offers it: 0.16 ms/frame on Intel UHD / Dx12. A software rasterizer (`device_type == "Cpu"`) counts as no GPU and takes the canvas path.
- **2026-10-06 — `canvas.delete("all")` in the wheel rebuild wiped the "Audio error" text, so a user with no microphone saw dark wheels and no explanation after the first resize.** `_tuner_error_state` is kept and redrawn at the end of every rebuild, cleared on a successful start. Gated by `test_tuner_canvas` pass 0 (2 checks fail on the old rebuild).
- **2026-10-06 — A `root.update()` loop livelocks when a frame outlasts its `after()` interval** (SSC measured a 25 s stall in `canvas.coords`): `update()` keeps servicing the already-due reschedule and never returns. GUI suites drive frames with `root.after(ms, root.quit); root.mainloop()`, and wait for the engine's `_synth_pos` to pass ~20×1024 before reading labels (the readout is per frame, not damped).
- **2026-10-06 — `defaults write -g AppleInterfaceStyle Dark` does not change a running login session** (SSC's first dark tour came back light). The CI dark tour also runs the `osascript` appearance switch and the app forces its own windows with `--appearance dark`; `tour-done.txt` records each shot's measured mean brightness, and since this app is dark by design the dialog stops are the ones to compare.
- **2026-10-06 — A parabola through three linear magnitudes is the wrong shape for a Hann main lobe: up to 0.05 bin off, which on 10.77 Hz bins is 0.54 Hz, 17 c at A1.** Measured on the old engine: in-tune A1–A6 read up to +15.3 c (B1), A2 −7.8 c, A4 +1.3 c, so the strobe turned on a dead-on note. `audio_utils.hann_peak_freq` climbs ≤2 bins to the lobe top and reads d = (2a−1)/(a+1) from the larger-neighbour ratio: pure sine A1–A6 worst 0.13 c; with a −6 dB second harmonic 0.72 c at A1 (the harmonic is 5 bins up and its sidelobe lands on the fundamental's neighbours) and under 0.3 c from C2. Rejected, measured in SSC: 4× zero-padded FFT, same accuracy, 4× cost. Gated by `test_tuner_engine` (7 of 14 accuracy checks fail on the old code).
- **2026-10-06 — One combined `try: import numpy; import sounddevice` set `np = None` whenever sounddevice was missing**, taking every pure-math path down with it. Imported separately now; `AUDIO_AVAILABLE = np is not None and sd is not None`. Gated by the child-interpreter probe in `test_tuner_engine`.
- **2026-10-06 — `os._exit` skips Python's buffer flush**, so the selftest verdict is written with `os.write(1, …)` (guarded: a windowed .exe may have no fd 1).

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

Dependencies: `numpy`, `sounddevice`, `pillow`, `pyinstaller` (for building). The GUI uses Python's built-in `tkinter`. Requires Python 3.11+.

## Tests

```bash
python tools/run_tests.py              # every tools/test_*.py, PASS/FAIL per suite
python tools/run_tests.py engine       # suites whose name contains a word
python tools/run_tests.py --skip gpu --allow-missing sounddevice
python tools/test_tuner_engine.py      # one suite directly
python main.py --selftest              # SELFTEST OK / SELFTEST FAIL, exit 0/1
python main.py --tour all --shots DIR [--appearance dark]   # screenshot every stop
```

Each `tools/test_*.py` is a standalone script, not pytest; the runner executes each in its own interpreter from the repo root (same as SSC). Ten suites as of 2026-10-06, 43 s locally, about 330 checks:

- `test_tuner_engine` — pure math, no display: the Hann estimator on a pure lobe (<0.01 bin) and on a decaying note, in-tune A1–A6 sweeps (pure sine <0.5 c; with a −6 dB H2 <1.0 c, C2–A6 <0.5 c), off-pitch A2–A5 within 0.15 c, the strobe standing still on an in-tune note, B5 26 c flat, numpy surviving a blocked sounddevice (child interpreter), and the synthetic source through `analyze()`.
- `test_audio_utils` — the ring buffer, `synthetic_tone` phase continuity, the estimator's climb and clamp, the sample-rate fallback for input and output on a fake sounddevice, `TunerEngine` on a 16 kHz device, the saved-device fallback, the stale-stream restart, `silent_seconds`.
- `test_exerciser_engine` — YIN over C2–C7 at 44.1 kHz and D2–C6 at 16 kHz, the JI interval math, note naming, transposition, presets and voicings, `get_pitch` on the synthetic source, and the drone-cancellation notch as measured (headphones and speakers).
- `test_sample_pipeline` — the WAV reader (16/24/32-bit PCM, float32/float64, stereo), sample install (trim, pitch, period-aligned crossfade, seam, level), pitched playback, synth output, recording, save and clear.
- `test_config` — settings load/merge/corruption/round trip, device resolution by name, prefix and legacy index, the device filter, logging.
- `test_audio_latency` — the loopback measurement on a mocked device: delays, noise, echo cancellation, disagreeing chirps, rate fallback.
- `test_gpu_tuner` — the `tuner_render` API, the renderer.rs / view.py source contract, a 3500×1500 surface, `adapter_info` / `present_mode`, 60 frames timed, and the 30-failure fallback on the real app. Skips the wheel-dependent parts when the wheel is not built (set `JUSTATUNER_REQUIRE_GPU=1` on a machine that built it to make a broken wheel fail loudly) and the construction cases on a runner with no GPU surface.
- `test_tuner_canvas` — the real tuner tab end to end: pass 0 no mic (error text drawn and surviving a rebuild, MIC lamp dark), pass 1 canvas mode on the synthetic tone (12 wheels, A brightest, readout A / IN TUNE, lamp green, 0 c through the live path), pass 2 the GPU build (live renderer with zero failures, or the designed fallback with the CPU-mode notice).
- `test_drone_tab` — the real drone tab end to end on a just major third above its root: Major 3rd, 5:4, LOCKED, "Playing: E3", the ET-difference line, Bb transposition, every visualizer mode drawing without a Tk exception, the "Phase Wheel" mode migration, tab switch, save.
- `test_tour` — `run_tour` with screenshots off as a gate on every platform (12 stops, no error), Tuner Settings opening with "System Default", the latency dialog.

Rules the suites follow, each from a trap above: an isolated profile via **`JUSTATUNER_CONFIG_DIR`** set before `config` is imported (never the user's settings); `builtins._` installed before importing `tuner.view`; `tkinter.messagebox` stubbed so the exception hook's dialog cannot block; **`JustATunerApp(autostart=False)`** so the test sets `synthetic_hz` before the first start and starts via `app._on_tab_changed()`; frames driven with `root.after(ms, root.quit); root.mainloop()`, never a `root.update()` loop; `check()` fails on a returned `False` as well as on an exception.

**`--selftest`** (`_selftest()` in main.py) builds both tabs in a withdrawn root, runs the tuner on the synthetic tone (≥20 frames, readout A, no error state), switches to the drone tab on a synthetic just major third and requires the panel to say "Major 3rd", and exits 0/1 without saving. CI runs it against the frozen binary on every platform — the one check that runs the shipped bundle. **`--tour all --shots DIR`** (`run_tour()`) walks 12 stops — tuner with the real mic, tuner on the tone, Tuner Settings, the drone tab in all six visualizer modes, the latency dialog, the user guide — screenshots each cropped to the app's windows, and writes `tour-done.txt` with each shot's mean brightness and any step errors. Help > About is a native messagebox and is not toured. Modal stops work because each stop's finish is scheduled with `after()` before its open is called. The macOS build job runs the tour light and dark and uploads `mac-tour`; those pictures are how the Mac UI gets reviewed. Driven on this PC (2026-10-06, 12 shots, three findings fixed); not yet seen on a Mac.

## Smoke Testing Patterns

Patterns that caught real bugs during the v1.1.3 work; use them before claiming a UI or audio change works:

- **Drive the real app on a hidden root.** `app = main.JustATunerApp(autostart=False); app.root.withdraw()`, then drive frames with `app.root.after(ms, app.root.quit); app.root.mainloop()` (not a `root.update()` loop — see the traps). Select tabs with `app.notebook.select(app.exerciser_frame)` (the queued tab event starts that tab), poke engine state, read widgets. Withdrawing avoids flashing a window at whoever is watching the screen (and them closing it mid-test). Widget sizes are still available via `winfo_reqheight()`; wheels are not built while the frame is unviewable, but the readout labels still update.
- **Monkeypatch `tkinter.messagebox`** (`showerror`/`showinfo`/`showwarning` to print) before importing `main`, or the exception hook's error dialog blocks the update loop forever.
- **Open the lazy-import dialogs.** `tuner/view.py`'s settings dialog imports `config.get_input_devices` and `ui_dialogs.add_tooltip` *inside* `_tuner_open_settings`, so `import tuner.view` succeeding proves nothing; two releases shipped with the dialog raising ImportError. Call `app.tuner._tuner_open_settings()` and confirm a `Tuner Settings` Toplevel appears.
- **Mock sounddevice for the macOS-only paths.** Windows MME accepts any sample rate (it resamples), so the CoreAudio "Invalid sample rate" fallback never fires here. Set `tuner.engine.sd = FakeSD` where `FakeSD.InputStream` raises on 44100 and `query_devices` reports a 16 kHz default, then feed `engine._ring_buffer.write(sine)` and check `analyze()` lights the right wheel.
- **Silence detection can't be tested with the real mic** (it keeps resetting the timer); stub `engine.silent_seconds = lambda: 10.0` for the UI path and call `_audio_callback` with zeros/non-zeros directly for the engine path.
- **`python audio_latency.py`** runs the loopback latency test standalone. On the dev laptop the Intel Smart Sound mic array cancels its own speaker output, so use the Realtek "Stereo Mix" input to validate the pipeline, or mock `sd.playrec` to return a delayed copy of the signal.
- **Lint**: `ruff check --select F,E9 <files>`. `tuner/view.py` has ~43 baseline `F821 Undefined name _` hits because `main.py` injects `_` as a builtin; compare counts against `git show HEAD:<file>` rather than reading the raw total.

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

**macOS microphone permission**: on macOS the build runs `_patch_macos_plist()` after PyInstaller, injecting `NSMicrophoneUsageDescription` into `dist/JustATuner.app/Contents/Info.plist`. macOS *silently* denies mic access to any app that doesn't declare it — the tuner wheels never move and the drone analyzer sees no input — and PyInstaller doesn't add the key. This mirrors SSC's `build.py`; the SSC extraction originally dropped the step (restored on `beta`).

The key alone is **not sufficient**: PyInstaller ad-hoc signs the bundle during build, and Info.plist is sealed into that signature. Patching the plist afterwards breaks the seal, and TCC refuses to show the permission prompt for an app whose signature doesn't validate — same silent-denial symptom, mic key present. v1.1.0 and v1.1.1 shipped this way. `_resign_macos_app()` therefore re-signs ad-hoc (`codesign --force --deep --sign -`) after the patch. Packaging matters too: CI zips the `.app` with `ditto -c -k --keepParent`, because `zip -r` follows the bundle's Frameworks↔Resources symlinks and stores them as duplicate files, breaking the resource seal on extraction. CI verifies all of it — `plutil -extract` for the key, `codesign --verify --deep --strict` on the built app, and again on an unzipped copy of the final artifact.

## Module Structure

```
main.py                 → Tk root + two-tab Notebook + on_tab_changed engine
                          swap; exception hooks (sys.excepthook + Tk
                          report_callback_exception → app.log + error dialog);
                          --selftest (_selftest) and --tour all (run_tour)
config.py               → DEFAULT_SETTINGS, settings I/O, per-platform config
                          dir (JUSTATUNER_CONFIG_DIR overrides it for tests),
                          setup_logging() (rotating app.log),
                          get_input_devices() + resolve/remember_input_device()
audio_utils.py          → AudioRingBuffer, hann_peak_freq() (Hann closed-form
                          peak estimator), synthetic_tone() (test source), and
                          open_input_stream()/open_output_stream() sample-rate
                          fallback helpers (shared by both audio engines)
tools/run_tests.py      → runs every tools/test_*.py (see Tests)
tools/test_*.py         → test_tuner_engine, test_gpu_tuner, test_tuner_canvas
audio_latency.py        → Help > Test Audio Latency…: loopback round-trip
                          measurement (chirps out, cross-correlate mic);
                          pure numpy + sounddevice, dialog lives in main.py
status_lamp.py          → StatusLamp canvas widget (green/amber/red/dark)
                          used for the MIC indicator on both tabs
ui_dialogs.py           → add_tooltip()/Tooltip, ported from SSC (only the
                          tooltip part); tuner settings dialog imports it
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

**Tab-specific menus**: each tab rebuilds the menubar when it becomes active. The exerciser contributes Drone / Exerciser Options menus; the tuner contributes a **Tuner** menu whose **Settings…** entry opens `_tuner_open_settings` (stripe/faceplate color, ring + overall brightness, octave boost, input-device picker, on-screen FPS toggle). Some tuner controls are also inline (sensitivity, reference pitch, transposition, waveform). The Tuner menu's wiring was missing until v1.1.x — the dialog existed but nothing opened it (an extraction gap) — and once wired, the dialog raised ImportError until v1.1.3 because neither `config.get_input_devices` nor `ui_dialogs.add_tooltip` (both imported inside `_tuner_open_settings`) had been extracted. Any smoke test of the tuner should actually open Tuner > Settings… — the imports are lazy, so `import tuner.view` succeeding proves nothing.

**Settings persistence**: `config.load_settings()` does a two-level deep merge with `DEFAULT_SETTINGS` so old config files survive new keys being added. Save happens on app close in `JustATunerApp._on_close` via both views' `save_settings()` methods.

**Input device by name**: the persisted mic choice is `audio_input_device_name`; `audio_input_device` (the PortAudio index) is only a cache. PortAudio renumbers devices whenever USB/Bluetooth devices come and go, so both views call `config.resolve_input_device(settings)` at start (name match → prefix match → migrate a legacy index → system default) and `config.remember_input_device(settings, idx)` when the user picks one. Both tabs share the one saved device.

**Error logging**: `config.setup_logging()` writes a rotating `app.log` (500KB, 1 backup) to the config dir. `main.py` wires both `sys.excepthook` and Tk's `report_callback_exception` to `_handle_exception`, which logs the full traceback and shows a dialog pointing at **Help > Open Log File**. The shipped app is `--windowed`/`--noconsole`, so `print()` goes nowhere — use `logging` for anything diagnostic (the root logger is at WARNING, so log audio-device trouble at WARNING). Native crashes (e.g. in a GPU driver) bypass all of this; those need the OS crash report.

**MIC lamp**: both tabs show a `StatusLamp` for the input stream, separate from the motor pilot (which only means "tuner running"). Tuner: to the right of the VU meter in the control bar's right column (`vu_frame` holds `vu_inner` = meter + readout, then `mic_col`; keep it beside the meter, not below — below made the whole control panel taller). Drone: in the status panel under DRONE. States, from `TunerView._tuner_update_mic_label` / `ExerciserView._update_mic_status`: **green** good input; **amber** + "no signal" when `engine.silent_seconds()` > `SILENT_WARN_S` (3 s of exact digital zeros while the stream is alive — the denied-macOS-permission / muted-input signature; a quiet room still has a noise floor); **amber** + "low quality input" when the rate is under `LOW_QUALITY_INPUT_HZ` (32 kHz, i.e. a Bluetooth hands-free link); **dark** when there is no mic input (stream closed or dead; the drone tab also prints the open error as text since it has nowhere else to say why). Texts are deliberately terse. Both updaters run on their existing frame timers and only touch widgets when the state changes.

**Latency test**: `audio_latency.measure()` opens one full-duplex `sd.playrec` stream (shared clock for both directions, output device chosen on the *same host API* as the input or Windows raises "Illegal combination of I/O devices"), plays three Hann-windowed 500–3000 Hz chirps 0.7 s apart, cross-correlates each search window against the chirp, and reports the median lag when at least two readings agree within 15 ms. The driver's `stream.latency` is reported alongside as "buffering only". `main.py._open_latency_test` stops both engines for the run and restarts the active one via `_on_tab_changed` when the worker thread finishes, even if the dialog was closed. Laptop mics with driver-level echo cancellation (Intel Smart Sound on the dev machine) swallow the chirps; the failure message says so. Validated against the Realtek Stereo Mix loopback (90 ms, three agreeing readings) and a synthetic delayed-echo mock.

**Sample rate is negotiated, never assumed**: both engines *prefer* 44.1 kHz but open through `audio_utils.open_input_stream()`/`open_output_stream()`, which retry at the device's `default_samplerate` when it refuses. Windows and PulseAudio resample transparently so the retry never fires there; CoreAudio does not, and a Bluetooth HFP mic (16/24 kHz) or an interface pinned to 48 kHz raises "Invalid sample rate". `TunerEngine.sample_rate`, `AudioEngine.in_sr` (mic) and `AudioEngine.sr` (drone output) hold the live rates and every bit of frequency math reads them — the `SAMPLE_RATE` constants are only the preference.

## Audio Engines

### Tuner engine (`tuner/engine.py`)

12 chromatic pitch classes, each with seven concentric rings (one per octave). FFT-based pitch detection with per-pitch-class phase tracking — phase deviation drives the stroboscopic rotation effect. Magnitude normalization is gated: `max_mag` must exceed `threshold * 1.5` before normalizing to 0–1, otherwise all magnitudes are zeroed. This prevents sensitive mics from showing wheel activity on room noise.

Peak frequency (both the per-ring estimate and the strongest-octave estimate that drives the VU and the wheel phase) comes from `audio_utils.hann_peak_freq`, the Hann closed form — not a parabola, which read in-tune low notes up to 15 c off (see the traps). Magnitudes are read as before.

`synthetic_hz` (default None) is the test/CI source: when set, `start()` opens no stream, sizes the ring buffer itself, and `analyze()` feeds `audio_utils.synthetic_tone` (fundamental + −6 dB H2, phase-continuous from `_synth_pos`) before the stale check. `silent_seconds()` stays 0 (no stream), so the MIC lamp reads green. Nothing in normal use sets it.

Audio stream health monitoring via `AudioRingBuffer.is_stale()` — if no new audio data arrives for ~1 second, the engine restarts the sounddevice stream. Recovers from silent callback death on Windows. The ring buffer is sized at open to `max(rate × 0.2 s, FFT_SIZE)` so a 16 kHz stream still fills one FFT frame.

`start(device)` falls back to the system default when the requested device won't open (unplugged since it was saved, grabbed exclusively, index shifted) and logs a warning; `_last_device` is updated so auto-restarts stay on the working device.

### Exerciser engine (`exerciser/engine.py`)

Drone synthesizer + mic input + pitch detection in one class. Two independent rates: `in_sr` (mic; YIN, drone-notch, Lissajous reference sine, recording) and `sr` (drone output; oscillator phase increments, sample playback rate). Input health is checked on the `get_pitch()` timer by `_check_input_health()`: if the input callback has been silent for `INPUT_STALE_S` (1.5 s) or the stream never opened, it reopens, paced by `INPUT_RETRY_S` (3 s) so an absent mic doesn't hammer PortAudio. `input_error` (None when healthy) drives the drone tab's **MIC** status line via `ExerciserView._update_mic_status`.

`_rebuild_oscillators` builds a per-voice list `_osc_freqs = [(freq, amp), ...]` driven by the current voicing (root / root+fifth / major / minor) and sound type:

- **sine**: one oscillator per voice
- **rich**: 8 partials per voice — the fundamental plus harmonics 2–8 at decreasing amplitude (8 / 16 / 24 oscillators for root / fifth / triad voicings)
- **sample**: one playhead per voice through the loaded `_drone_sample` buffer

`synthetic_hz` (default None) is the same test/CI hook `TunerEngine` has: `start()` opens no microphone, `get_pitch()` feeds a harmonic-rich tone through the callback's own path (`_push_input`), health checks stand down, and `input_open()` tells the MIC lamp the source is live.

For sample mode, `_render_sample_voices` runs in the audio callback and per-voice computes the playback rate as `(target_freq / sample_freq) * (sample_sr / output_sr)`, advances a float playhead through the sample buffer with wrap, interpolates with a Catmull-Rom cubic (4-tap; taps wrap mod-N across the crossfaded loop boundary), sums all voices, normalizes. Was 2-tap linear before v1.1.1 — cubic is audibly cleaner when a sample is pitched well away from its source note.

### WAV-sample drone (`_install_sample` in `exerciser/engine.py`)

Loaded WAV files and live recordings both go through `_install_sample`, which does three things before storing the buffer:

1. **Trim attack + release** — up to 200ms from each end, capped at 10% of total length. Drops onset and decay so the looping region is steady-state.
2. **Pitch detection** — YIN on a 2-second window centered on the trimmed middle (fmin 55, so A1 is in range). Used both for the per-voice playback rate AND for sizing the crossfade. Falls back to A4 (440 Hz) at low confidence.
3. **Period-aligned linear crossfade at the loop boundary** (since 2026-10-06; see the traps for what the equal-power version did) — the sample is trimmed to a whole number of periods of the detected pitch, and the last L samples become `tail * (1 - t) + head * t` where L is a whole number of periods too (4, fewer under the 150 ms / 25 % caps, 64-sample floor). Head and tail of a steady tone are then in phase, the level stays flat through the fade, and the mod-wrap from index L-1 to 0 in `_render_sample_voices` lands on the next sample of the waveform.

`_read_wav_file` at the bottom of the module handles 16/24/32-bit PCM through the stdlib `wave` module and 32/64-bit IEEE-float WAVs through `_read_float_wav` (a small RIFF reader, because `wave` refuses format tag 3). Stereo is downmixed to mono by averaging.

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

# 6. Watch the release-event run (not the push runs) and confirm all
#    three assets landed; the release page is live before CI finishes.
gh run list --limit 4 --json databaseId,event,status,displayTitle
gh run watch <release run id> --exit-status --interval 30
gh release view vX.Y.Z --json assets --jq '.assets[] | "\(.name) \(.size)"'
```

Expect roughly 36 MB for the Windows installer, 22 MB for the macOS zip (a ~70 MB zip means `zip -r` crept back in and the signature seal is broken), and 53 MB for the Linux binary. Then `git checkout beta` so the next change does not land on `main`, and update the shipped-version entry in the `TODO.md` ledger.

## CI/CD (GitHub Actions)

Single workflow at `.github/workflows/build.yml`. Three matrix entries:

- **`windows-latest`** — Python 3.11, `pip install -r requirements.txt`, `python build.py`, then Inno Setup (`choco install innosetup`) wraps `dist\JustATuner.exe` into `JustATuner-Windows-Setup-{APP_VERSION}.exe`. Only the installer is published; the bare `.exe` is not.
- **`macos-latest`** — Apple Silicon. Same Python install, `python build.py` produces `dist/JustATuner.app`, packaged to `JustATuner-macOS.zip` with `ditto -c -k --keepParent` (preserves the bundle's internal symlinks; `zip -r` would break the code-signature seal). CI verifies the mic key and the code signature, including on an unzipped copy of the final artifact.
- **`ubuntu-latest`** — `apt-get install libportaudio2`, then build, rename to `JustATuner-Linux`.

Before the PyInstaller step, the Windows and Linux runners install the Rust toolchain (`dtolnay/rust-toolchain@stable`) and `maturin build` the `tuner_renderer/` crate, then `pip install` the resulting `tuner_render` wheel so `build.py` bundles the GPU strobe renderer. Adds a Rust compile (~1–2 min/runner) to those builds. The macOS runner skips the Rust steps entirely — macOS is canvas-only (see Per-Platform Constraints).

Triggers: push to `main` or `beta`, release `created`, manual `workflow_dispatch`. On release events, the `softprops/action-gh-release@v2` step attaches each platform's artifact to the release page (bumped from `@v1`, which ran on the soon-to-be-removed Node 20).

Since 2026-10-06 the build job is preceded by a **`lint`** job (`ruff check .`, config in `ruff.toml`) and a **`test`** job running `tools/run_tests.py` on windows-latest, macos-latest and ubuntu-latest (under `xvfb-run`); `build` has `needs: [lint, test]` and `fail-fast: false`. The Windows and Linux build jobs run `test_gpu_tuner` and `test_tuner_canvas` with the freshly built wheel (runners have a software adapter or no Vulkan, so that exercises the fallback to canvas for real). After PyInstaller each build job runs the frozen binary with **`--selftest`** against an isolated `JUSTATUNER_CONFIG_DIR`. The Windows build job then installs the Inno Setup installer silently, runs the installed copy's `--selftest`, checks the Start Menu shortcut, uninstalls silently, and asserts the user's `%APPDATA%\JustATuner` folder survived. The macOS build job runs **`--tour all`** twice (light, then dark via `defaults write` + the `osascript` appearance switch + `--appearance dark`) and uploads both as the `mac-tour` artifact with `continue-on-error`. Look at those pictures after a Mac-affecting change; they are the only eyes on the Mac. First run (2026-10-06): the canvas tuner lit A4 IN TUNE on real Mac Tk, the dark run took (Tuner Settings mean brightness 129 → 43, latency dialog 107 → 43), and the pictures found the blank Aqua swatches and the clipped drone status row (see the traps). The runner has a silent input device, so the "tuner-no-mic" stop shows a running tuner there; the no-mic error itself is gated in `test_tuner_canvas` pass 0. Blind spots no runner reaches: the mic permission prompt itself, Retina scaling, display scaling above 100 % on Windows, real audio devices, Gatekeeper's first launch.

## Config File Location

User settings live in `app_settings.json` at:

| Platform | Location |
|----------|----------|
| Windows | `%APPDATA%\JustATuner\` |
| macOS | `~/Library/Application Support/JustATuner/` |
| Linux | `$XDG_CONFIG_HOME/JustATuner/` (or `~/.config/JustATuner/`) |

Schema lives in `config.py`'s `DEFAULT_SETTINGS`. Anything read at runtime MUST exist in `DEFAULT_SETTINGS` — the merge in `load_settings` only preserves keys that already appear in the defaults, so runtime-only keys silently disappear on next launch.

Top-level keys: `tuner_settings` (dict), `exerciser_settings` (dict), `audio_input_device` (int or None — cached PortAudio index), `audio_input_device_name` (str or None — the real persisted choice, see Input device by name), `active_tab` (str — "tuner" or "exerciser").

## Per-Platform Constraints

- **Apple Silicon only on macOS** — `sounddevice`'s Intel wheel doesn't reliably bundle PortAudio. JustATuner is audio-only, so an Intel build with no audio isn't worth shipping. README points Intel Mac users at `brew install portaudio` + From-Source.
- **No code signing on any platform**. Windows uses SmartScreen "Run anyway" + UAC; macOS needs `xattr -cr` to clear the quarantine flag; Linux needs `chmod +x`. README documents all three.
- **macOS mic permission must be declared in the bundle — and the bundle must be re-signed after patching it.** `build.py`'s `_patch_macos_plist()` adds `NSMicrophoneUsageDescription` to the `.app` Info.plist post-build; without it macOS silently denies microphone access. v1.0.0 shipped without it (an extraction regression). But patching the plist after PyInstaller's ad-hoc signing breaks the signature seal, and TCC also silently denies (never prompts) when the signature doesn't validate — so v1.1.0/v1.1.1 had the key yet still never asked for the mic. `_resign_macos_app()` re-signs after the patch, and CI packages with symlink-preserving `ditto` (not `zip -r`) and runs `codesign --verify --deep --strict` on both the built app and the unzipped artifact. Users upgrading from a broken build may need `tccutil reset Microphone com.stohrer.justatuner` if macOS cached a denial.
- **GPU tuner renderer is built in CI** (v1.1.0+), **Windows and Linux only**. The Rust/wgpu `tuner_render` crate lives in `tuner_renderer/` (copied from SSC); maturin builds it on those runners and `build.py`'s `--hidden-import` capability check bundles it, with `tuner/view.py` falling back to the Tk canvas renderer when it's absent. **v1.0.0 shipped without it** — the extraction brought over the Python integration in `tuner/view.py` but not the crate or the build wiring, so end users got canvas-only while a stray local `tuner_render` install masked the gap in dev. Fixed in v1.1.0. Since 2026-10-06 the renderer asks for the adapter's real texture limits (not the 2048 px downlevel cap), clamps every configure, presents with Mailbox where offered (0.16 ms/frame vs 16.67 for Fifo), exposes `adapter_info()` / `present_mode()`, and the view treats a `Cpu` adapter as no GPU; every surface call is guarded against the pyo3 `PanicException` (a `BaseException`) and routed through `_tuner_gpu_fallback`. A local `python -m maturin build --release --manifest-path tuner_renderer/Cargo.toml` then `pip install --force-reinstall --no-deps tuner_renderer/target/wheels/tuner_render-*.whl` is how the dev box gets the current crate; the installed wheel is otherwise whatever was built last (SSC's and this repo's crates share the module name).
- **macOS is canvas-only — never load `tuner_render` on darwin.** Tk Aqua draws all widgets into a single NSView per toplevel, and `winfo_id()` returns an internal `MacDrawable` pointer ("the value has no meaning outside Tk" — Tk docs), not an NSView. `tuner_renderer/src/platform.rs` treats the handle as an NSView, so wgpu's Metal backend segfaults in `objc_msgSend` during surface creation — a native crash the Python `except` fallback in `tuner/view.py` can never catch. Three layers enforce this: `tuner/view.py` skips the `tuner_render` import on darwin, `build.py` skips the `--hidden-import` on darwin, and CI skips the Rust build on the macOS runner. The v1.1.0 macOS zip shipped with the renderer bundled and likely crashed at launch. Even a real NSView wouldn't be enough: a CAMetalLayer on the shared view would paint over the entire window, so a macOS GPU path would need a dedicated subview managed natively (plus Retina scale handling).
- **CoreAudio does not resample.** A stream opened at 44.1 kHz on a device that only does 16/24/48 kHz fails outright on macOS (Windows/PulseAudio silently convert). Never call `sd.InputStream`/`sd.OutputStream` directly — go through the `audio_utils` helpers and read the returned rate. Unverified on real hardware as of v1.1.3; the retry path is mock-tested.
- **Cmd-Q must be routed through `_on_close`.** On macOS, Cmd-Q and the app menu's Quit fire Tk's `::tk::mac::Quit`, which by default exits the process without running the `WM_DELETE_WINDOW` handler — settings would silently never save. `main.py` registers `root.createcommand("::tk::mac::Quit", self._on_close)` on darwin.

## Relationship to Stohrer Sax Shop Companion

JustATuner started as a "what if the SSC tuner was its own free app for musicians who aren't repair techs" question. The strobe tuner half is a direct extraction of `tuner_engine.py`, `audio_utils.py`, and `tuner_tab.py`, with `TunerTabMixin` refactored into a standalone `TunerView` class that takes `(parent, root, settings)` in its constructor instead of pulling them from `self`. Tuner bugfixes that land in SSC should be ported here when relevant; this app doesn't import from SSC at runtime — the files are duplicated, by design, so the two projects can evolve independently.

The JI Drone half was the original JustATone Python prototype (still in `C:\code\justatone` as legacy files alongside the now-current Rust/bevy garden visualizer). Brought over wholesale and adapted: `AudioEngine`, `intervals.py`, `pitch.py`, `widgets.py` are essentially unchanged from the prototype; `view.py` is rebuilt as an embeddable Frame.

The garden visualizer in this app is a fresh take on the garden vision from the JustATone Rust pivot — done in Tk + PIL instead of bevy + wgpu. Different stack, same spirit.
