"""JustATuner settings persistence + defaults.

Stores app_settings.json in a platform-appropriate config directory:
  Windows: %APPDATA%\\JustATuner\\
  macOS:   ~/Library/Application Support/JustATuner/
  Linux:   $XDG_CONFIG_HOME/JustATuner/ (or ~/.config/JustATuner/)

Pattern mirrors Stohrer Sax Shop Companion's config module so users
get the same per-user persistence story.
"""

import copy
import json
import logging
import logging.handlers
import os
import sys


APP_NAME = "JustATuner"
APP_VERSION = "1.1.2"


# Settings defaults. Anything read at runtime MUST exist here — the
# load_settings() merge only preserves keys that already appear in the
# defaults, so runtime-only keys silently disappear on next launch.
DEFAULT_SETTINGS = {
    # Strobe tuner — keys match the SSC tuner_settings block so the
    # tuner view code reads/writes them without translation.
    "tuner_settings": {
        "stripe_color": "#00FF00",
        "reference_pitch": 440.0,
        "transposition": "C",
        "sensitivity": 50,
        "waveform": "pure",
        "fps": "60",
        "ring_brightness": 100,
        "overall_brightness": 80,
        "octave_boost": 50,
        "faceplate_color": "#1A1A1A",
        "show_fps": False,
    },
    # Just-intonation exerciser
    "exerciser_settings": {
        "root_note": 0,
        "octave": 3,
        "transposition": "Concert (C)",
        "drone_voicing": "root",
        "drone_type": "rich",
        "drone_volume": 0.3,
        "show_et_diff": True,
        "instrument": "Auto",
        "visualizer_mode": "Lissajous",
        "scope_color": "Green",
        "scope_trails": 1,
        "scope_thickness": 2,
        "scope_points": 300,
        # Most-recently-used drone sample (WAV path). Reloaded on launch
        # when drone_type == "sample". Recordings are auto-saved into the
        # config dir's recordings/ folder so they can persist by path too.
        "last_sample_path": None,
    },
    # Audio input device (None = system default). Shared across tabs.
    "audio_input_device": None,
    # Which tab is shown at startup
    "active_tab": "tuner",
}


def get_config_dir():
    """Platform-appropriate per-user config directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    elif sys.platform == "darwin":
        path = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


SETTINGS_FILE = os.path.join(get_config_dir(), "app_settings.json")
LOG_FILE = os.path.join(get_config_dir(), "app.log")


def setup_logging():
    """Set up rotating file logging for crash/error diagnostics.

    Writes ``app.log`` to the config dir (rotates at 500KB, keeps 1 backup).
    Without this, diagnostics are invisible in the shipped app: it's built
    --windowed/--noconsole so print()/stderr go nowhere, and Tk silently
    swallows exceptions raised inside callbacks. Returns the log file path.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.WARNING)
    # Idempotent — don't stack handlers if this is called more than once.
    if any(isinstance(h, logging.handlers.RotatingFileHandler)
           for h in logger.handlers):
        return LOG_FILE
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=500_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logging.warning("App starting — version %s", APP_VERSION)
    return LOG_FILE


def get_log_file():
    """Path to the diagnostic log file (may not exist until setup_logging)."""
    return LOG_FILE


def load_settings():
    """Load settings, filling in any missing keys from DEFAULT_SETTINGS.

    Defends against corrupted/null values: top-level keys whose stored
    value is None are replaced with the default; nested dicts that
    decoded to something else (e.g. an int) get reset to their default.
    """
    defaults = copy.deepcopy(DEFAULT_SETTINGS)
    if not os.path.exists(SETTINGS_FILE):
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            return defaults
    except (OSError, json.JSONDecodeError):
        return defaults

    merged = defaults
    for key, default_val in defaults.items():
        if key not in user or user[key] is None:
            continue
        if isinstance(default_val, dict):
            if not isinstance(user[key], dict):
                continue
            # Two-level merge: nested keys from defaults preserved, user
            # values take precedence.
            sub = dict(default_val)
            for sk, sv in user[key].items():
                if sk in sub:
                    sub[sk] = sv
            merged[key] = sub
        else:
            merged[key] = user[key]
    return merged


def save_settings(settings):
    """Persist settings to disk. Returns True on success."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except OSError as e:
        print(f"Could not save settings: {e}")
        return False
