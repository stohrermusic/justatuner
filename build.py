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
        cmd.append("--windowed")
    else:
        cmd.extend(["--onefile", "--noconsole"])
    cmd.append("main.py")

    print(" ".join(cmd))
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
