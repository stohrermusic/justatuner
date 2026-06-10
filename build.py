"""Cross-platform PyInstaller build script.

Outputs:
  Windows: dist/JustATuner.exe
  macOS:   dist/JustATuner.app
  Linux:   dist/JustATuner

Each platform must run this on its own machine (no cross-compilation).
"""

import argparse
import os
import shutil
import subprocess
import sys


APP_NAME = "JustATuner"


def _patch_macos_plist():
    """Add microphone permission to the macOS .app Info.plist.

    macOS silently denies mic access to apps that don't declare
    NSMicrophoneUsageDescription in their Info.plist — the tuner wheels
    never move and the drone analyzer sees no input. PyInstaller doesn't
    add the key, so patch the built bundle. (Ported from Stohrer Sax Shop
    Companion, which has shipped this fix since v2.x.)
    """
    import plistlib

    plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
    if not os.path.exists(plist_path):
        print(f"Warning: {plist_path} not found, skipping plist patch")
        return

    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    plist["NSMicrophoneUsageDescription"] = (
        "JustATuner uses the microphone to detect pitch for tuning "
        "and to analyze intervals against the drone."
    )

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    print("  Added NSMicrophoneUsageDescription to Info.plist")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true",
                        help="Remove dist/, build/, and any .spec before building")
    args = parser.parse_args()

    repo = os.path.dirname(os.path.abspath(__file__))
    os.chdir(repo)

    if args.clean:
        for d in ("dist", "build"):
            if os.path.exists(d):
                shutil.rmtree(d)
        spec = f"{APP_NAME}.spec"
        if os.path.exists(spec):
            os.remove(spec)

    # PyInstaller picks up tuner/, exerciser/, audio_utils.py, and config.py
    # via the main.py import graph; no --add-data needed for the source.
    #
    # Per-platform flags:
    #   Windows / Linux: --onefile produces a single binary, --noconsole
    #                    suppresses the terminal window for the GUI app.
    #   macOS:           --windowed produces a .app bundle (the standard
    #                    distributable on Mac). --onefile here would
    #                    flatten it to a single binary that wouldn't run
    #                    as a regular Mac app.
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconfirm",
    ]
    if sys.platform == "darwin":
        cmd.extend([
            "--windowed",
            "--osx-bundle-identifier", "com.stohrer.justatuner",
        ])
    else:
        cmd.extend(["--onefile", "--noconsole"])

    # GPU-accelerated tuner renderer (Rust/wgpu via pyo3). Bundled only
    # when the tuner_render extension is importable at build time —
    # otherwise the app ships canvas-only and the tuner falls back at
    # runtime. Mirrors the capability check SSC's build.py uses.
    #
    # Never bundled on macOS: Tk Aqua's winfo_id() is not an NSView, so
    # wgpu can't create a surface from it (segfaults in objc_msgSend).
    # tuner/view.py refuses to import it on darwin; bundling it would
    # just be dead weight in the .app.
    if sys.platform == "darwin":
        print("  macOS: skipping tuner_render — tuner uses CPU canvas rendering")
    else:
        try:
            import tuner_render  # noqa: F401  (capability check)
            cmd.extend(["--hidden-import", "tuner_render"])
            print("  tuner_render found — including GPU strobe renderer")
        except ImportError:
            print("  tuner_render not found — tuner will use CPU canvas rendering")

    cmd.append("main.py")

    print(" ".join(cmd))
    subprocess.check_call(cmd)

    if sys.platform == "darwin":
        _patch_macos_plist()


if __name__ == "__main__":
    main()
