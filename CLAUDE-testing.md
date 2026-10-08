# JustATuner — testing

*The test suites, the frozen-build probe, the screenshot tour, and the smoke-test patterns. Companion to CLAUDE.md; same rules, same voice. Edited in the same commit as the code it describes.*

## Tests

```bash
python tools/run_tests.py              # every tools/test_*.py, PASS/FAIL per suite
python tools/run_tests.py engine       # suites whose name contains a word
python tools/run_tests.py --skip gpu --allow-missing sounddevice
python tools/test_tuner_engine.py      # one suite directly
python main.py --selftest              # SELFTEST OK / SELFTEST FAIL, exit 0/1
python main.py --tour all --shots DIR [--appearance dark]   # screenshot every stop
```

Each `tools/test_*.py` is a standalone script, not pytest; the runner executes each in its own interpreter from the repo root (same as SSC). Twelve suites as of 2026-10-07, about 95 s locally, about 440 checks. `tools/measure_bleed.py` is a measuring tool, not a test: it plays the drone through the real speakers and reports what the real mic hears. Every engine built in a test stubs its stream openers or uses `synthetic_hz`; see the traps.

- `test_tuner_engine` — pure math, no display: the Hann estimator on a pure lobe (<0.01 bin) and on a decaying note, in-tune A1–A6 sweeps (pure sine <0.5 c; with a −6 dB H2 <1.0 c, C2–A6 <0.5 c), off-pitch A2–A5 within 0.15 c, the strobe standing still on an in-tune note, B5 26 c flat, numpy surviving a blocked sounddevice (child interpreter), and the synthetic source through `analyze()`.
- `test_audio_utils` — the ring buffer, `synthetic_tone` phase continuity, the estimator's climb and clamp, the sample-rate fallback for input and output on a fake sounddevice, `TunerEngine` on a 16 kHz device, the saved-device fallback, the stale-stream restart, `silent_seconds`.
- `test_exerciser_engine` — YIN over C2–C7 at 44.1 kHz and D2–C6 at 16 kHz, the JI interval math, note naming, transposition, presets and voicings, `get_pitch` on the synthetic source, headphones mode untouched, the sample-drone notch documented.
- `test_drone_cancel` — the speakers-mode cancellation on a simulated room (delay, echo, noise, clock drift): the drone alone reads no pitch (53 dB of the fundamental removed), just intervals over the bleed within 0.02 c, a locked unison held 30 s is not learned away, 50 ppm drift still cancelled after 60 s, headphones mode exact, a note change re-listens, the room table (back to a known chord with 20 ppm drift and no new listen: 59.8 dB removed, ppm learned within 0.1), the click-free chord change, the sample drone keeps the notch.
- `test_progression` — notation round trips and rejections, timing in all three modes, presets, save/load, and the player on a fake clock and a fake engine: count-in, step changes at 2/4/6/8 s at 120 bpm, looping, next(), the calibration sequence and its skip, manual mode.
- `test_sample_pipeline` — the WAV reader (16/24/32-bit PCM, float32/float64, stereo), sample install (trim, pitch, period-aligned crossfade, seam, level), pitched playback, synth output, recording, save and clear.
- `test_config` — settings load/merge/corruption/round trip, device resolution by name, prefix and legacy index, the device filter, logging.
- `test_audio_latency` — the loopback measurement on a mocked device: delays, noise, echo cancellation, disagreeing chirps, rate fallback.
- `test_gpu_tuner` — the `tuner_render` API, the renderer.rs / view.py source contract, a 3500×1500 surface, `adapter_info` / `present_mode`, 60 frames timed, and the 30-failure fallback on the real app. Skips the wheel-dependent parts when the wheel is not built (set `JUSTATUNER_REQUIRE_GPU=1` on a machine that built it to make a broken wheel fail loudly) and the construction cases on a runner with no GPU surface.
- `test_tuner_canvas` — the real tuner tab end to end: pass 0 no mic (error text drawn and surviving a rebuild, MIC lamp dark), pass 1 canvas mode on the synthetic tone (12 wheels, A brightest, readout A / IN TUNE, lamp green, 0 c through the live path), pass 2 the GPU build (live renderer with zero failures, or the designed fallback with the CPU-mode notice).
- `test_drone_tab` — the real drone tab end to end on a just major third above its root: Major 3rd, 5:4, LOCKED, "Playing: E3", the ET-difference line, Bb transposition, every visualizer mode drawing without a Tk exception, the "Phase Wheel" mode migration, a progression in seconds mode whose interval readings follow the moving root (Major 3rd → Major 7th → Major 6th → Major 3rd), manual mode on the space key (and not from a text field), the Next button, drone-off stops it, tab switch, save.
- `test_tour` — `run_tour` with screenshots off as a gate on every platform (14 stops, no error), Tuner Settings opening with "System Default", the latency dialog, the progression editor (preset pick, bad-chord status line, the picker, Save, Use, Delete).

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
