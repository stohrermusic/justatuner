## JustATuner v0.9.0 — first public release

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis and a vintage Lissajous CRT for ear training against true ratios.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu when the optional extension is built; automatic fallback to canvas everywhere else
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color
- Vintage backlit VU meter showing the closest pitch class and cents off
- Warm tube-amp-style motor-pilot lamp that glows when audio is live

### Just Intonation Drone
- Drone synthesizer in any of 12 chromatic roots; voicings root / root+fifth / major triad / minor triad; sine or rich harmonic stack
- Big DRONE switch with OFF / ON positions
- Live just-intonation interval analysis with LOCKED indicator (±5¢) and cents readout
- Spectral notch on the mic input that knocks down direct drone bleed (room reflections still want headphones)
- Five visualizer modes:
  - **Lissajous** (default) — interference pattern between you and the drone
  - **Waveform** — classic horizontal oscilloscope
  - **Spectrum** — log-frequency FFT bars
  - **Waterfall** — 3D rolling spectrum, mountain-range style, with slow color cycle
  - **Warp** — Geiss-style feedback bloom, hypnotic backdrop for long sessions
- Instrument presets for pitch detection (sax family, voice, brass, strings, etc.)

### Installs
- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-0.9.0.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
- **macOS (Apple Silicon only, M1/M2/M3/M4)**: download the `.zip`, drag the .app into Applications, then run `xattr -cr /Applications/JustATuner.app` once in Terminal to clear the quarantine flag (the app isn't code-signed because Apple charges $100/year for that).
  - **No Intel Mac build**: `sounddevice` doesn't bundle PortAudio reliably on Intel macOS, and an audio app where the audio doesn't work isn't worth shipping. Intel Mac users can run from source after `brew install portaudio`.
- **Linux**: download the binary, `chmod +x`, run. Needs `sudo apt install libportaudio2` first (or your distro's equivalent).

Full installation instructions, including the one-time unblock steps for each platform, are in the [README](https://github.com/stohrermusic/justatuner#installation).

### Known limitations
- Tuner GPU acceleration requires the optional `tuner_render` Rust extension; not shipped in this release. Canvas mode runs fine at 60 fps on any modern laptop.
- Drone-cancellation notch on the mic helps with direct bleed but can't fully cancel speaker feedback through the room. Use headphones when the drone is on.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
