# JustATuner

A free strobe tuner and just-intonation exerciser for musicians.

Two tabs in one Tk app:

- **Strobe Tuner** — 12-wheel chromatic stroboscopic tuner with optional
  GPU rendering. Originally built for [Stohrer Sax Shop Companion][ssc]
  for saxophone repair work; spun out here standalone for everyone else.
- **JI Exerciser** — drone playback in any voicing (root / fifth / major /
  minor triad), live pitch detection, just-intonation interval analysis,
  and a vintage round Lissajous CRT display. The original [JustATone][jat]
  Python prototype, preserved here after that project pivoted to a
  Rust/bevy generative-art garden.

## Running from source

```bash
pip install -r requirements.txt
python main.py
```

Python 3.11+ recommended.

The strobe tuner falls back to a pure-Tk canvas renderer if the optional
[`tuner_render`][gpu] Rust extension isn't installed. Canvas mode runs
fine on any laptop; the GPU mode is what to install if you want 90–120 fps.

## Audio

Both tabs use [sounddevice] for mic input. They share one input device,
selected per-tab (Options menus inside each view).

Only the *active* tab's audio engine is running at any time — switching
tabs stops one and starts the other, so the OS never sees two opens on
your mic.

## Settings storage

`app_settings.json` lives in:

- Windows: `%APPDATA%\JustATuner\`
- macOS: `~/Library/Application Support/JustATuner/`
- Linux: `$XDG_CONFIG_HOME/JustATuner/` (or `~/.config/JustATuner/`)

## Credits

Built by Matt Stohrer ([stohrermusic.com]). The strobe-tuner side is
extracted from [Stohrer Sax Shop Companion][ssc]; the JI-exerciser side
is the original [JustATone][jat] Python prototype.

[ssc]: https://github.com/stohrermusic/Stohrer-Sax-Shop-Companion
[jat]: https://github.com/stohrermusic/justatone
[gpu]: https://github.com/stohrermusic/Stohrer-Sax-Shop-Companion/tree/main/tuner_renderer
[sounddevice]: https://python-sounddevice.readthedocs.io/
[stohrermusic.com]: https://www.stohrermusic.com
