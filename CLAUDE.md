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

- **2026-10-07 — A `Progression` built from a preset's `steps` shared the preset's `Step` objects**, so editing a length on the copy edited the preset for the rest of the process (the tour did it; the editor then showed "C:0.6 | F:0.6…" as the I–IV–V–I preset). `Progression.__init__` copies its steps. Gated in `test_tour` (the editor shows the preset's own chords after the tour's progression ran).
- **2026-10-07 — The projection's phase is demodulated; do not add an absolute-phase term to it.** `c = Σ x·w·e^{−iωt}` is constant in time for a steady partial, so the room table stores `angle(c) + 2πf·epoch/sr` and derives `psi − 2πf·epoch/sr`. My first formulas added `2πf·(t − t_ref)`, which with that run's timing was exactly 771.5 cycles: odd partials 180° off, even ones exact, which looked like a half-period shift until measured partial by partial. Gated in `test_drone_cancel` ("back to C from the room").

- **2026-10-07 — An `AudioEngine` with `running = True` and no stubbed opener opens the REAL microphone from `get_pitch()`'s health check**, and a suite that builds a dozen engines that way leaves a dozen never-closed PortAudio streams, which segfaulted the interpreter (exit 139) on garbage collection. Every engine built in a test stubs `_start_input_stream` / `_start_output_stream` (or uses `synthetic_hz`). The "input stream open" log line during a pure-math suite is the tell.
- **2026-10-07 — Drone-bleed cancellation needs the mic/speaker clock difference, and phases cannot be saved across sessions.** Measured here: the Intel mic and Realtek speakers differ by 2.6 ppm (0.12 deg/s drift at the fundamental, 0.74 at the sixth partial); a device that does both (Stereo Mix, a Scarlett) is 0 ppm. The two streams start at unrelated moments, so each partial's phase at the mic is new every time the streams open (every tab switch): a "saved room" could keep amplitudes only and would still need the listen, so there is no saved room. The engine listens for 3 s after a 0.4 s settle, fits gain and drift per partial, predicts forward, and tracks only while no pitch is detected (a held unison is never learned away). Gated by `test_drone_cancel` on a simulated room with delay, echo, noise and 50 ppm drift; verified on real streams through the loopback (0 of 96 frames read the drone as a note).

- **2026-10-06 — The one-neighbour Hann form d = (2a−1)/(a+1) is exact on a steady lobe but biased on a lobe broadened evenly on both sides**, which is what a note decaying during the frame produces: a 20 ms decay on bin 40 read +0.105 bin (4.5 c at A4, 18 c at A2), so a plucked or struck note flicked the strobe. The two-neighbour form d = 2(R−L)/(L+2P+R) reduces to d on a clean lobe and reads the decaying note within 0.002 bin. Found by `test_audio_utils`; gated by the decaying-note check in `test_tuner_engine`. SSC's `hann_peak_freq` still has the one-neighbour form.
- **2026-10-06 — The stdlib `wave` module refuses IEEE-float WAVs ("unknown format: 3"), so a "probe the first 1024 samples as float32" guess in the reader only ever fired on int32 files.** Any int32 file that starts quietly (leading silence) decoded its tone as float bit patterns: NaN and 1e38 into the drone, which `np.clip` passes through. 4-byte PCM is int32; real float files go through `_read_float_wav`. Gated in `test_sample_pipeline`.
- **2026-10-06 — A loop crossfade must be a whole number of periods, and so must the sample; equal-power curves are wrong for correlated signals.** `4 * int(sr/f)` truncated 200.45 to 200 samples (seam 2.8× a normal step), and cos/sin equal-power curves on a steady tone's in-phase head and tail swelled or dipped the level by +3/−4 dB once per loop depending on the sample length, which also pushed a 0.95-normalised recording past full scale. Period-aligned trim plus a period-aligned linear fade: seam 0.026 vs p99 step 0.031, level within ±1.5 dB. Gated in `test_sample_pipeline`.
- **2026-10-06 — YIN's `tau_max = int(sr / fmin)` stops two lags short of fmin's own period**, so a tone at exactly fmin is undetectable: an A1 (55 Hz) sample fell back to 440 and played three octaves off; C2 was missed at a 16 kHz input rate. Now `ceil(sr/fmin) + 2`. Gated in `test_sample_pipeline` and `test_exerciser_engine`.
- **2026-10-06 — `UnicodeDecodeError` is a `ValueError`, not an `OSError` or `JSONDecodeError`**, and it is raised inside `fp.read()` before the JSON parser. `load_settings` caught only the latter two, so a settings file with bytes that aren't UTF-8 stopped the app launching (settings load on the first line of `JustATunerApp.__init__`). Catch `ValueError`. Gated in `test_config`.
- **2026-10-06 — A spectral notch (±4 Hz round every partial, rectangular window) cannot hide the drone itself**: with speakers the drone read as a played unison at confidence 0.97 through its own notch's leakage, a just third over the bleeding drone read −12 c and a fifth −5.5 c; with headphones the notch biased a unison by about +1 c. Wider and Hann-windowed notches were measured and rejected (30–80 c unison bias); no notch loses the third under bleed entirely. Replaced on 2026-10-07 by the per-partial subtraction above for sine/rich drones (the notch survives only for WAV-sample drones). Also: measure with phase-continuous signals — pushing identical 4096-sample blocks puts a phase jump mid-buffer and produced a false +10 c "bias" first.

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

The suites, the rules they follow, `--selftest` and `--tour`, and the smoke-test patterns are in **CLAUDE-testing.md**. Every engine built in a test stubs its stream openers or uses `synthetic_hz`; see the traps.

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
  progression.py        → Step / Progression, the chord notation, PRESETS,
                          progressions.json, ProgressionPlayer (no tkinter)
  progression_ui.py     → ProgressionDialog (Drone > Progression...)
  view.py               → ExerciserView (drone tab UI), RecordSampleDialog,
                          all six visualizer mode draw methods, the
                          progression transport (_prog_*)

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

**Tab-specific menus**: each tab rebuilds the menubar when it becomes active. The exerciser contributes the Drone menu (sound, voicing, sample, the progression entries) and Exerciser Options (input device, Monitoring, visualizer); the tuner contributes a **Tuner** menu whose **Settings…** entry opens `_tuner_open_settings` (stripe/faceplate color, ring + overall brightness, octave boost, input-device picker, on-screen FPS toggle). Some tuner controls are also inline (sensitivity, reference pitch, transposition, waveform). The Tuner menu's wiring was missing until v1.1.x — the dialog existed but nothing opened it (an extraction gap) — and once wired, the dialog raised ImportError until v1.1.3 because neither `config.get_input_devices` nor `ui_dialogs.add_tooltip` (both imported inside `_tuner_open_settings`) had been extracted. Any smoke test of the tuner should actually open Tuner > Settings… — the imports are lazy, so `import tuner.view` succeeding proves nothing.

**Settings persistence**: `config.load_settings()` does a two-level deep merge with `DEFAULT_SETTINGS` so old config files survive new keys being added. Save happens on app close in `JustATunerApp._on_close` via both views' `save_settings()` methods.

**Input device by name**: the persisted mic choice is `audio_input_device_name`; `audio_input_device` (the PortAudio index) is only a cache. PortAudio renumbers devices whenever USB/Bluetooth devices come and go, so both views call `config.resolve_input_device(settings)` at start (name match → prefix match → migrate a legacy index → system default) and `config.remember_input_device(settings, idx)` when the user picks one. Both tabs share the one saved device.

**Error logging**: `config.setup_logging()` writes a rotating `app.log` (500KB, 1 backup) to the config dir. `main.py` wires both `sys.excepthook` and Tk's `report_callback_exception` to `_handle_exception`, which logs the full traceback and shows a dialog pointing at **Help > Open Log File**. The shipped app is `--windowed`/`--noconsole`, so `print()` goes nowhere — use `logging` for anything diagnostic (the root logger is at WARNING, so log audio-device trouble at WARNING). Native crashes (e.g. in a GPU driver) bypass all of this; those need the OS crash report.

**MIC lamp**: both tabs show a `StatusLamp` for the input stream, separate from the motor pilot (which only means "tuner running"). Tuner: to the right of the VU meter in the control bar's right column (`vu_frame` holds `vu_inner` = meter + readout, then `mic_col`; keep it beside the meter, not below — below made the whole control panel taller). Drone: in the status panel under DRONE. States, from `TunerView._tuner_update_mic_label` / `ExerciserView._update_mic_status`: **green** good input; **amber** + "no signal" when `engine.silent_seconds()` > `SILENT_WARN_S` (3 s of exact digital zeros while the stream is alive — the denied-macOS-permission / muted-input signature; a quiet room still has a noise floor); **amber** + "low quality input" when the rate is under `LOW_QUALITY_INPUT_HZ` (32 kHz, i.e. a Bluetooth hands-free link); **dark** when there is no mic input (stream closed or dead; the drone tab also prints the open error as text since it has nowhere else to say why). Texts are deliberately terse. Both updaters run on their existing frame timers and only touch widgets when the state changes.

**Latency test**: `audio_latency.measure()` opens one full-duplex `sd.playrec` stream (shared clock for both directions, output device chosen on the *same host API* as the input or Windows raises "Illegal combination of I/O devices"), plays three Hann-windowed 500–3000 Hz chirps 0.7 s apart, cross-correlates each search window against the chirp, and reports the median lag when at least two readings agree within 15 ms. The driver's `stream.latency` is reported alongside as "buffering only". `main.py._open_latency_test` stops both engines for the run and restarts the active one via `_on_tab_changed` when the worker thread finishes, even if the dialog was closed. Laptop mics with driver-level echo cancellation (Intel Smart Sound on the dev machine) swallow the chirps; the failure message says so. Validated against the Realtek Stereo Mix loopback (90 ms, three agreeing readings) and a synthetic delayed-echo mock.

**Sample rate is negotiated, never assumed**: both engines *prefer* 44.1 kHz but open through `audio_utils.open_input_stream()`/`open_output_stream()`, which retry at the device's `default_samplerate` when it refuses. Windows and PulseAudio resample transparently so the retry never fires there; CoreAudio does not, and a Bluetooth HFP mic (16/24 kHz) or an interface pinned to 48 kHz raises "Invalid sample rate". `TunerEngine.sample_rate`, `AudioEngine.in_sr` (mic) and `AudioEngine.sr` (drone output) hold the live rates and every bit of frequency math reads them — the `SAMPLE_RATE` constants are only the preference.

## Window Behavior

App opens **maximized** on every platform: `state('zoomed')` on Windows, `attributes('-zoomed', True)` on Linux/X11, screen-sized geometry fallback on macOS (Aqua has no programmatic maximize). The fallback geometry is the screen size + position (0, 0); the user can drag/resize from there.

## Tab-Specific Menu

`main.py`'s `_rebuild_menubar(is_tuner)` builds a fresh menubar on every tab change. Both views expose `populate_menu(menubar)` to contribute their tab's menus — Tuner ▸ Settings… for the tuner; Drone (Sound, Voicing, Sample, Progression…, Start / Stop Progression, Next Chord) and Exerciser Options (Input, Monitoring, Visualizer, Show ET Difference) for the exerciser.

## Branching Strategy

- **`main`**: Stable release branch. Tagged versions live here. Merges from `beta` when features are tested and ready.
- **`beta`**: Active development branch. New features land here first. CI builds run on both branches so beta pushes get the same Win/macOS/Linux validation main does.
- Same pattern as Stohrer Sax Shop Companion.

## Versioning

`APP_VERSION` in `config.py` is the manual source of truth — bump it when preparing a release. Also update `installer.iss`'s build-comment example and create a matching `release_notes_vX.Y.Z.md` file. The `AppId` GUID in `installer.iss` is stable across releases — **do not change** it or Windows will install upgrades in parallel instead of replacing.

Release notes file format mirrors what landed for v0.9.0 and v1.0.0: a "What's new since vX.Y.Z" section at the top (when applicable), then the standard feature lists, then Installs and Known limitations sections. Screenshots embed via `https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/{tuner,drone}.png` URLs.

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

## Companion files

The detail lives beside this file, split by subject so each stays short. Edit the companion in the same commit as the code it describes; the traps ledger above stays here.

- **CLAUDE-tuner.md** — the strobe tuner engine (FFT, the Hann estimator, phase tracking, stream health, the synthetic source)
- **CLAUDE-drone.md** — the drone engine (synth, samples, recording, drone-bleed cancellation, the room table, progressions), the visualizer modes, the garden
- **CLAUDE-testing.md** — the twelve suites and their rules, `--selftest`, `--tour`, smoke-test patterns
- **CLAUDE-build.md** — PyInstaller and macOS signing, the release process, CI, the config folder

@CLAUDE-tuner.md
@CLAUDE-drone.md
@CLAUDE-testing.md
@CLAUDE-build.md
