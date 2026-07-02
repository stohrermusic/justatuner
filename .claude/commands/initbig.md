---
description: Audit project documentation against current codebase state. Catches drift; does not restructure without explicit approval.
---

Audit whether the project documentation accurately reflects the current
codebase. Scope: `CLAUDE.md` (root, the always-loaded project entrypoint),
`README.md` (user-facing install + feature claims), and `TODO.md` (release
ledger + open work).

**Do NOT restructure** by default. JustATuner deliberately keeps a single
`CLAUDE.md` (no `CLAUDE-*.md` companion split like SSC — this app is an
order of magnitude smaller). Your job is to catch *content drift*, not
reorganize. If you think restructuring is warranted, flag it as a
recommendation and wait for explicit approval before touching structure.

## Steps

1. **Read the doc tree.**
   - `CLAUDE.md` (project entrypoint, always loaded by Claude Code).
   - `README.md` (install steps per platform, feature bullets, From Source).
   - `TODO.md` (shipped-release ledger at top, then iterative/stretch work).

2. **Check claimed facts against reality.** Common drift sources for
   this project:
   - **`APP_VERSION`**: grep `config.py` and compare against the
     build-comment example in `installer.iss` (`iscc /DAppVersion=X.Y.Z`)
     and the newest `release_notes_vX.Y.Z.md` — all three should agree on
     the latest released version.
   - **The macOS canvas-only gate (three layers)** — this is the one that
     crashes Macs at launch if it regresses. Verify all three still hold:
     `tuner/view.py` forces `_HAS_GPU_RENDERER = False` on darwin (never
     imports `tuner_render`), `build.py` skips the `--hidden-import` on
     darwin, and `.github/workflows/build.yml` skips the Rust/maturin
     steps on the macOS runner. CLAUDE.md's Per-Platform Constraints
     section must keep describing all three.
   - **`::tk::mac::Quit`** — `main.py` must still route it to `_on_close`
     on darwin (Cmd-Q settings save). Documented in Per-Platform
     Constraints.
   - **Tab menus** — which views expose `populate_menu()` (currently both:
     tuner contributes Tuner > Settings..., exerciser contributes Drone /
     Exerciser Options) vs what the "Tab-specific menus" pattern and the
     "Tab-Specific Menu" section claim.
   - **Visualizer modes** — `_VALID_MODES` in `ExerciserView.__init__` vs
     the six-mode table in CLAUDE.md and the README/release-notes bullets.
   - **Garden constants** — the values CLAUDE.md and TODO.md quote
     (`GARDEN_DEPTH_DECAY_*` 0.78/0.62/0.55, `GARDEN_MAX_DEPTH` 4,
     `GARDEN_BRANCH_FAN` 28°, etc.) vs the constants in
     `exerciser/view.py`. The garden is the most-tuned subsystem; numbers
     drift.
   - **Sample-drone interpolation** — currently Catmull-Rom cubic (4-tap)
     in `_render_sample_voices`; older docs/notes said linear. If the
     interpolation changes again (phase vocoder is a stretch goal), update
     the engine section AND the known-limitations wording used in release
     notes.
   - **`DEFAULT_SETTINGS` schema** — top-level keys in `config.py` vs the
     Config File Location section's key list. Anything read at runtime
     must exist in the defaults (the merge drops unknown keys) — that
     warning must stay.
   - **CI workflow** — matrix entries, action versions, the macOS Rust
     skip, and what each platform publishes, vs the CI/CD section.
   - **Test suite** — CLAUDE.md says "no test suite yet". If `tools/` or
     tests appear, replace that claim with real run instructions.

3. **Check for undocumented recent work.** `git log --oneline -25` for
   commits since the last doc refresh. Ask:
   - New modules, menus, settings keys, visualizer modes, or build steps
     the docs haven't caught up to?
   - Anything contradicting an architectural claim in CLAUDE.md?
   - TODO.md's release ledger — does the newest shipped section match the
     newest git tag and release notes file?

4. **Memory is out of scope.** This project's Claude memory lives OUTSIDE
   the repo (in `C:\Users\abadc\.claude\projects\C--code\memory\`, indexed
   by its `MEMORY.md` — Matt works from `C:\code`, so memory accrues under
   that project key). Do NOT edit memory content during a doc audit. You
   may *note* if a memory entry names a symbol/file that no longer exists,
   as a heads-up for the next session.

5. **Propose targeted edits.** Show the planned changes in diff-like form
   *before* applying. Do not change structure (split files, rename
   sections, add companion docs) without explicit consent.

6. **Report.** Summarize: what drifted, what was updated, what was noticed
   but intentionally left alone (with reasoning), anything recommended but
   not changed.

## Do NOT touch

- **Published release notes** (`release_notes_v*.md` for releases that are
  already on GitHub) — frozen historical records. A typo fix is fine; do
  not rewrite claims retroactively. New facts go in the NEXT release's
  notes.
- **Auto-memory content** (external; own lifecycle). See step 4.
- Sections describing deliberate choices still known to be accurate —
  don't "improve" these for stylistic reasons. Examples:
  - macOS is canvas-only by design (winfo_id is not an NSView; a real
    NSView still wouldn't work — CAMetalLayer would cover the whole
    window). Do not "fix" by re-enabling GPU on darwin.
  - Apple Silicon only on macOS (sounddevice Intel wheel unreliability).
  - No code signing on any platform ($100/yr).
  - Tuner files duplicated from SSC **by design** — do not deduplicate or
    import across repos; port fixes manually when relevant.
  - The `AppId` GUID in `installer.iss` is frozen forever.
- Frozen historical claims that are part of the project's record (e.g.
  "v1.0.0 shipped 2026-06-04", the v1.0.0 extraction-regression stories).

## Trigger conditions for running this

- After a meaningful feature pass or hygiene pass ships.
- When Matt says "let's update the docs" or asks for an audit.
- As a final check before claiming a body of work is complete (e.g.
  right before the merge-to-main step of a release).
- When recent commits touched architecture, the build/CI pipeline, or
  platform gates — likely doc drift to verify.
