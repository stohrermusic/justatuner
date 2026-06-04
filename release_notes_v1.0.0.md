## JustATuner v1.0.0

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis, six visualizer modes (including a Geiss-style waterfall and a branching audio-driven garden), and a sample-based drone you can record off your own horn.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### What's new since v0.9.0

- **WAV sample drone** — under Drone > Sample, load a sustained-tone WAV file from disk or record one off your microphone. YIN auto-detects the sample's fundamental pitch; attack and release are trimmed; an equal-power crossfade at the loop boundary makes the sample loop cleanly. The voicing system layers pitch-shifted copies of the sample, so one recorded "ahhh" becomes a layered choral drone when Voicing is set to Major Triad. Supports 16/24/32-bit PCM and 32-bit float WAVs, mono or stereo (stereo downmixes).
- **Garden visualizer (beta)** — a sixth visualizer mode in the JI Drone tab. Plants grow on a persistent canvas: each branch is a print head that stamps the current FFT cross-section perpendicular to its growth direction. Amplitude peaks trigger L-system-style branch splits; spectral centroid drives a slow lateral drift (warm playing leans one way, bright the other); volume modulates growth speed. Sub-branches drop teardrop leaves on alternating sides; branches that reach natural maturity bloom flowers at their tips. Each plant rolls its own species-style at spawn time — petal count, shape (round / teardrop / ray / spade), center size, and color relationship are all randomized per plant, so the garden reads as a mix of species rather than identical blooms. Yellow-green fireflies drift above the garden, spawning faster when you sustain notes — they're a transient overlay (no trails into the plant material). When one plant matures a new one seeds beside it; once the canvas fills, the garden treadmills along to make room.
- **Warmer motor pilot lamp** on the tuner — five-layer concentric glow with a specular hotspot, replacing the flat orange dot. Reads like a vintage tube-amp pilot light.
- **Responsive tuner control bar** — sliders, motor pilot, and VU meter now live in three equal-weight columns that scale uniformly with window width.
- **Polished framebuffer visualizers** — Garden and Warp both apply a circular alpha mask so their square framebuffers stop poking past the CRT bezel ring.

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu when the optional extension is built; automatic fallback to canvas everywhere else
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color
- Vintage backlit VU meter showing the closest pitch class and cents off
- Warm tube-amp-style motor-pilot lamp that glows when audio is live

### Just Intonation Drone
- Drone synthesizer in any of 12 chromatic roots; voicings root / root+fifth / major triad / minor triad; sine, rich harmonic stack, or **WAV sample** (load file or record)
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

- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-1.0.0.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
- **macOS (Apple Silicon only, M1/M2/M3/M4)**: download the `.zip`, drag the .app into Applications, then run `xattr -cr /Applications/JustATuner.app` once in Terminal to clear the quarantine flag (the app isn't code-signed because Apple charges $100/year for that).
  - **No Intel Mac build**: `sounddevice` doesn't bundle PortAudio reliably on Intel macOS, and an audio app where the audio doesn't work isn't worth shipping. Intel Mac users can run from source after `brew install portaudio`.
- **Linux**: download the binary, `chmod +x`, run. Needs `sudo apt install libportaudio2` first (or your distro's equivalent).

Full installation instructions, including the one-time unblock steps for each platform, are in the [README](https://github.com/stohrermusic/justatuner#installation).

### Known limitations
- Tuner GPU acceleration requires the optional `tuner_render` Rust extension; not shipped in this release. Canvas mode runs fine at 60 fps on any modern laptop.
- Drone-cancellation notch on the mic helps with direct bleed but can't fully cancel speaker feedback through the room. Use headphones when the drone is on.
- WAV-sample drone uses linear-interpolation resampling — sounds clean within ~an octave of the source pitch; larger shifts start to sound aliased. Record near the middle of your intended drone range.
- Garden visualizer is marked beta; expect visual tuning to keep evolving.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
