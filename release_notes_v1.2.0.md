## JustATuner v1.2.0

A free cross-platform desktop tuner for musicians by [Matt Stohrer](https://www.StohrerMusic.com). Two tools in one window: a 12-wheel chromatic stroboscopic tuner for everyday tuning and intonation work, and a just-intonation drone with live interval analysis, chord progressions, six visualizer modes (including a Geiss-style waterfall and a branching audio-driven garden), and a sample-based drone you can record off your own horn.

> **First-install heads-up**: Windows shows a SmartScreen warning, macOS blocks the app as "unidentified developer," and Linux needs one extra package. None of it is broken — see [Installs](#installs) below for the one-time unblock step on your platform.

![Stroboscopic Tuner](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/tuner.png)

![Just Intonation Drone](https://raw.githubusercontent.com/stohrermusic/justatuner/main/img/drone.png)

### What's new since v1.1.3

The drone got a lot smarter about speakers, learned to play chord changes, and the whole app now has a real test suite behind it.

- **Chord progressions (new).** Drone > Progression… lets the drone move through a chord progression on its own, so you practise intonation while the harmony changes under you. Pick a preset (I–IV–V–I, ii–V–I, a twelve-bar blues, the cycle of fifths…) or type your own as `C | F | G7:2 | Am`, or build it with the chord pickers. Run it in bars at a tempo, in seconds per chord, or by hand: a key you choose (the space bar by default) moves to the next chord whenever you're ready. The PROG row under the DRONE switch starts, stops and skips, with a count-in and the current and next chord shown in your written key. Save your progressions under a name.
- **Eleven chords instead of four (new).** Root, root + fifth, major and minor triads, major 7th, dominant 7th (the harmonic 7:4), minor 7th, sus4, sus2, diminished and augmented, all as just ratios. Chord changes no longer click.
- **Speakers or headphones (new).** Exerciser Options > Monitoring. With **Speakers**, the drone leaks into the mic, so whenever the drone starts or changes chord the app listens to the room for a few seconds (the DRONE status says so; stay quiet) and then cancels the drone from what the mic hears. It can do that because it knows exactly what it is playing: each partial of the drone is subtracted at the level and phase it arrives with. A chord the app has heard once in a session needs no second listen, so a progression calibrates each chord once and then plays straight through. With **Headphones** there is nothing to cancel, so there is no listen at all. The old spectral notch, which let the drone itself read as a unison through speakers, survives only for WAV-sample drones (use headphones with those).
- **The tuner reads low notes right.** The spectral peak estimator was the wrong shape for the Hann window the tuner uses: an exactly in-tune note read up to 15 cents off at the bottom of the range (B1), 8 cents at A2, so the strobe turned on a note that was dead on. The estimator now matches the window, is within a fraction of a cent across A1–A6, and no longer flicks on a note that is decaying.
- **GPU strobe on scaled displays.** On a laptop at 150 % or more the GPU renderer could hit a 2048-pixel texture cap and crash the tuner's window; it now asks the graphics driver for its real limits, presents without blocking the UI on vertical sync (0.16 ms per frame instead of 16.7), and if the GPU fails in any way the tuner drops to the canvas renderer with a notice instead of dying. A software-only graphics adapter is treated as no GPU.
- **Small things that were wrong.** The audio-error message on the tuner no longer vanishes after a resize; the Tuner Settings input-device box no longer opens blank; dialogs open over the app instead of the screen corner; the colour swatches in Tuner Settings show their colours on a Mac; a settings file with damaged bytes no longer stops the app launching; WAV samples saved as 32-bit integer with leading silence are read correctly, and real floating-point WAVs open at all; sample loops are seamless (the old crossfade could swell by 3 dB once per loop and push a recording past full scale); an A1 sample is detected instead of falling back to 440 Hz.
- **Behind the scenes.** Twelve test suites (about 440 checks) run on Windows, macOS and Linux for every change; each shipped binary runs a self-check in the build; the Windows installer is installed, run and uninstalled on a clean machine before it is published; and the macOS build is screenshot in light and dark mode so the Mac UI gets looked at even though nobody on the project owns a Mac.

### Stroboscopic Tuner
- 12 chromatic wheels, each with seven concentric rings (one per octave) lit by real spectral data so the played octave reads sharp and bright
- GPU-accelerated rendering via Rust/wgpu on Windows and Linux — 60–120 fps on capable machines, with automatic fallback to canvas when a machine can't initialize the GPU. macOS uses the canvas renderer.
- Configurable reference pitch (A=440, 441, 442, …), transposition (Concert / B♭ / E♭ / F), per-wheel and per-ring cents biases, frame rate, and stripe color — reachable via **Tuner > Settings...**
- Vintage backlit VU meter showing the closest pitch class and cents off
- Warm tube-amp-style motor-pilot lamp that glows when audio is live
- MIC lamp: green for good input, amber with a note for a Bluetooth-grade or silent input, dark for none

### Just Intonation Drone
- Drone synthesizer in any of 12 chromatic roots; eleven just-ratio voicings; sine, rich harmonic stack, or **WAV sample** (load file or record)
- Chord progressions: presets or your own, bars at a tempo / seconds / manual on a key, count-in, saved by name
- Samples persist between sessions, with Save Sample As… export
- Big DRONE switch with OFF / ON positions; the PROG row for progressions
- Live just-intonation interval analysis with LOCKED indicator (±5¢) and cents readout
- Speakers / Headphones monitoring, with room-listening drone cancellation for speakers
- Six visualizer modes:
  - **Lissajous** (default) — interference pattern between you and the drone
  - **Waveform** — classic horizontal oscilloscope
  - **Spectrum** — log-frequency FFT bars
  - **Waterfall** — 3D rolling spectrum, mountain-range style, with slow color cycle
  - **Warp** — Geiss-style feedback bloom, hypnotic backdrop for long sessions
  - **Garden (beta)** — branching audio-driven plants with leaves and species-styled flowers
- Instrument presets for pitch detection (sax family, voice, brass, strings, etc.)
- Help > Test Audio Latency… measures the real round trip from speakers to mic

### Installs

- **Windows**: Inno Setup installer (`JustATuner-Windows-Setup-1.2.0.exe`). SmartScreen will warn on first launch — click "More info" → "Run anyway".
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
- A Bluetooth headset mic works, but it is a telephony channel: speech codec, noise gating, and 100–300 ms of lag. Pitch range is fine (16 kHz still covers all seven tuner octaves); responsiveness and tone are not. The MIC readouts turn amber to say so. Any wired mic or the built-in one will do better.
- Devices plugged in after the app starts don't appear in the device lists until the next launch (the audio library snapshots devices at startup). The system default still follows the OS.
- With speakers, the drone cancellation needs you quiet for its few-second listen whenever the drone starts or changes to a chord it hasn't heard yet; play during the listen and it will learn you as part of the room. If a reading looks wrong after a chord change, stop and start the drone to listen again. WAV-sample drones aren't cancelled this way — use headphones with them.
- WAV-sample drone resampling sounds clean within ~an octave of the source pitch; larger shifts start to sound aliased. Record near the middle of your intended drone range.
- Progressions can be typed or picked, not yet played in from a MIDI keyboard; that's on the list.
- Garden visualizer is marked beta; expect visual tuning to keep evolving.
- macOS is Apple Silicon only (see above).

### Questions / feedback
stohrermusic@gmail.com
