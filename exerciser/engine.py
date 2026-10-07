"""Audio engine: drone synthesis and microphone input with pitch detection."""

import logging
import math
import os
import struct
import threading
import time
import wave
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from audio_utils import open_input_stream, open_output_stream, synthetic_tone
from exerciser.pitch import yin_detect, moving_median_filter

_log = logging.getLogger(__name__)


# Preferred rate for both streams. Either stream may end up at a different
# rate if the device refuses 44.1 kHz (CoreAudio doesn't resample the way
# Windows/PulseAudio do): the mic runs at ``in_sr`` and the drone output
# at ``sr``, and every bit of frequency math reads the matching one.
SAMPLE_RATE = 44100
INPUT_BLOCK = 4096     # ~93ms at 44.1 kHz - enough for low notes
OUTPUT_BLOCK = 1024    # ~23ms - smooth drone output

# Input stream health: if no callback has delivered audio for this long
# the stream is presumed dead (device unplugged, default device switched
# underneath us on macOS, PortAudio callback silently stopped) ...
INPUT_STALE_S = 1.5
# ... and we retry opening it, at most this often. Also paces retries
# when the mic couldn't be opened at all, so plugging one in later works.
INPUT_RETRY_S = 3.0

# Drone cancellation when the drone plays through speakers (monitoring
# "speakers"). The app generates the drone, so each partial arrives at the
# mic as the same tone with one amplitude and one phase: one complex gain
# per partial. When the drone starts (or changes note), the engine waits
# for it to reach the mic, listens for BLEED_LISTEN_S with the player
# presumed silent, fits each partial's gain and its phase drift (the mic
# and speaker streams run on separate clocks: 2.6 ppm here, 0.1-0.7 deg/s),
# then subtracts the predicted bleed from every buffer. The gains keep
# tracking only while no pitch is detected, so a held unison is never
# learned as bleed. All timing is in input-sample time, so tests run
# faster than real time. Measured 2026-10-07; see tools/test_drone_cancel.py.
BLEED_SETTLE_S = 0.4
BLEED_LISTEN_S = 3.0
BLEED_TRACK_TAU_S = 4.0
BLEED_PAUSE_S = 1.0
MONITORING_SPEAKERS = "speakers"
MONITORING_HEADPHONES = "headphones"

# Chord voicings as just ratios above the root, with the amplitude of each
# voice. The first four are the original drone voicings; the rest arrived
# with progressions (2026-10-07). dom7 is the harmonic seventh 7:4, min7 the
# just minor seventh 9:5, dim uses the septimal tritone 7:5, aug 25:16.
VOICINGS = {
    "root":  [(1, 1.0)],
    "fifth": [(1, 1.0), (3 / 2, 0.7)],
    "major": [(1, 1.0), (5 / 4, 0.6), (3 / 2, 0.7)],
    "minor": [(1, 1.0), (6 / 5, 0.6), (3 / 2, 0.7)],
    "maj7":  [(1, 1.0), (5 / 4, 0.6), (3 / 2, 0.7), (15 / 8, 0.5)],
    "dom7":  [(1, 1.0), (5 / 4, 0.6), (3 / 2, 0.7), (7 / 4, 0.5)],
    "min7":  [(1, 1.0), (6 / 5, 0.6), (3 / 2, 0.7), (9 / 5, 0.5)],
    "sus4":  [(1, 1.0), (4 / 3, 0.6), (3 / 2, 0.7)],
    "sus2":  [(1, 1.0), (9 / 8, 0.6), (3 / 2, 0.7)],
    "dim":   [(1, 1.0), (6 / 5, 0.6), (7 / 5, 0.6)],
    "aug":   [(1, 1.0), (5 / 4, 0.6), (25 / 16, 0.6)],
}
VOICING_LABELS = {
    "root": "Root", "fifth": "Root + Fifth", "major": "Major Triad", "minor": "Minor Triad",
    "maj7": "Major 7th", "dom7": "Dominant 7th (7:4)", "min7": "Minor 7th", "sus4": "Sus4",
    "sus2": "Sus2", "dim": "Diminished", "aug": "Augmented",
}
# Short chord symbols for the progression notation ("C", "Fm", "G7", ...).
VOICING_SYMBOLS = {
    "root": "1", "fifth": "5", "major": "", "minor": "m", "maj7": "maj7", "dom7": "7",
    "min7": "m7", "sus4": "sus4", "sus2": "sus2", "dim": "dim", "aug": "aug",
}
# Crossfade from the old chord to the new one over this much of the first
# output block, so a change doesn't click (the phases restart at zero).
CHORD_XFADE_FRAMES = 1024

# Instrument presets: (fmin, fmax, yin_threshold, confidence_threshold, description)
INSTRUMENT_PRESETS = {
    "Auto":            (65,  2500, 0.25, 0.20, "Automatic detection"),
    "Voice":           (75,  1200, 0.30, 0.15, "Singing voice (all ranges)"),
    "Soprano Sax":     (190, 1400, 0.20, 0.20, "Soprano saxophone"),
    "Alto Sax":        (130, 950,  0.20, 0.20, "Alto saxophone"),
    "Tenor Sax":       (95,  700,  0.20, 0.20, "Tenor saxophone"),
    "Bari Sax":        (65,  450,  0.20, 0.20, "Baritone saxophone"),
    "Trumpet":         (170, 1200, 0.20, 0.20, "Trumpet"),
    "Trombone":        (75,  500,  0.20, 0.20, "Trombone"),
    "Flute":           (240, 2200, 0.28, 0.18, "Flute"),
    "Clarinet":        (140, 1900, 0.22, 0.20, "Clarinet"),
    "Violin":          (190, 3200, 0.22, 0.20, "Violin"),
    "Cello":           (60,  1000, 0.22, 0.20, "Cello"),
    "Guitar":          (75,  1400, 0.22, 0.20, "Acoustic guitar"),
    "Bass":            (35,  400,  0.22, 0.20, "Bass (electric/upright)"),
}


def get_default_input_device():
    """Return index of default input device, or None."""
    if sd is None:
        return None
    try:
        return sd.default.device[0]
    except Exception:
        return None


class AudioEngine:
    """Manages audio input (mic) and output (drone) streams."""

    def __init__(self):
        self.sr = SAMPLE_RATE      # output (drone) rate, set when the stream opens
        self.in_sr = SAMPLE_RATE   # input (mic) rate, set when the stream opens
        self.running = False

        # Input device
        self._input_device = None  # None = system default
        # Why the mic isn't delivering, for the UI (None = healthy).
        self.input_error = None
        self._last_input_time = 0.0     # monotonic time of last input callback
        self._last_input_attempt = 0.0  # monotonic time of last open attempt
        self._last_nonzero_time = 0.0   # monotonic time of last non-zero sample
        # Synthetic source (same hook as TunerEngine.synthetic_hz): when set
        # (Hz), start() opens no microphone and get_pitch() feeds a
        # harmonic-rich tone into the input ring itself, so the drone tab
        # runs end to end on a machine with no input device (CI, the
        # --selftest, the --tour). Never set in normal use.
        self.synthetic_hz = None
        self._synth_pos = 0

        # Instrument/detection settings
        self._fmin = 65
        self._fmax = 2500
        self._yin_threshold = 0.25
        self._conf_threshold = 0.20

        # Input state — accumulate into a larger ring buffer for better detection
        self._ring_size = INPUT_BLOCK * 2  # ~186ms of audio
        self._ring_buf = np.zeros(self._ring_size)
        self._ring_pos = 0
        self._in_total = 0            # samples ever pushed: the cancellation's time base

        # Drone-bleed cancellation state (see the BLEED_* constants).
        self.monitoring = MONITORING_SPEAKERS
        self._bleed_state = "idle"    # idle | settle | listen | ready
        self._bleed_t0 = 0.0          # input-sample time the current phase began
        self._bleed_obs = []          # (t, gains array) collected while listening
        self._bleed_gain = None       # complex gain per partial at _bleed_tref
        self._bleed_slope = None      # phase drift per partial, rad/s
        self._bleed_tref = 0.0
        self._bleed_last_pitch_t = 0.0
        self._bleed_freqs = None      # partials the current gains belong to
        self._bleed_epoch = None      # output epoch those gains were fitted against
        # The room: per partial frequency heard this session, its amplitude
        # and phase relative to the output's own phase, so a chord heard once
        # needs no second listen (the progression pre-calibrates every chord
        # once). Cleared whenever a stream reopens: the two streams' clocks
        # then start at a new unknown offset. _room_ppm is the mic-vs-speaker
        # clock difference, one number for the session.
        self._room = {}               # round(f, 3) -> (amp, psi, t_cal)
        self._room_ppm = 0.0
        self.buffer_lock = threading.Lock()
        self.buffer_ready = False
        self.pitch_history = []
        self.latest_pitch = None      # Hz or None
        self.latest_confidence = 0.0
        self._miss_count = 0          # consecutive frames with no detection
        self._hold_frames = 6         # hold last pitch for this many misses (~500ms)

        # Lissajous buffer - stores recent mic samples for display
        self._lissajous_lock = threading.Lock()
        self._lissajous_mic = np.zeros(INPUT_BLOCK)
        self._ref_phase = 0.0  # continuous phase for Lissajous reference

        # Drone state
        self.drone_on = False
        self.drone_freq = 261.63      # C4
        self.drone_voicing = "root"   # root, fifth, major, minor
        self.drone_type = "rich"      # sine, rich, sample
        self.drone_volume = 0.3

        # Oscillator internals. _osc_freqs is the canonical voicing list
        # (read by the sample path, the cancellation and the UI); the synth
        # path renders from _synth, a dict the output callback swaps in
        # from _synth_pending at a block boundary, recording the output
        # sample index ("epoch") at which its phases started from zero.
        self._osc_freqs = []          # [(freq, amplitude), ...]
        self._osc_phases = None       # kept for compatibility; _synth holds the live phases
        self._synth = None            # {"freqs", "amps", "phases", "epoch"}
        self._synth_pending = None
        self._out_total = 0           # output samples rendered: the epoch time base
        self._target_amp = 0.0        # for fade in/out
        self._current_amp = 0.0
        self._amp_slew = 0.005        # amplitude change per sample

        # Sample-drone state. When drone_type == "sample" and a sample is
        # loaded, _output_callback resamples it on the fly to whatever
        # frequency each voice in the voicing is set to (instead of
        # summing sine oscillators). The same voicing list (_osc_freqs)
        # drives both paths — for samples it's a list of (freq, amp)
        # playheads instead of oscillators. _sample_phases is the float
        # playback position into _drone_sample for each voice.
        self._drone_sample = None       # numpy float32, mono, normalized
        self._drone_sample_sr = None    # original sample rate
        self._drone_sample_freq = None  # detected fundamental Hz
        self._drone_sample_label = ""   # short label for UI ("file.wav" or "recorded")
        self._sample_phases = None      # float ndarray, one per voice
        self._sample_lock = threading.Lock()

        # Recording state — append to _recording_chunks from _input_callback
        # when _recording is True; concatenate on stop.
        self._recording = False
        self._recording_chunks = []
        self._recording_lock = threading.Lock()

        # Streams
        self._input_stream = None
        self._output_stream = None

        self._rebuild_oscillators()

    def start(self):
        """Start audio streams."""
        if sd is None:
            raise RuntimeError(
                "sounddevice not installed. Run: pip install sounddevice"
            )
        self.running = True
        self._start_input_stream()
        self._start_output_stream()

    def input_open(self):
        """True while the mic stream (or the synthetic source) delivers."""
        return self._input_stream is not None or bool(self.synthetic_hz)

    def _feed_synthetic(self):
        """Next block of the synthetic tone into the input ring, the way the
        audio callback would: fundamental plus two harmonics at -6/-12 dB."""
        block = synthetic_tone(self._synth_pos, INPUT_BLOCK, float(self.synthetic_hz),
                               self.in_sr, harmonics_db=(0.0, -6.0, -12.0))
        self._synth_pos += INPUT_BLOCK
        self._push_input(block)

    def _start_input_stream(self):
        """Start (or restart) the input stream."""
        self._room = {}               # new stream, new clock offset: the room is unknown again
        if self.synthetic_hz:
            self._input_stream = None
            self.input_error = None
            self._synth_pos = 0
            return
        if self._input_stream is not None:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        now = time.monotonic()
        self._last_input_attempt = now
        try:
            self._input_stream, self.in_sr = open_input_stream(
                sd, self._input_device, SAMPLE_RATE,
                channels=1,
                blocksize=INPUT_BLOCK,
                dtype="float32",
                callback=self._input_callback,
            )
            self._input_stream.start()
            self._last_input_time = now
            self._last_nonzero_time = now
            if self.input_error:
                _log.warning("Microphone recovered (device %r, %d Hz)",
                             self._input_device, self.in_sr)
            self.input_error = None
        except Exception as e:
            self._input_stream = None
            msg = str(e).strip() or type(e).__name__
            if msg != self.input_error:
                # Log each distinct failure once, not once per retry.
                _log.warning("Could not open microphone (device %r): %s",
                             self._input_device, msg)
            self.input_error = msg

    def _start_output_stream(self):
        """Start the output stream."""
        if self._output_stream is not None:
            return  # already running
        try:
            self._output_stream, self.sr = open_output_stream(
                sd, None, SAMPLE_RATE,
                channels=1,
                blocksize=OUTPUT_BLOCK,
                dtype="float32",
                callback=self._output_callback,
            )
            self._output_stream.start()
        except Exception as e:
            _log.warning("Could not open audio output: %s", e)
            self._output_stream = None

    def silent_seconds(self):
        """Seconds since the mic last delivered a non-zero sample (0.0 when
        the stream isn't open). Exact digital silence while the stream is
        alive is what a denied macOS mic permission or a muted input looks
        like; a quiet room still has a noise floor."""
        if self._input_stream is None:
            return 0.0
        return time.monotonic() - self._last_nonzero_time

    def _check_input_health(self):
        """Reopen the mic if it never opened or its callback went quiet.

        Called from get_pitch() on the UI timer. The tuner engine does the
        same via AudioRingBuffer.is_stale(); here we timestamp callbacks
        directly. Paced by INPUT_RETRY_S so a genuinely absent device
        doesn't hammer PortAudio.
        """
        if not self.running or self.synthetic_hz:
            return
        now = time.monotonic()
        if self._input_stream is None:
            stale = True
        else:
            stale = (now - self._last_input_time) > INPUT_STALE_S
        if stale and (now - self._last_input_attempt) > INPUT_RETRY_S:
            if self._input_stream is not None:
                _log.warning("Microphone stream went silent for %.1fs; restarting",
                             now - self._last_input_time)
            self._start_input_stream()

    def stop(self):
        """Stop and close audio streams.

        stop()/close() can raise PortAudioError if the device vanished
        (Bluetooth disconnect is the common case) — swallow it so a tab
        switch or app close still completes. Mirrors TunerEngine.stop().
        """
        self.running = False
        self._room = {}
        self._bleed_state = "idle"
        if self._input_stream is not None:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None
        if self._output_stream is not None:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

    def set_input_device(self, device_index):
        """Switch to a different input device. Pass None for system default."""
        self._input_device = device_index
        # Clear state
        with self.buffer_lock:
            self._ring_buf = np.zeros(self._ring_size)
            self._ring_pos = 0
            self.buffer_ready = False
        self.pitch_history.clear()
        self.latest_pitch = None
        self.latest_confidence = 0.0
        self._miss_count = 0
        # Restart input stream with new device
        if self.running:
            self._start_input_stream()

    def set_instrument(self, preset_name):
        """Apply an instrument preset for pitch detection tuning."""
        preset = INSTRUMENT_PRESETS.get(preset_name)
        if preset:
            self._fmin, self._fmax, self._yin_threshold, self._conf_threshold, _ = preset
            # Clear pitch history when switching instruments
            self.pitch_history.clear()
            self.latest_pitch = None
            self.latest_confidence = 0.0
            self._miss_count = 0

    def set_drone(self, on=None, freq=None, voicing=None, dtype=None, volume=None):
        """Update drone parameters. Pass only what changed."""
        rebuild = False
        if on is not None:
            if on and not self.drone_on:
                self._bleed_reset()
            elif not on:
                self._bleed_state = "idle"
            self.drone_on = on
            self._target_amp = self.drone_volume if on else 0.0
        if freq is not None and freq != self.drone_freq:
            self.drone_freq = freq
            rebuild = True
        if voicing is not None and voicing != self.drone_voicing:
            self.drone_voicing = voicing
            rebuild = True
        if dtype is not None and dtype != self.drone_type:
            self.drone_type = dtype
            rebuild = True
        if volume is not None:
            self.drone_volume = volume
            if self.drone_on:
                self._target_amp = volume
        if rebuild:
            self._rebuild_oscillators()

    def get_pitch(self):
        """Get the latest detected pitch. Returns (freq_hz, confidence)."""
        if self.synthetic_hz and self.running:
            self._feed_synthetic()
        self._check_input_health()
        with self.buffer_lock:
            if not self.buffer_ready:
                return self.latest_pitch, self.latest_confidence
            buf = np.roll(self._ring_buf, -self._ring_pos).copy()
            t_start = (self._in_total - self._ring_size) / float(self.in_sr)
            self.buffer_ready = False

        # Cancel the drone from the mic signal before pitch detection
        if self.drone_on and self._osc_freqs:
            buf = self._cancel_drone(buf, t_start)
            if buf is None:            # still listening to the room
                return None, 0.0

        freq, conf = yin_detect(
            buf, self.in_sr,
            fmin=self._fmin, fmax=self._fmax,
            threshold=self._yin_threshold,
        )

        if freq is not None and conf > self._conf_threshold:
            self._bleed_last_pitch_t = t_start
            self.pitch_history.append(freq)
            if len(self.pitch_history) > 15:
                self.pitch_history = self.pitch_history[-15:]
            smoothed = moving_median_filter(self.pitch_history, window=5)
            self.latest_pitch = smoothed
            self.latest_confidence = conf
            self._miss_count = 0
        else:
            self._miss_count += 1
            if self._miss_count > self._hold_frames:
                self.pitch_history.clear()
                self.latest_pitch = None
                self.latest_confidence = 0.0

        return self.latest_pitch, self.latest_confidence

    def get_lissajous_data(self, root_freq, num_points=1200):
        """Get reference and mic signals for Lissajous display."""
        with self._lissajous_lock:
            mic = self._lissajous_mic.copy()

        if len(mic) > num_points:
            mic = mic[-num_points:]

        # The reference sine is generated at the *mic* rate so the two
        # traces line up sample-for-sample.
        n = len(mic)
        t = np.arange(n) / self.in_sr
        ref = np.sin(2 * np.pi * root_freq * t + self._ref_phase)
        self._ref_phase = (self._ref_phase + 2 * np.pi * root_freq * n / self.in_sr) % (2 * np.pi)

        return ref, mic

    # -- Drone-bleed cancellation --

    def bleed_status(self):
        """"off" (headphones, drone off, or a sample drone), "listening"
        while the room is being measured, "ready" while cancelling."""
        if not self.drone_on or self.monitoring != MONITORING_SPEAKERS \
                or self.drone_type == "sample" or not self._osc_freqs:
            return "off"
        return "ready" if self._bleed_state == "ready" else "listening"

    def room_known(self, freqs=None):
        """True when every partial of the given (default: current) voicing
        has been heard this session, so switching to it needs no listen."""
        if freqs is None:
            freqs = [f for f, _ in self._osc_freqs]
        return bool(freqs) and all(round(f, 3) in self._room for f in freqs)

    def _bleed_reset(self):
        """The drone just started or changed chord: the partials' phases at
        the mic are new. Bank what the last chord taught us about the room,
        then settle; _cancel_drone decides whether a listen is needed."""
        if self._bleed_state == "ready" and self._bleed_gain is not None:
            self._room_store()
        self._bleed_state = "settle"
        self._bleed_t0 = self._in_total / float(self.in_sr)
        self._bleed_obs = []
        self._bleed_gain = None
        self._bleed_slope = None
        self._bleed_freqs = None
        self._bleed_epoch = None

    def _room_store(self):
        """Bank the current gains as room entries: amplitude and the phase
        relative to the output's own phase (psi), per partial frequency."""
        if self._bleed_freqs is None or self._bleed_epoch is None:
            return
        # The projection demodulates against exp(-i 2 pi f t), so for a
        # steady chord its phase is constant in time: what the epoch
        # contributes is -2 pi f epoch / sr (the chord's phases restarted at
        # zero there), and what remains is the room. Store the room part.
        for k, f in enumerate(self._bleed_freqs):
            g = self._bleed_gain[k]
            psi = np.angle(g) + 2 * np.pi * f * self._bleed_epoch / float(self.sr)
            self._room[round(f, 3)] = (float(abs(g)), float(psi), float(self._bleed_tref))

    def _room_derive(self, freqs, epoch, t_mid):
        """Gains for a chord whose partials are all in the room, at this
        output epoch and input time, without listening."""
        k = len(freqs)
        gain = np.zeros(k, dtype=complex)
        slope = np.zeros(k)
        for i, f in enumerate(freqs):
            amp, psi, t_cal = self._room[round(f, 3)]
            slope[i] = 2 * np.pi * f * self._room_ppm * 1e-6
            phase = psi - 2 * np.pi * f * epoch / float(self.sr) + slope[i] * (t_mid - t_cal)
            gain[i] = amp * np.exp(1j * phase)
        self._bleed_gain = gain
        self._bleed_slope = slope
        self._bleed_tref = t_mid
        self._bleed_freqs = list(freqs)
        self._bleed_epoch = epoch

    def _bleed_project(self, buf, t_start, freqs):
        """Complex amplitude of each partial in buf (Hann-windowed), and the
        matrix of references so the caller can rebuild the bleed."""
        n = len(buf)
        t = t_start + np.arange(n) / float(self.in_sr)
        refs = np.exp(-2j * np.pi * np.asarray(freqs)[:, None] * t[None, :])
        w = np.hanning(n)
        c = refs @ (buf * w) / w.sum()
        return c, refs

    def _cancel_drone(self, buf, t_start):
        """Remove the drone from the mic buffer. Returns the cleaned buffer,
        or None while the room is still being listened to.

        Speakers: subtract each partial's predicted bleed (gain and phase
        drift learned during the listen, tracked during the player's
        pauses). Headphones: nothing to remove. Sample drone: the old
        +-4 Hz spectral notch, since a sample is not a known set of partials.
        """
        if self.monitoring == MONITORING_HEADPHONES:
            return buf
        if self.drone_type == "sample":
            return self._notch_drone(buf)

        freqs = [f for f, _ in self._osc_freqs]
        t_mid = t_start + 0.5 * len(buf) / float(self.in_sr)
        syn = self._synth
        if syn is None or syn["epoch"] is None or len(syn["freqs"]) != len(freqs) \
                or not np.allclose(syn["freqs"], freqs):
            return None                # the new chord hasn't reached the output yet
        epoch = syn["epoch"]
        c, refs = self._bleed_project(buf, t_start, freqs)

        if self._bleed_state == "idle":
            self._bleed_reset()
        if self._bleed_state == "settle":
            if t_mid - self._bleed_t0 < BLEED_SETTLE_S:
                return None            # the old chord's tail is still arriving
            if self.room_known(freqs):
                self._room_derive(freqs, epoch, t_mid)
                self._bleed_state = "ready"
            else:
                self._bleed_state = "listen"
                self._bleed_t0 = t_mid
        if self._bleed_state == "listen":
            self._bleed_obs.append((t_mid, c))
            if t_mid - self._bleed_t0 < BLEED_LISTEN_S:
                return None
            self._bleed_fit()
            self._bleed_freqs = list(freqs)
            self._bleed_epoch = epoch
            self._room_learn_ppm()
            self._room_store()
            self._bleed_state = "ready"

        # Predicted bleed at this buffer's time, then subtract it.
        dt = t_mid - self._bleed_tref
        pred = self._bleed_gain * np.exp(1j * self._bleed_slope * dt)
        cleaned = buf - 2.0 * np.real(pred @ np.conj(refs))

        # Track the gains only while the player is silent, so a held note
        # at the drone's own pitch is never learned as bleed.
        if t_mid - self._bleed_last_pitch_t > BLEED_PAUSE_S and self.latest_pitch is None:
            alpha = min(1.0, (len(buf) / float(self.in_sr)) / BLEED_TRACK_TAU_S)
            measured = c * np.exp(-1j * self._bleed_slope * dt)
            self._bleed_gain = self._bleed_gain + alpha * (measured - self._bleed_gain)
        return cleaned

    def _bleed_fit(self):
        """Fit each partial's complex gain and phase-drift rate from the
        observations collected during the listen."""
        ts = np.array([t for t, _ in self._bleed_obs])
        cs = np.array([c for _, c in self._bleed_obs])       # (n_obs, K)
        self._bleed_tref = float(ts.mean())
        k = cs.shape[1]
        gain = np.zeros(k, dtype=complex)
        slope = np.zeros(k)
        for i in range(k):
            ph = np.unwrap(np.angle(cs[:, i]))
            if len(ts) >= 3:
                s, b = np.polyfit(ts - self._bleed_tref, ph, 1)
            else:
                s, b = 0.0, float(np.mean(ph))
            slope[i] = s
            gain[i] = float(np.mean(np.abs(cs[:, i]))) * np.exp(1j * b)
        self._bleed_gain = gain
        self._bleed_slope = slope

    def _room_learn_ppm(self):
        """One clock-difference number for the session from the partials'
        fitted drift rates (slope = 2 pi f ppm 1e-6), weighted toward the
        loud ones; then every partial drifts by the same rule."""
        if self._bleed_gain is None or self._bleed_freqs is None:
            return
        amps = np.abs(self._bleed_gain)
        strong = amps >= 0.1 * (amps.max() if amps.size else 0)
        if not strong.any() or amps.max() <= 0:
            return
        est = [self._bleed_slope[i] / (2 * np.pi * f * 1e-6)
               for i, f in enumerate(self._bleed_freqs) if strong[i]]
        self._room_ppm = float(np.median(est))
        self._bleed_slope = np.array([2 * np.pi * f * self._room_ppm * 1e-6 for f in self._bleed_freqs])

    def _notch_drone(self, buf):
        """Remove drone frequencies with a +-4 Hz spectral notch (sample
        drones only: not a known set of partials). Leaks: the drone itself
        still reads as a unison through it, and a third over bleed reads
        -12 c (measured 2026-10-06); headphones are the answer there."""
        n = len(buf)
        spectrum = np.fft.rfft(buf)
        freqs = np.fft.rfftfreq(n, 1.0 / self.in_sr)
        for osc_freq, _ in self._osc_freqs:
            spectrum[np.abs(freqs - osc_freq) < 4.0] = 0
        return np.fft.irfft(spectrum, n)

    # -- Internal --

    def _input_callback(self, indata, frames, time_info, status):
        self._push_input(indata[:, 0].copy())

    def _push_input(self, data):
        """One block of mono input into the ring, the Lissajous buffer and
        the recording, from the audio callback or the synthetic source."""
        self._last_input_time = time.monotonic()
        if data.any():
            self._last_nonzero_time = self._last_input_time
        with self.buffer_lock:
            n = len(data)
            end = self._ring_pos + n
            if end <= self._ring_size:
                self._ring_buf[self._ring_pos:end] = data
            else:
                split = self._ring_size - self._ring_pos
                self._ring_buf[self._ring_pos:] = data[:split]
                self._ring_buf[:n - split] = data[split:]
            self._ring_pos = end % self._ring_size
            self._in_total += n
            self.buffer_ready = True
        with self._lissajous_lock:
            self._lissajous_mic = data
        # Recording path: append a copy of this block to the recording
        # buffer when active. We hold the lock briefly to avoid racing
        # with stop_and_use's concatenation.
        if self._recording:
            with self._recording_lock:
                if self._recording:
                    self._recording_chunks.append(data.copy())

    def _output_callback(self, outdata, frames, time_info, status):
        if not self._osc_freqs:
            outdata[:] = 0
            return

        # ---- Synthesize the per-voice signal ----
        if self.drone_type == "sample" and self._drone_sample is not None:
            signal = self._render_sample_voices(frames)
            self._out_total += frames
        else:
            signal = self._render_synth_block(frames)

        # ---- Amp envelope (slew for fade in/out) ----
        envelope = np.empty(frames)
        for i in range(frames):
            if self._current_amp < self._target_amp:
                self._current_amp = min(
                    self._current_amp + self._amp_slew, self._target_amp
                )
            elif self._current_amp > self._target_amp:
                self._current_amp = max(
                    self._current_amp - self._amp_slew, self._target_amp
                )
            envelope[i] = self._current_amp

        signal *= envelope
        outdata[:, 0] = np.clip(signal, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def _render_synth(voices, frames, sr):
        """One block of the voices' sines, advancing their phases."""
        freqs, amps, phases = voices["freqs"], voices["amps"], voices["phases"]
        if len(freqs) == 0:
            return np.zeros(frames)
        incs = 2.0 * np.pi * freqs / sr
        t = np.arange(frames).reshape(-1, 1)
        signal = np.sum(amps * np.sin(phases + incs * t), axis=1)
        voices["phases"] = (phases + incs * frames) % (2 * np.pi)
        return signal / max(float(np.sum(amps)), 0.01)

    def _render_synth_block(self, frames):
        """Render the synth drone; swap in a pending chord at this block
        boundary, record its epoch, and crossfade from the old one so the
        change doesn't click (phases restart at zero)."""
        pending = self._synth_pending
        if pending is not None:
            self._synth_pending = None
            pending["epoch"] = self._out_total
            old = self._synth
            self._synth = pending
            signal = self._render_synth(pending, frames, self.sr)
            if old is not None and len(old["freqs"]):
                n = min(frames, CHORD_XFADE_FRAMES)
                old_sig = self._render_synth(old, frames, self.sr)
                ramp = np.ones(frames)
                ramp[:n] = np.linspace(0.0, 1.0, n)
                signal = old_sig * (1.0 - ramp) + signal * ramp
        elif self._synth is not None:
            signal = self._render_synth(self._synth, frames, self.sr)
        else:
            signal = np.zeros(frames)
        self._out_total += frames
        return signal

    def _render_sample_voices(self, frames):
        """Resample-and-loop the loaded WAV sample for every voice in
        the current voicing, sum the results, normalize. Runs on the
        audio callback thread."""
        with self._sample_lock:
            sample = self._drone_sample
            sample_sr = self._drone_sample_sr
            sample_freq = self._drone_sample_freq
            phases = self._sample_phases
        if sample is None or phases is None or len(self._osc_freqs) == 0:
            return np.zeros(frames, dtype=np.float64)

        N = sample.shape[0]
        amps = np.array([a for _, a in self._osc_freqs])
        # Per-voice playback rate. Pitch shift = target_freq / sample_freq;
        # sample-rate ratio = sample_sr / output_sr; combined drives how
        # many sample-frames to advance per output frame.
        rates = np.array([
            (f / sample_freq) * (sample_sr / self.sr)
            for f, _ in self._osc_freqs
        ])

        signal = np.zeros(frames, dtype=np.float64)
        for v in range(len(self._osc_freqs)):
            pos = phases[v]
            rate = rates[v]
            # Vectorized sample positions for this voice's `frames`
            # output samples, wrapped modulo N.
            idx_float = (pos + rate * np.arange(frames)) % N
            i0 = idx_float.astype(np.int64)
            frac = idx_float - i0
            # Catmull-Rom cubic interpolation (4-tap) instead of 2-tap
            # linear — much less harsh when a sample is pitched well away
            # from its source pitch (loading arbitrary WAVs at any octave).
            # The mod-N taps ride across the loop boundary, which
            # _install_sample already crossfaded smooth.
            im1 = (i0 - 1) % N
            i1 = (i0 + 1) % N
            i2 = (i0 + 2) % N
            y0 = sample[im1]
            y1 = sample[i0]
            y2 = sample[i1]
            y3 = sample[i2]
            a0 = -0.5 * y0 + 1.5 * y1 - 1.5 * y2 + 0.5 * y3
            a1 = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3
            a2 = -0.5 * y0 + 0.5 * y2
            voice = ((a0 * frac + a1) * frac + a2) * frac + y1
            signal += amps[v] * voice
            phases[v] = (pos + rate * frames) % N

        with self._sample_lock:
            self._sample_phases = phases

        peak = max(float(np.sum(amps)), 0.01)
        return signal / peak

    # ----- Sample loading / recording / clearing -----

    def load_sample_wav(self, path):
        """Load a WAV file, detect its fundamental pitch, and install it
        as the drone sample. Switches ``drone_type`` to ``'sample'``.

        Returns a dict with ``sr``, ``freq_hz``, ``duration_s``, ``label``
        for the UI to display. Raises ValueError / OSError on bad input.
        """
        sample, sr = _read_wav_file(path)
        return self._install_sample(sample, sr, label=os.path.basename(path))

    def record_start(self):
        """Begin capturing input frames into the recording buffer."""
        with self._recording_lock:
            self._recording_chunks = []
            self._recording = True

    def record_stop_and_use(self):
        """Stop the recording, concatenate the captured frames, analyze
        their pitch, and install them as the drone sample. Returns the
        same dict as ``load_sample_wav`` or None if nothing was captured."""
        with self._recording_lock:
            self._recording = False
            chunks = self._recording_chunks
            self._recording_chunks = []
        if not chunks:
            return None
        sample = np.concatenate(chunks).astype(np.float32)
        if len(sample) < int(self.in_sr * 0.2):
            return None  # too short to be useful (~200ms)
        # Normalize to peak 0.95 so quiet recordings still drive the drone.
        peak = float(np.max(np.abs(sample)))
        if peak > 0.001:
            sample = sample / peak * 0.95
        return self._install_sample(sample, self.in_sr, label="recorded")

    def record_cancel(self):
        """Drop any in-flight recording without installing it."""
        with self._recording_lock:
            self._recording = False
            self._recording_chunks = []

    def is_recording(self):
        return self._recording

    def recorded_duration_s(self):
        """Approximate duration of the in-flight recording in seconds."""
        with self._recording_lock:
            total = sum(len(c) for c in self._recording_chunks)
        return total / self.in_sr if self.in_sr else 0.0

    def clear_sample(self):
        """Drop the loaded sample. Drone falls back to whatever synth
        type the caller chooses next via set_drone(dtype=...)."""
        with self._sample_lock:
            self._drone_sample = None
            self._drone_sample_sr = None
            self._drone_sample_freq = None
            self._drone_sample_label = ""
            self._sample_phases = None
        if self.drone_type == "sample":
            self.drone_type = "rich"
            self._rebuild_oscillators()

    def sample_info(self):
        """Return a (label, freq_hz) tuple describing the loaded sample,
        or (None, None) if none is loaded."""
        with self._sample_lock:
            if self._drone_sample is None:
                return (None, None)
            return (self._drone_sample_label, self._drone_sample_freq)

    def save_sample_wav(self, path):
        """Write the current drone sample to a 16-bit PCM mono WAV at
        ``path``. Backs both the user's "Save Sample As..." export and the
        persistence of recordings (which are otherwise in-memory only) so
        the last sample can be reloaded next launch. Raises ValueError if
        no sample is loaded, OSError if the file can't be written."""
        with self._sample_lock:
            if self._drone_sample is None:
                raise ValueError("No sample loaded to save.")
            sample = self._drone_sample.copy()
            sr = int(self._drone_sample_sr or self.sr)
        # Round, don't truncate: astype() alone cost up to 2 LSB per sample
        # on the round trip (tools/test_sample_pipeline.py, 2026-10-06).
        pcm16 = np.round(np.clip(sample, -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm16.tobytes())

    def _install_sample(self, sample, sr, label):
        """Process raw audio into a loopable drone sample, detect its
        pitch, and swap it in. Holds the sample lock only briefly so
        the audio callback isn't blocked.

        Three steps shape the loaded audio into something that loops
        as cleanly as a real produced sample would:

        1. Trim the attack and release — drop ~200ms from each end so
           the looping region is steady-state. Skipped when the source
           is too short to spare it.
        2. Run YIN on the trimmed middle to find the fundamental
           frequency. Used both for the playback-rate math AND for
           sizing the crossfade.
        3. Trim the sample to a whole number of periods of that pitch and
           blend its tail into its head with a linear crossfade that is
           itself a whole number of periods (4, fewer under the 150 ms /
           25 % caps): head and tail are then in phase, the level stays
           flat through the fade, and the wrap from the last sample back
           to the first lands on the next sample of the waveform.

        Result is a sample that loops without the audible click a
        plain mod-wrap would produce on most instrument tones.
        """
        sample = sample.astype(np.float32, copy=True)
        N_raw = len(sample)

        # ---- 1. Trim attack + release ----
        # Cut up to 200 ms from each end, but never more than 10% of
        # total length — short recordings would lose their meat.
        trim = min(int(0.2 * sr), N_raw // 10)
        if N_raw > 2 * trim + int(0.3 * sr):
            sample = sample[trim : N_raw - trim]

        # ---- 2. Pitch detection on the trimmed middle ----
        N = len(sample)
        mid_start = max(0, N // 2 - sr)        # 1s before midpoint
        mid_end = min(N, N // 2 + sr)          # 1s after
        window = sample[mid_start:mid_end] if mid_end > mid_start else sample
        freq, conf = yin_detect(
            window, sr,
            fmin=55, fmax=2000, threshold=0.30,
        )
        if freq is None or conf < 0.15:
            # Couldn't detect a pitch — fall back to A4 so we still play
            # *something*, and let the UI surface the ambiguity.
            freq = 440.0
            conf = conf or 0.0

        # ---- 3. Period-aligned linear crossfade at the loop boundary ----
        # The loop is a whole number of periods of the detected pitch, and
        # so is the crossfade: then the head and the tail of a steady tone
        # are in phase, a linear (constant-sum) blend keeps the level flat,
        # and the wrap from the last sample back to the first lands on the
        # next sample of the waveform. Measured 2026-10-06 on a 220 Hz
        # tone: the old int()-truncated 4-period fade (800 of 801.8
        # samples) plus equal-power curves gave a seam 2.8x a normal step
        # and a +3/-4 dB swell once per loop, which also pushed a
        # recording normalised to 0.95 past full scale. Four periods is
        # enough for the ear to read the boundary as a fade, not a splice.
        period = sr / freq if freq > 0 else sr * 0.01
        N = int(round(math.floor(N / period) * period)) if N >= 2 * period else N
        sample = sample[:N]
        cap = min(int(0.15 * sr), N // 4)   # 150 ms, and never more than 25 %
        n_periods = min(4, max(1, int(cap // period)))
        crossfade_len = int(round(n_periods * period))
        crossfade_len = max(64, min(crossfade_len, cap))

        if N > 2 * crossfade_len and crossfade_len >= 16:
            head = sample[:crossfade_len].copy()
            tail_idx = N - crossfade_len
            tail = sample[tail_idx:].copy()
            t = np.arange(crossfade_len, dtype=np.float32) / max(1, crossfade_len - 1)
            sample[tail_idx:] = (tail * (1.0 - t) + head * t).astype(np.float32)

        with self._sample_lock:
            self._drone_sample = sample
            self._drone_sample_sr = sr
            self._drone_sample_freq = float(freq)
            self._drone_sample_label = label
            # Reset playback heads for the current voicing length.
            n_voices = max(1, len(self._osc_freqs))
            self._sample_phases = np.zeros(n_voices)

        # Switch to sample mode and rebuild voicing list (which also
        # re-sizes _sample_phases via _rebuild_oscillators).
        self.drone_type = "sample"
        self._rebuild_oscillators()

        return {
            "sr": sr,
            "freq_hz": float(freq),
            "duration_s": len(sample) / sr,
            "label": label,
            "pitch_confident": conf >= 0.15,
        }

    def _rebuild_oscillators(self):
        """Recalculate oscillator bank for current drone settings."""
        f = self.drone_freq
        voices = [(f * ratio, amp) for ratio, amp in VOICINGS.get(self.drone_voicing, VOICINGS["root"])]

        osc_list = []
        if self.drone_type == "sample":
            # One playback head per voicing voice — the sample already
            # carries its own harmonics, so we don't stack a harmonic
            # bank on top of it (that would just create comb-filter
            # artifacts).
            osc_list = voices[:]
        elif self.drone_type == "sine":
            osc_list = voices[:]
        else:  # rich
            for base_f, base_a in voices:
                osc_list.append((base_f, base_a))
                for n in range(2, 9):
                    osc_list.append((base_f * n, base_a / (n * 1.5)))

        self._osc_freqs = osc_list
        self._osc_phases = np.zeros(len(osc_list))
        self._synth_pending = {
            "freqs": np.array([f for f, _ in osc_list], dtype=float),
            "amps": np.array([a for _, a in osc_list], dtype=float),
            "phases": np.zeros(len(osc_list)),
            "epoch": None,
        }
        if self.drone_on:
            self._bleed_reset()        # new partials, new phases at the mic
        # Re-size sample playback heads to match voicing length.
        with self._sample_lock:
            if self._drone_sample is not None:
                self._sample_phases = np.zeros(len(osc_list))


# ----- WAV file reader -----

def _read_float_wav(path):
    """Read an IEEE-float WAV (format tag 3, or extensible with the float
    sub-format): the stdlib `wave` module refuses those outright
    ("unknown format: 3"). Returns (float32 interleaved samples, channels,
    sample rate) or None when the file is not a float WAV."""
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            return None
        f.read(4)
        if f.read(4) != b"WAVE":
            return None
        fmt = None
        data = None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cid, size = struct.unpack("<4sI", hdr)
            body = f.read(size) if cid in (b"fmt ", b"data") else (f.seek(size, 1) or b"")
            if size % 2:
                f.seek(1, 1)                  # chunks are word-aligned
            if cid == b"fmt ":
                fmt = body
            elif cid == b"data":
                data = body
                break
    if fmt is None or data is None or len(fmt) < 16:
        return None
    tag, channels, sr, _, _, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 40:
        tag = struct.unpack("<H", fmt[24:26])[0]   # sub-format's first word
    if tag != 3 or bits not in (32, 64):
        return None
    dtype = "<f4" if bits == 32 else "<f8"
    usable = len(data) - len(data) % (bits // 8)
    samples = np.frombuffer(data[:usable], dtype=dtype).astype(np.float32)
    return samples, channels, sr


def _read_wav_file(path):
    """Read a WAV file → (mono float32 numpy array in -1..1, sample rate).

    Handles 16-bit, 24-bit and 32-bit PCM through the stdlib `wave`
    module, and 32/64-bit IEEE-float WAVs through _read_float_wav (`wave`
    refuses format tag 3). Stereo files are downmixed to mono by averaging.
    """
    try:
        with wave.open(path, 'rb') as w:
            n_channels = w.getnchannels()
            samp_width = w.getsampwidth()
            sr = w.getframerate()
            n_frames = w.getnframes()
            raw = w.readframes(n_frames)
    except wave.Error as e:
        found = _read_float_wav(path)
        if found is None:
            raise ValueError(f"Unsupported WAV format: {e}") from e
        data, n_channels, sr = found
        if n_channels > 1:
            data = data.reshape(-1, n_channels).mean(axis=1)
        return np.clip(data, -1.0, 1.0).astype(np.float32), sr

    if samp_width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif samp_width == 4:
        # `wave` only opens PCM, so 4 bytes is int32. The old "probe the
        # first 1024 samples as float32" guess read any int32 file that
        # starts quietly (leading silence) as float bit patterns: NaN and
        # 1e38 into the drone (tools/test_sample_pipeline.py, 2026-10-06).
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif samp_width == 3:
        # 24-bit PCM — unpack three bytes at a time, sign-extend to int32.
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        i32 = (arr[:, 0].astype(np.int32) |
               (arr[:, 1].astype(np.int32) << 8) |
               (arr[:, 2].astype(np.int32) << 16))
        # Sign-extend the 24-bit values.
        i32 = np.where(i32 & 0x800000, i32 | ~0xFFFFFF, i32)
        data = i32.astype(np.float32) / 8388608.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {samp_width} bytes")

    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)

    return data.astype(np.float32), sr
