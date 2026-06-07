"""Audio engine: drone synthesis and microphone input with pitch detection."""

import os
import threading
import wave
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

from exerciser.pitch import yin_detect, moving_median_filter
from exerciser.intervals import note_freq


SAMPLE_RATE = 44100
INPUT_BLOCK = 4096     # ~93ms - enough for low notes
OUTPUT_BLOCK = 1024    # ~23ms - smooth drone output

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


def list_input_devices():
    """Return list of (index, name) for available input devices."""
    if sd is None:
        return []
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append((i, dev["name"]))
    return devices


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
        self.sr = SAMPLE_RATE
        self.running = False

        # Input device
        self._input_device = None  # None = system default

        # Instrument/detection settings
        self._fmin = 65
        self._fmax = 2500
        self._yin_threshold = 0.25
        self._conf_threshold = 0.20

        # Input state — accumulate into a larger ring buffer for better detection
        self._ring_size = INPUT_BLOCK * 2  # ~186ms of audio
        self._ring_buf = np.zeros(self._ring_size)
        self._ring_pos = 0
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

        # Oscillator internals
        self._osc_freqs = []          # [(freq, amplitude), ...]
        self._osc_phases = None       # numpy array of phases
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

    def _start_input_stream(self):
        """Start (or restart) the input stream."""
        if self._input_stream is not None:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        try:
            self._input_stream = sd.InputStream(
                device=self._input_device,
                channels=1,
                samplerate=self.sr,
                blocksize=INPUT_BLOCK,
                dtype="float32",
                callback=self._input_callback,
            )
            self._input_stream.start()
        except Exception as e:
            print(f"Warning: Could not open microphone: {e}")
            self._input_stream = None

    def _start_output_stream(self):
        """Start the output stream."""
        if self._output_stream is not None:
            return  # already running
        try:
            self._output_stream = sd.OutputStream(
                channels=1,
                samplerate=self.sr,
                blocksize=OUTPUT_BLOCK,
                dtype="float32",
                callback=self._output_callback,
            )
            self._output_stream.start()
        except Exception as e:
            print(f"Warning: Could not open audio output: {e}")
            self._output_stream = None

    def stop(self):
        """Stop and close audio streams."""
        self.running = False
        if self._input_stream is not None:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream is not None:
            self._output_stream.stop()
            self._output_stream.close()
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
        with self.buffer_lock:
            if not self.buffer_ready:
                return self.latest_pitch, self.latest_confidence
            buf = np.roll(self._ring_buf, -self._ring_pos).copy()
            self.buffer_ready = False

        # Cancel drone frequencies from mic signal before pitch detection
        if self.drone_on and self._osc_freqs:
            buf = self._cancel_drone(buf)

        freq, conf = yin_detect(
            buf, self.sr,
            fmin=self._fmin, fmax=self._fmax,
            threshold=self._yin_threshold,
        )

        if freq is not None and conf > self._conf_threshold:
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

        n = len(mic)
        t = np.arange(n) / self.sr
        ref = np.sin(2 * np.pi * root_freq * t + self._ref_phase)
        self._ref_phase = (self._ref_phase + 2 * np.pi * root_freq * n / self.sr) % (2 * np.pi)

        return ref, mic

    # -- Internal --

    def _cancel_drone(self, buf):
        """Remove drone frequencies from mic buffer using spectral notching."""
        n = len(buf)
        spectrum = np.fft.rfft(buf)
        freqs = np.fft.rfftfreq(n, 1.0 / self.sr)

        notch_half_width = 4.0  # Hz each side

        for osc_freq, _ in self._osc_freqs:
            mask = np.abs(freqs - osc_freq) < notch_half_width
            spectrum[mask] = 0

        return np.fft.irfft(spectrum, n)

    def _input_callback(self, indata, frames, time_info, status):
        data = indata[:, 0].copy()
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
        else:
            freqs = np.array([f for f, _ in self._osc_freqs])
            amps = np.array([a for _, a in self._osc_freqs])
            phase_incs = 2.0 * np.pi * freqs / self.sr
            t = np.arange(frames).reshape(-1, 1)
            phases = self._osc_phases + phase_incs * t
            signal = np.sum(amps * np.sin(phases), axis=1)
            self._osc_phases = (self._osc_phases + phase_incs * frames) % (2 * np.pi)
            peak = max(np.sum(amps), 0.01)
            signal = signal / peak

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
        if len(sample) < int(self.sr * 0.2):
            return None  # too short to be useful (~200ms)
        # Normalize to peak 0.95 so quiet recordings still drive the drone.
        peak = float(np.max(np.abs(sample)))
        if peak > 0.001:
            sample = sample / peak * 0.95
        return self._install_sample(sample, self.sr, label="recorded")

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
        return total / self.sr if self.sr else 0.0

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
        pcm16 = (np.clip(sample, -1.0, 1.0) * 32767.0).astype("<i2")
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
        3. Equal-power crossfade between the tail and the head — the
           last N samples become ``tail * cos(πi/2N) + head * sin(πi/2N)``,
           so when the playback head wraps from index L-1 back to 0
           the transition is seamless. Crossfade length is 4 periods
           of the fundamental, capped at 150 ms or 25% of the sample
           length, with a 64-sample floor.

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

        # ---- 3. Equal-power crossfade at the loop boundary ----
        # 4 periods of fundamental is enough for the ear to read the
        # boundary as a smooth fade-through, not a butt-splice.
        period_samples = int(sr / freq) if freq > 0 else int(sr * 0.01)
        crossfade_len = min(
            4 * period_samples,
            int(0.15 * sr),     # 150 ms cap
            N // 4,             # don't fade more than 25% of the sample
        )
        crossfade_len = max(crossfade_len, 64)  # floor

        if N > 2 * crossfade_len and crossfade_len >= 16:
            head = sample[:crossfade_len].copy()
            tail_idx = N - crossfade_len
            tail = sample[tail_idx:].copy()
            # Equal-power (constant-RMS) curves: tail rolls off as
            # cos, head fades in as sin, so their squared sum is
            # 1.0 everywhere — no energy dip across the crossfade.
            i = np.arange(crossfade_len, dtype=np.float32)
            t = i / max(1, crossfade_len - 1)
            tail_w = np.cos(t * np.pi / 2)
            head_w = np.sin(t * np.pi / 2)
            sample[tail_idx:] = (tail * tail_w + head * head_w).astype(np.float32)

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
        voices = [(f, 1.0)]

        if self.drone_voicing == "fifth":
            voices.append((f * 3 / 2, 0.7))
        elif self.drone_voicing == "major":
            voices.append((f * 5 / 4, 0.6))
            voices.append((f * 3 / 2, 0.7))
        elif self.drone_voicing == "minor":
            voices.append((f * 6 / 5, 0.6))
            voices.append((f * 3 / 2, 0.7))

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
        # Re-size sample playback heads to match voicing length.
        with self._sample_lock:
            if self._drone_sample is not None:
                self._sample_phases = np.zeros(len(osc_list))


# ----- WAV file reader -----

def _read_wav_file(path):
    """Read a WAV file → (mono float32 numpy array in -1..1, sample rate).

    Handles 16-bit, 24-bit, and 32-bit PCM, plus 32-bit float WAVs.
    Stereo files are downmixed to mono by averaging channels.
    """
    with wave.open(path, 'rb') as w:
        n_channels = w.getnchannels()
        samp_width = w.getsampwidth()
        sr = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)

    # wave can't tell us float-vs-int — but PCM WAVs report a known
    # sample width (2/3/4 bytes) and float WAVs report 4 bytes with
    # a different format tag we can't read via the stdlib `wave`
    # module. The float case is rare for the kinds of files users
    # will load here (instrument samples are almost always int16),
    # so we default to int and document the limitation.
    if samp_width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif samp_width == 4:
        # Could be int32 or float32; pick by range probing the first
        # ~1k samples — if any |sample| > 1.5, it's int32.
        i32 = np.frombuffer(raw, dtype=np.int32)
        f32 = np.frombuffer(raw, dtype=np.float32)
        probe = f32[: min(1024, len(f32))]
        if probe.size and np.max(np.abs(probe)) <= 1.5:
            data = f32.astype(np.float32)
        else:
            data = i32.astype(np.float32) / 2147483648.0
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
