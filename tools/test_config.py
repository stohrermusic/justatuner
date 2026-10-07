"""Settings, input-device and logging gates for config.py — no display, no audio.

Standalone script (not pytest): prints PASS/FAIL per check and exits 1 on
any failure. Runs against a temp profile via JUSTATUNER_CONFIG_DIR, which
must be set before config is imported (SETTINGS_FILE/LOG_FILE are module
constants). sounddevice is never called: get_input_devices is monkeypatched,
and its own filter test swaps in a fake sounddevice module.
"""
import copy
import json
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="jat_test_config_")
os.environ["JUSTATUNER_CONFIG_DIR"] = TMP

import config  # noqa: E402

passed = 0
failed = 0


def test(name, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


cap = Capture()
logging.getLogger().addHandler(cap)  # also stops logging.warning from calling basicConfig
DEFAULTS_SNAPSHOT = copy.deepcopy(config.DEFAULT_SETTINGS)


def write_raw(data):
    with open(config.SETTINGS_FILE, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def safe_load():
    """(settings, exception) — load_settings must never raise."""
    try:
        return config.load_settings(), None
    except Exception as e:  # noqa: BLE001
        return None, e


def clear_file():
    if os.path.isfile(config.SETTINGS_FILE):
        os.remove(config.SETTINGS_FILE)


# ============================================
print("\n--- Config dir override ---")
test(f"get_config_dir() == temp dir {TMP}", config.get_config_dir() == TMP)
test("SETTINGS_FILE is app_settings.json inside the temp dir",
     config.SETTINGS_FILE == os.path.join(TMP, "app_settings.json"))
test("LOG_FILE is app.log inside the temp dir", config.LOG_FILE == os.path.join(TMP, "app.log"))
test("override directory exists", os.path.isdir(TMP))

# ============================================
print("\n--- load_settings ---")
clear_file()
s, err = safe_load()
test("no file: returns DEFAULT_SETTINGS", err is None and s == config.DEFAULT_SETTINGS)
s["tuner_settings"]["stripe_color"] = "#FFFFFF"
s["active_tab"] = "exerciser"
test("no file: mutating the result leaves DEFAULT_SETTINGS unchanged (deep copy)",
     config.DEFAULT_SETTINGS == DEFAULTS_SNAPSHOT)

old = {  # v1.1.2 shape: no audio_input_device_name, last_sample_path, show_fps
    "tuner_settings": {k: v for k, v in DEFAULTS_SNAPSHOT["tuner_settings"].items()
                       if k != "show_fps"} | {"stripe_color": "#FF0000", "reference_pitch": 442.0},
    "exerciser_settings": {"root_note": 5, "drone_type": "sine"},
    "audio_input_device": 3,
    "active_tab": "exerciser",
}
write_raw(json.dumps(old))
s, err = safe_load()
ok = err is None
test("v1.1.2 file: every top-level default key present",
     ok and set(s) == set(DEFAULTS_SNAPSHOT))
test("v1.1.2 file: every nested default key present",
     ok and all(set(s[k]) == set(DEFAULTS_SNAPSHOT[k]) for k in ("tuner_settings", "exerciser_settings")))
test("v1.1.2 file: stored stripe_color #FF0000 and reference_pitch 442.0 win",
     ok and s["tuner_settings"]["stripe_color"] == "#FF0000" and s["tuner_settings"]["reference_pitch"] == 442.0)
test("v1.1.2 file: stored root_note 5, drone_type sine, audio_input_device 3, active_tab exerciser win",
     ok and s["exerciser_settings"]["root_note"] == 5 and s["exerciser_settings"]["drone_type"] == "sine"
     and s["audio_input_device"] == 3 and s["active_tab"] == "exerciser")
test("v1.1.2 file: missing show_fps=False, last_sample_path=None, audio_input_device_name=None defaulted",
     ok and s["tuner_settings"]["show_fps"] is False and s["exerciser_settings"]["last_sample_path"] is None
     and s["audio_input_device_name"] is None)

# Current behaviour: the merge keeps only keys that exist in DEFAULT_SETTINGS.
write_raw(json.dumps({"bogus_top": 1, "tuner_settings": {"bogus_nested": 2, "sensitivity": 70}}))
s, err = safe_load()
test("unknown top-level key 'bogus_top' dropped (documented behaviour)", err is None and "bogus_top" not in s)
test("unknown tuner_settings key 'bogus_nested' dropped, known sensitivity 70 kept",
     err is None and "bogus_nested" not in s["tuner_settings"] and s["tuner_settings"]["sensitivity"] == 70)

write_raw(json.dumps({"active_tab": None, "exerciser_settings": None, "tuner_settings": 5}))
s, err = safe_load()
test("top-level None active_tab -> default 'tuner'", err is None and s["active_tab"] == "tuner")
test("top-level None exerciser_settings -> default dict",
     err is None and s["exerciser_settings"] == DEFAULTS_SNAPSHOT["exerciser_settings"])
test("tuner_settings decoded to int 5 -> default dict",
     err is None and s["tuner_settings"] == DEFAULTS_SNAPSHOT["tuner_settings"])

# Current behaviour: None inside a nested dict is a stored value and survives.
write_raw(json.dumps({"tuner_settings": {"stripe_color": None, "sensitivity": None}}))
s, err = safe_load()
test("nested None stripe_color/sensitivity kept as None (documented behaviour)",
     err is None and s["tuner_settings"]["stripe_color"] is None and s["tuner_settings"]["sensitivity"] is None)

for label, raw in [("corrupt JSON '{\"tuner_settings\": {'", '{"tuner_settings": {'),
                   ("JSON list [1, 2, 3]", "[1, 2, 3]"),
                   ("empty file", b""),
                   ("invalid UTF-8 bytes b'\\xff\\xfe\\x00garbage'", b"\xff\xfe\x00garbage")]:
    write_raw(raw)
    s, err = safe_load()
    test(f"{label}: defaults, no exception (got {type(err).__name__ if err else 'none'})",
         err is None and s == DEFAULTS_SNAPSHOT)
clear_file()

saved_path = config.SETTINGS_FILE
config.SETTINGS_FILE = os.path.join(TMP, "a_directory")
os.makedirs(config.SETTINGS_FILE, exist_ok=True)
s, err = safe_load()
test(f"unreadable settings path (a directory): defaults, no exception "
     f"(got {type(err).__name__ if err else 'none'})",
     err is None and s == DEFAULTS_SNAPSHOT)

# ============================================
print("\n--- save_settings ---")
cap.messages.clear()
result = config.save_settings(DEFAULTS_SNAPSHOT)
test("save to a directory path returns False", result is False)
test("save failure logged 'Could not save settings'",
     any("Could not save settings" in m for m in cap.messages))
config.SETTINGS_FILE = saved_path


def changed(v):
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v + 1
    if isinstance(v, str):
        return v + "_x"
    return "set"  # None defaults


every = {k: ({sk: changed(sv) for sk, sv in v.items()} if isinstance(v, dict) else changed(v))
         for k, v in DEFAULTS_SNAPSHOT.items()}
leaves_differ = all(
    (all(every[k][sk] != sv for sk, sv in v.items()) if isinstance(v, dict) else every[k] != v)
    for k, v in DEFAULTS_SNAPSHOT.items())
test("round-trip fixture changes every default leaf", leaves_differ)
test("save_settings returns True", config.save_settings(every) is True)
s, err = safe_load()
test("load_settings reads every changed value back equal", err is None and s == every)
with open(config.SETTINGS_FILE, encoding="utf-8") as f:
    test("saved file is valid JSON", json.load(f) == every)
clear_file()

# ============================================
print("\n--- resolve_input_device / remember_input_device ---")
DEVICES = [(1, "Microphone (Realtek High Definition Audio)"), (3, "USB Audio CODEC"),
           (5, "Headset Microphone (Jabra Evolve2 65 Mono)")]
real_get = config.get_input_devices
config.get_input_devices = lambda: list(DEVICES)

st = {"audio_input_device": None, "audio_input_device_name": "USB Audio CODEC"}
test("exact name 'USB Audio CODEC' -> 3", config.resolve_input_device(st) == 3)
test("exact match caches index 3", st["audio_input_device"] == 3)

st = {"audio_input_device": None, "audio_input_device_name": "Headset Microphone (Jabra Evolve2 65 Stereo)"}
test("prefix match (same first 30 chars, different tail) -> 5", config.resolve_input_device(st) == 5)
test("prefix match caches index 5", st["audio_input_device"] == 5)

st = {"audio_input_device": 3, "audio_input_device_name": "AirPods Pro"}
test("absent name 'AirPods Pro' -> None", config.resolve_input_device(st) is None)
test("absent name clears cached index 3 -> None", st["audio_input_device"] is None)
test("absent name keeps 'AirPods Pro'", st["audio_input_device_name"] == "AirPods Pro")
config.get_input_devices = lambda: list(DEVICES) + [(8, "AirPods Pro")]
test("device comes back at index 8 -> resolves to 8", config.resolve_input_device(st) == 8)
config.get_input_devices = lambda: list(DEVICES)

st = {"audio_input_device": 3, "audio_input_device_name": None}
test("legacy index 3 -> 3", config.resolve_input_device(st) == 3)
test("legacy index 3 adopts name 'USB Audio CODEC'", st["audio_input_device_name"] == "USB Audio CODEC")
st = {"audio_input_device": 7, "audio_input_device_name": None}
test("legacy index 7 (gone) -> None", config.resolve_input_device(st) is None)
test("legacy index 7 cleared to None", st["audio_input_device"] is None and st["audio_input_device_name"] is None)
st = {"audio_input_device": None, "audio_input_device_name": None}
test("no name, no index -> None", config.resolve_input_device(st) is None)

st = {}
config.remember_input_device(st, 5)
test("remember 5 stores index 5 + Jabra name",
     st == {"audio_input_device": 5, "audio_input_device_name": "Headset Microphone (Jabra Evolve2 65 Mono)"})
config.remember_input_device(st, None)
test("remember None clears both", st == {"audio_input_device": None, "audio_input_device_name": None})
config.remember_input_device(st, 9)
test("remember 9 (not listed) stores index 9, name None",
     st == {"audio_input_device": 9, "audio_input_device_name": None})
config.get_input_devices = real_get

# ============================================
print("\n--- get_input_devices filtering (fake sounddevice) ---")


def dev(name, ins, outs=2):
    return {"name": name, "max_input_channels": ins, "max_output_channels": outs,
            "hostapi": 0, "default_samplerate": 44100.0}


FAKE = [dev("Speakers (Realtek High Definition Audio)", 0),      # 0 output-only
        dev("Microphone (Realtek High Definition Audio)", 2),    # 1 kept
        dev("Headset (Bluetooth Hands-Free AG Audio)", 1),       # 2 bluetooth
        dev("Headset Hands-Free Microphone", 1),                 # 3 hands-free
        dev("Input (@System32\\drivers\\bthhfenum.sys,#2;%1)", 1),  # 4 BTHHFENUM
        dev("Microsoft Sound Mapper - Input", 2),                # 5 sound mapper
        dev("Primary Sound Capture Driver", 2),                  # 6 primary sound
        dev("Microphone (Realtek High Defini", 2),               # 7 dup of 1 (first 30)
        dev("  USB Audio CODEC  ", 1)]                           # 8 kept, stripped
real_sd = sys.modules.get("sounddevice")
sys.modules["sounddevice"] = types.SimpleNamespace(query_devices=lambda: FAKE)
got = config.get_input_devices()
test(f"filtered list == [(1, Realtek mic), (8, 'USB Audio CODEC')] (got {got})",
     got == [(1, "Microphone (Realtek High Definition Audio)"), (8, "USB Audio CODEC")])
idxs = [i for i, _ in got]
test("output-only index 0 dropped", 0 not in idxs)
test("Bluetooth/Hands-Free/BTHHFENUM/Sound Mapper/Primary Sound (2-6) dropped",
     not any(i in idxs for i in (2, 3, 4, 5, 6)))
test("30-char duplicate index 7 dropped, first index 1 kept", 7 not in idxs and 1 in idxs)
test("'  USB Audio CODEC  ' stripped", (8, "USB Audio CODEC") in got)


def boom():
    raise RuntimeError("PortAudio not initialized")


cap.messages.clear()
sys.modules["sounddevice"] = types.SimpleNamespace(query_devices=boom)
try:
    got, err = config.get_input_devices(), None
except Exception as e:  # noqa: BLE001
    got, err = None, e
test("query_devices raising -> [] with no exception", err is None and got == [])
test("enumeration failure logged", any("Could not enumerate input devices" in m for m in cap.messages))
if real_sd is not None:
    sys.modules["sounddevice"] = real_sd
else:
    del sys.modules["sounddevice"]

# ============================================
print("\n--- setup_logging ---")
root = logging.getLogger()
path1 = config.setup_logging()
path2 = config.setup_logging()
rfh = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
test("setup_logging twice -> exactly 1 RotatingFileHandler", len(rfh) == 1)
test("handler writes to LOG_FILE inside the temp dir",
     len(rfh) == 1 and rfh[0].baseFilename == os.path.abspath(os.path.join(TMP, "app.log")))
test("both calls return LOG_FILE", path1 == path2 == config.LOG_FILE)
test("root logger level is WARNING", root.level == logging.WARNING)
test("get_log_file() == LOG_FILE", config.get_log_file() == config.LOG_FILE)
for h in rfh:
    h.flush()
with open(config.LOG_FILE, encoding="utf-8") as f:
    test(f"app.log contains the 'App starting' line for version {config.APP_VERSION}",
         f"App starting — version {config.APP_VERSION}" in f.read())
for h in rfh:
    root.removeHandler(h)
    h.close()
shutil.rmtree(TMP, ignore_errors=True)

# ============================================
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    print("FAILURES")
    sys.exit(1)
print("ALL TESTS PASSED")
