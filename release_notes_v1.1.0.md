## JustATuner v1.1.0

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis, six visualizer modes (including a Geiss-style waterfall and a branching audio-driven garden), and a sample-based drone you can record off your own horn.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### What's new since v1.0.0

- **GPU-accelerated strobe tuner — now actually shipping.** The Rust/wgpu renderer that powers the strobe wheels in Stohrer Sax Shop Companion is now built into *every* JustATuner release, on Windows, macOS, and Linux. Wheels run at 60–120 fps with buttery-smooth strobe motion. v1.0.0 quietly shipped CPU-canvas-only — the GPU renderer was wired into the app but the build never included it — so this is the upgrade most people will *feel* immediately. Machines that can't initialize a GPU fall back to the canvas renderer automatically, exactly as before.
- **macOS microphone fix.** v1.0.0's macOS app didn't declare microphone usage in its bundle, so macOS silently denied mic access on a fresh install — the tuner wheels wouldn't move and the drone analyzer saw no input. Fixed: the app now requests microphone permission properly on first launch. Just click **Allow**.
- **Drone samples persist across launches.** The last WAV you loaded — or recorded off your mic — is now remembered and restored the next time you open the app. Recordings are saved automatically, and a new **Drone > Sample > Save Sample As…** lets you export any loaded or recorded sample to a WAV file of your own.

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu — 60–120 fps on capable machines, bundled in every release, with automatic fallback to canvas when a machine can't initialize the GPU
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color
- Vintage backlit VU meter showing the closest pitch class and cents off
- Warm tube-amp-style motor-pilot lamp that glows when audio is live

### Just Intonation Drone
- Drone synthesizer in any of 12 chromatic roots; voicings root / root+fifth / major triad / minor triad; sine, rich harmonic stack, or **WAV sample** (load file or record)
- **Samples now persist** between sessions, with Save Sample As… export
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

- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-1.1.0.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
- **macOS (Apple Silicon only, M1/M2/M3/M4)**: download the `.zip`, drag the .app into Applications, then run `xattr -cr /Applications/JustATuner.app` once in Terminal to clear the quarantine flag (the app isn't code-signed because Apple charges $100/year for that). On first launch macOS will ask for **microphone access** — click **Allow**.
- **Linux**: download the binary, `chmod +x`, run. Needs `sudo apt install libportaudio2` first (or your distro's equivalent).

Full installation instructions, including the one-time unblock steps for each platform, are in the [README](https://github.com/stohrermusic/justatuner#installation).

### Upgrading from v1.0.0
Your settings carry over automatically. macOS users who couldn't get the mic working in v1.0.0: that's the bug fixed here — just install v1.1.0 and click **Allow** when prompted.

### Known limitations
- GPU strobe rendering needs a working graphics stack — on Linux that means Vulkan or OpenGL drivers. Where it can't initialize, the tuner falls back to the canvas renderer (still a smooth 60 fps on any modern laptop).
- Drone-cancellation notch on the mic helps with direct bleed but can't fully cancel speaker feedback through the room. Use headphones when the drone is on.
- WAV-sample drone uses linear-interpolation resampling — sounds clean within ~an octave of the source pitch; larger shifts start to sound aliased. Record near the middle of your intended drone range.
- Garden visualizer is marked beta; expect visual tuning to keep evolving.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
