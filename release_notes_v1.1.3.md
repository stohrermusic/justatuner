## JustATuner v1.1.3

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis, six visualizer modes (including a Geiss-style waterfall and a branching audio-driven garden), and a sample-based drone you can record off your own horn.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### What's new since v1.1.2

Audio-input robustness, aimed mostly at macOS but applying everywhere:

- **Microphones that don't run at 44.1 kHz now work.** Both the tuner and the drone used to demand 44.1 kHz from the mic. Windows and Linux quietly resample, but macOS does not — a Bluetooth headset mic (AirPods and friends run at 16 or 24 kHz) or an audio interface set to 48 kHz in Audio MIDI Setup would refuse to open, leaving the tuner showing an audio error and the drone tab hearing nothing. The streams now open at the device's own rate when it won't do 44.1 kHz, and all the pitch math follows the real rate.
- **Tuner > Settings… opens again.** A helper the settings dialog relies on was dropped in the extraction from Stohrer Sax Shop Companion, so the dialog raised an error instead of opening in v1.1.1 and v1.1.2. Fixed.
- **Your input device is remembered by name, not by number.** The audio system renumbers devices whenever something is plugged in or unplugged (constantly, on a Mac with Bluetooth), so a saved device number could silently pick the wrong mic or fail outright. The saved choice is now matched by name at startup; if that device isn't connected, the app uses the system default instead of an error. The tuner and drone tabs now share the same remembered device.
- **A chosen mic that fails to open falls back to the system default** instead of leaving the tuner dead.
- **Drone tab shows mic status.** A MIC line in the status panel says "Listening (44.1 kHz)" or exactly why the microphone couldn't be opened. Previously that error was discarded, so a silent drone tab gave no clue.
- **Drone tab recovers a dead mic on its own.** If the input stream stops delivering audio (device unplugged, default device switched underneath the app, Bluetooth drop), it reopens automatically, and keeps retrying every few seconds if no mic is available at all. The tuner already did this; now both tabs do.
- **Audio problems are logged.** Device failures, rate fallbacks, and stream restarts go to `app.log` (Help > Open Log File) so a report from the field has something to work with.

This release has **not** been verified on Apple Silicon hardware yet; the changes are pure Python and can't crash the app the way the v1.1.0 renderer did, but the Bluetooth-mic and 48 kHz paths only exercise on a Mac. If you're a Mac user with AirPods, you're the test.

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu on Windows and Linux — 60–120 fps on capable machines, with automatic fallback to canvas when a machine can't initialize the GPU. macOS uses the canvas renderer.
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color — reachable via **Tuner > Settings...**
- Vintage backlit VU meter showing the closest pitch class and cents off
- Warm tube-amp-style motor-pilot lamp that glows when audio is live

### Just Intonation Drone
- Drone synthesizer in any of 12 chromatic roots; voicings root / root+fifth / major triad / minor triad; sine, rich harmonic stack, or **WAV sample** (load file or record)
- Samples persist between sessions, with Save Sample As… export
- Big DRONE switch with OFF / ON positions
- Live just-intonation interval analysis with LOCKED indicator (±5¢) and cents readout
- Spectral notch on the mic input that knocks down direct drone bleed (room reflections still want headphones)
- Six visualizer modes:
  - **Lissajous** (default) — interference pattern between you and the drone
  - **Waveform** — classic horizontal oscilloscope
  - **Spectrum** — log-frequency FFT bars
  - **Waterfall** — 3D rolling spectrum, mountain-range style, with slow color cycle
  - **Warp** — Geiss-style feedback bloom, hypnotic backdrop for long sessions
  - **Garden (beta)** — branching audio-driven plants with leaves and species-styled flowers
- Instrument presets for pitch detection (sax family, voice, brass, strings, etc.)

### Installs

- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-1.1.3.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
- **macOS (Apple Silicon only, M1/M2/M3/M4)**: download the `.zip`, drag the .app into Applications, then run `xattr -cr /Applications/JustATuner.app` once in Terminal to clear the quarantine flag (the app isn't code-signed because Apple charges $100/year for that). On first launch macOS will ask for **microphone access** — click **Allow**.
- **Linux**: download the binary, `chmod +x`, run. Needs `sudo apt install libportaudio2` first (or your distro's equivalent).

Full installation instructions, including the one-time unblock steps for each platform, are in the [README](https://github.com/stohrermusic/justatuner#installation).

### Upgrading from v1.1.1 or earlier (Mac users, read this)

Your settings carry over automatically. On first launch, macOS should ask for **microphone access** — click **Allow** and you're done. If it *doesn't* ask and the wheels still won't move, your Mac cached the old silent denial from a pre-v1.1.2 build; clear it with this one Terminal command, then relaunch:

```
tccutil reset Microphone com.stohrer.justatuner
```

Because the app isn't Apple-signed, macOS may ask for microphone access again after future updates — that's normal, just click Allow.

### Known limitations
- The strobe tuner on macOS is not GPU-accelerated — Tk on macOS doesn't expose a native view the GPU renderer can draw into, so Macs use the canvas renderer. Fully functional, just lower frame rates than the Windows/Linux GPU path.
- GPU strobe rendering (Windows/Linux) needs a working graphics stack — on Linux that means Vulkan or OpenGL drivers. Where it can't initialize, the tuner falls back to the canvas renderer.
- A Bluetooth headset mic works now but is a 16 kHz telephony-grade signal; the tuner's top octave is out of range at that rate and pitch detection is coarser. Any wired mic or the built-in one will do better.
- Devices plugged in after the app starts don't appear in the device lists until the next launch (the audio library snapshots devices at startup). The system default still follows the OS.
- Drone-cancellation notch on the mic helps with direct bleed but can't fully cancel speaker feedback through the room. Use headphones when the drone is on.
- WAV-sample drone resampling sounds clean within ~an octave of the source pitch; larger shifts start to sound aliased. Record near the middle of your intended drone range.
- Garden visualizer is marked beta; expect visual tuning to keep evolving.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
