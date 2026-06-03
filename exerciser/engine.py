"""Audio engine: drone synthesis and microphone input with pitch detection."""

import threading
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
        self.drone_type = "rich"      # sine, rich
        self.drone_volume = 0.3

        # Oscillator internals
        self._osc_freqs = []          # [(freq, amplitude), ...]
        self._osc_phases = None       # numpy array of phases
        self._target_amp = 0.0        # for fade in/out
        self._current_amp = 0.0
        self._amp_slew = 0.005        # amplitude change per sample

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

    def _output_callback(self, outdata, frames, time_info, status):
        if not self._osc_freqs:
            outdata[:] = 0
            return

        freqs = np.array([f for f, _ in self._osc_freqs])
        amps = np.array([a for _, a in self._osc_freqs])

        phase_incs = 2.0 * np.pi * freqs / self.sr
        t = np.arange(frames).reshape(-1, 1)
        phases = self._osc_phases + phase_incs * t
        signal = np.sum(amps * np.sin(phases), axis=1)

        self._osc_phases = (self._osc_phases + phase_incs * frames) % (2 * np.pi)

        peak = max(np.sum(amps), 0.01)
        signal = signal / peak

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
        if self.drone_type == "sine":
            osc_list = voices[:]
        else:  # rich
            for base_f, base_a in voices:
                osc_list.append((base_f, base_a))
                for n in range(2, 9):
                    osc_list.append((base_f * n, base_a / (n * 1.5)))

        self._osc_freqs = osc_list
        self._osc_phases = np.zeros(len(osc_list))
