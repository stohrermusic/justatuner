# JustATuner — strobe tuner

*The tuner engine: FFT analysis, the Hann peak estimator, phase tracking, stream health, the synthetic source. The GPU renderer's traps are in CLAUDE.md's ledger and Per-Platform Constraints. Companion to CLAUDE.md; same rules, same voice. Edited in the same commit as the code it describes.*

## Tuner engine (`tuner/engine.py`)

12 chromatic pitch classes, each with seven concentric rings (one per octave). FFT-based pitch detection with per-pitch-class phase tracking — phase deviation drives the stroboscopic rotation effect. Magnitude normalization is gated: `max_mag` must exceed `threshold * 1.5` before normalizing to 0–1, otherwise all magnitudes are zeroed. This prevents sensitive mics from showing wheel activity on room noise.

Peak frequency (both the per-ring estimate and the strongest-octave estimate that drives the VU and the wheel phase) comes from `audio_utils.hann_peak_freq`, the Hann closed form — not a parabola, which read in-tune low notes up to 15 c off (see the traps). Magnitudes are read as before.

`synthetic_hz` (default None) is the test/CI source: when set, `start()` opens no stream, sizes the ring buffer itself, and `analyze()` feeds `audio_utils.synthetic_tone` (fundamental + −6 dB H2, phase-continuous from `_synth_pos`) before the stale check. `silent_seconds()` stays 0 (no stream), so the MIC lamp reads green. Nothing in normal use sets it.

Audio stream health monitoring via `AudioRingBuffer.is_stale()` — if no new audio data arrives for ~1 second, the engine restarts the sounddevice stream. Recovers from silent callback death on Windows. The ring buffer is sized at open to `max(rate × 0.2 s, FFT_SIZE)` so a 16 kHz stream still fills one FFT frame.

`start(device)` falls back to the system default when the requested device won't open (unplugged since it was saved, grabbed exclusively, index shifted) and logs a warning; `_last_device` is updated so auto-restarts stay on the working device.
