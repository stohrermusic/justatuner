## JustATuner v1.1.1

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis, six visualizer modes (including a Geiss-style waterfall and a branching audio-driven garden), and a sample-based drone you can record off your own horn.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### What's new since v1.1.0

- **macOS launch crash fixed.** v1.1.0's macOS app could crash the moment it opened. The GPU strobe renderer introduced in v1.1.0 tried to attach to a native window handle that doesn't exist on macOS the way it does on Windows and Linux, and the app died before its renderer fallback could kick in. The strobe tuner on macOS now always uses the canvas renderer — fully functional, smooth at canvas frame rates. (GPU acceleration remains on Windows and Linux, where it works as advertised.) **If v1.1.0 wouldn't open on your Mac, this release is the fix.**
- **macOS: Cmd-Q now saves your settings.** Quitting with Cmd-Q (or the app menu's Quit) used to skip the settings save, so tuner colors, drone setup, and your last sample were forgotten unless you closed via the window's red button. Both quit paths now save.
- **Tuner Settings menu.** The tuner's settings dialog — stripe and faceplate color, brightness, octave boost, input-device picker, FPS overlay — existed but nothing opened it. It now lives at **Tuner > Settings...** while the tuner tab is active.
- **Cleaner drone sample pitch-shifting.** The WAV-sample drone now uses cubic (Catmull-Rom) interpolation instead of linear, for a cleaner sound when the drone pitch is shifted away from the recorded note.
- **Error logging.** The app keeps a rotating log file now, with **Help > Open Log File** to find it — so if something does go wrong, it's traceable instead of vanishing silently.
- **Audio teardown robustness.** Switching tabs or quitting no longer trips over an input device that disappeared mid-session (e.g. a Bluetooth headset disconnecting).

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu on Windows and Linux — 60–120 fps on capable machines, with automatic fallback to canvas when a machine can't initialize the GPU. macOS uses the canvas renderer.
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color — now reachable via **Tuner > Settings...**
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

- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-1.1.1.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
- **macOS (Apple Silicon only, M1/M2/M3/M4)**: download the `.zip`, drag the .app into Applications, then run `xattr -cr /Applications/JustATuner.app` once in Terminal to clear the quarantine flag (the app isn't code-signed because Apple charges $100/year for that). On first launch macOS will ask for **microphone access** — click **Allow**.
- **Linux**: download the binary, `chmod +x`, run. Needs `sudo apt install libportaudio2` first (or your distro's equivalent).

Full installation instructions, including the one-time unblock steps for each platform, are in the [README](https://github.com/stohrermusic/justatuner#installation).

### Upgrading from v1.1.0 or v1.0.0
Your settings carry over automatically. Mac users: v1.1.0 could crash at launch — v1.1.1 fixes it. If you're coming straight from v1.0.0, you also get the microphone-permission fix from v1.1.0: just click **Allow** when prompted.

### Known limitations
- The strobe tuner on macOS is not GPU-accelerated — Tk on macOS doesn't expose a native view the GPU renderer can draw into, so Macs use the canvas renderer. Fully functional, just lower frame rates than the Windows/Linux GPU path.
- GPU strobe rendering (Windows/Linux) needs a working graphics stack — on Linux that means Vulkan or OpenGL drivers. Where it can't initialize, the tuner falls back to the canvas renderer.
- Drone-cancellation notch on the mic helps with direct bleed but can't fully cancel speaker feedback through the room. Use headphones when the drone is on.
- WAV-sample drone resampling sounds clean within ~an octave of the source pitch; larger shifts start to sound aliased. Record near the middle of your intended drone range.
- Garden visualizer is marked beta; expect visual tuning to keep evolving.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
