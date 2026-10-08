# JustATuner — build, CI and release

*PyInstaller builds and the macOS signing story, the release process, the GitHub Actions workflow, and where settings live. Companion to CLAUDE.md; same rules, same voice. Edited in the same commit as the code it describes.*

## Building Executables

```bash
# Build for current platform (Win/Linux: single binary, macOS: .app bundle)
python build.py

# Clean and rebuild
python build.py --clean
```

PyInstaller picks up the `tuner/`, `exerciser/`, and `audio_utils.py` packages via the import graph from `main.py` — no `--add-data` needed for source. Pillow's native libraries get bundled automatically (~5–10 MB).

**GPU tuner renderer**: `build.py` adds `--hidden-import tuner_render` only when that extension is importable, so a *local* `python build.py` bundles the GPU renderer only if you've built and installed it first:

```bash
pip install maturin
python -m maturin build --release --manifest-path tuner_renderer/Cargo.toml
pip install --find-links tuner_renderer/target/wheels tuner_render
```

CI does this on the Windows and Linux runners (Rust via `dtolnay/rust-toolchain@stable`); the macOS runner skips it because macOS is canvas-only (see Per-Platform Constraints). Without the extension the build is canvas-only and `tuner/view.py` falls back at runtime — which is exactly how v1.0.0 silently shipped CPU-only.

**macOS microphone permission**: on macOS the build runs `_patch_macos_plist()` after PyInstaller, injecting `NSMicrophoneUsageDescription` into `dist/JustATuner.app/Contents/Info.plist`. macOS *silently* denies mic access to any app that doesn't declare it — the tuner wheels never move and the drone analyzer sees no input — and PyInstaller doesn't add the key. This mirrors SSC's `build.py`; the SSC extraction originally dropped the step (restored on `beta`).

The key alone is **not sufficient**: PyInstaller ad-hoc signs the bundle during build, and Info.plist is sealed into that signature. Patching the plist afterwards breaks the seal, and TCC refuses to show the permission prompt for an app whose signature doesn't validate — same silent-denial symptom, mic key present. v1.1.0 and v1.1.1 shipped this way. `_resign_macos_app()` therefore re-signs ad-hoc (`codesign --force --deep --sign -`) after the patch. Packaging matters too: CI zips the `.app` with `ditto -c -k --keepParent`, because `zip -r` follows the bundle's Frameworks↔Resources symlinks and stores them as duplicate files, breaking the resource seal on extraction. CI verifies all of it — `plutil -extract` for the key, `codesign --verify --deep --strict` on the built app, and again on an unzipped copy of the final artifact.

## Release Process

```bash
# 1. Bump version in config.py and installer.iss
# 2. Write release_notes_vX.Y.Z.md
# 3. Commit on beta and push
git push origin beta

# 4. Merge beta into main
git checkout main
git pull --ff-only
git merge --no-ff beta -m "Merge beta into main: vX.Y.Z release"
git push origin main

# 5. Create the release — triggers CI on the `release` event, which
#    attaches all three platform binaries to the release page
gh release create vX.Y.Z --target main --title "JustATuner vX.Y.Z" \
    --notes-file release_notes_vX.Y.Z.md

# 6. Watch the release-event run (not the push runs) and confirm all
#    three assets landed; the release page is live before CI finishes.
gh run list --limit 4 --json databaseId,event,status,displayTitle
gh run watch <release run id> --exit-status --interval 30
gh release view vX.Y.Z --json assets --jq '.assets[] | "\(.name) \(.size)"'
```

Expect roughly 36 MB for the Windows installer, 22 MB for the macOS zip (a ~70 MB zip means `zip -r` crept back in and the signature seal is broken), and 53 MB for the Linux binary. Then `git checkout beta` so the next change does not land on `main`, and update the shipped-version entry in the `TODO.md` ledger.

## CI/CD (GitHub Actions)

Single workflow at `.github/workflows/build.yml`. Three matrix entries:

- **`windows-latest`** — Python 3.11, `pip install -r requirements.txt`, `python build.py`, then Inno Setup (`choco install innosetup`) wraps `dist\JustATuner.exe` into `JustATuner-Windows-Setup-{APP_VERSION}.exe`. Only the installer is published; the bare `.exe` is not.
- **`macos-latest`** — Apple Silicon. Same Python install, `python build.py` produces `dist/JustATuner.app`, packaged to `JustATuner-macOS.zip` with `ditto -c -k --keepParent` (preserves the bundle's internal symlinks; `zip -r` would break the code-signature seal). CI verifies the mic key and the code signature, including on an unzipped copy of the final artifact.
- **`ubuntu-latest`** — `apt-get install libportaudio2`, then build, rename to `JustATuner-Linux`.

Before the PyInstaller step, the Windows and Linux runners install the Rust toolchain (`dtolnay/rust-toolchain@stable`) and `maturin build` the `tuner_renderer/` crate, then `pip install` the resulting `tuner_render` wheel so `build.py` bundles the GPU strobe renderer. Adds a Rust compile (~1–2 min/runner) to those builds. The macOS runner skips the Rust steps entirely — macOS is canvas-only (see Per-Platform Constraints).

Triggers: push to `main` or `beta`, release `created`, manual `workflow_dispatch`. On release events, the `softprops/action-gh-release@v2` step attaches each platform's artifact to the release page (bumped from `@v1`, which ran on the soon-to-be-removed Node 20).

Since 2026-10-06 the build job is preceded by a **`lint`** job (`ruff check .`, config in `ruff.toml`) and a **`test`** job running `tools/run_tests.py` on windows-latest, macos-latest and ubuntu-latest (under `xvfb-run`); `build` has `needs: [lint, test]` and `fail-fast: false`. The Windows and Linux build jobs run `test_gpu_tuner` and `test_tuner_canvas` with the freshly built wheel (runners have a software adapter or no Vulkan, so that exercises the fallback to canvas for real). After PyInstaller each build job runs the frozen binary with **`--selftest`** against an isolated `JUSTATUNER_CONFIG_DIR`. The Windows build job then installs the Inno Setup installer silently, runs the installed copy's `--selftest`, checks the Start Menu shortcut, uninstalls silently, and asserts the user's `%APPDATA%\JustATuner` folder survived. The macOS build job runs **`--tour all`** twice (light, then dark via `defaults write` + the `osascript` appearance switch + `--appearance dark`) and uploads both as the `mac-tour` artifact with `continue-on-error`. Look at those pictures after a Mac-affecting change; they are the only eyes on the Mac. First run (2026-10-06): the canvas tuner lit A4 IN TUNE on real Mac Tk, the dark run took (Tuner Settings mean brightness 129 → 43, latency dialog 107 → 43), and the pictures found the blank Aqua swatches and the clipped drone status row (see the traps). The runner has a silent input device, so the "tuner-no-mic" stop shows a running tuner there; the no-mic error itself is gated in `test_tuner_canvas` pass 0. Blind spots no runner reaches: the mic permission prompt itself, Retina scaling, display scaling above 100 % on Windows, real audio devices, Gatekeeper's first launch.

## Config File Location

User settings live in `app_settings.json` at:

| Platform | Location |
|----------|----------|
| Windows | `%APPDATA%\JustATuner\` |
| macOS | `~/Library/Application Support/JustATuner/` |
| Linux | `$XDG_CONFIG_HOME/JustATuner/` (or `~/.config/JustATuner/`) |

Schema lives in `config.py`'s `DEFAULT_SETTINGS`. Anything read at runtime MUST exist in `DEFAULT_SETTINGS` — the merge in `load_settings` only preserves keys that already appear in the defaults, so runtime-only keys silently disappear on next launch.

Top-level keys: `tuner_settings` (dict), `exerciser_settings` (dict), `audio_input_device` (int or None — cached PortAudio index), `audio_input_device_name` (str or None — the real persisted choice, see Input device by name), `active_tab` (str — "tuner" or "exerciser").
