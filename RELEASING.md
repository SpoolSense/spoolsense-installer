# Releasing the installer

The installer deploys the moment `main` moves — `install.sh` clones/pulls
`main` directly, so there is no artifact step between "merged" and "every
user's next run." Treat a release as one atomic checklist:

1. **Verify `dev`** — CI green, and a hardware pass on a Raspberry Pi:
   one fresh "Scanner + Middleware" install AND one re-run over the previous
   release (re-runs exercise migrations: venv, service unit, update_manager).
2. **Date the CHANGELOG** — change `## [X.Y.Z] - Unreleased` to today's date
   on `dev`. Bump `__version__` in `install.py` and `version` in
   `pyproject.toml` if not already done (a test enforces they match).
3. **Merge `dev` → `main`** — merge commit, no squash. `main` only ever
   receives release merges from `dev`; features never merge to `main`
   directly (that's how the 2026-06 history split happened).
4. **Tag and publish** — `git tag vX.Y.Z && git push origin vX.Y.Z`, then a
   GitHub Release with notes condensed from the CHANGELOG. Tags without
   published Releases confuse users (v1.2.5/v1.2.6 sat unpublished for
   months).
5. **Check the site** — `docs/releases/installer.md` on spoolsense.org should
   pick up the CHANGELOG (sync-changelog workflow); verify it ran.

## Watching the ecosystem

Scanner and middleware move fast; the installer must track:

- New **NVS keys** in the scanner's `ConfigurationManager.cpp` → `nvs.py` +
  `config.py` prompts + `nvs_keys.csv`.
- New **Spoolman extra fields** in the scanner's `REQUIRED_EXTRA_FIELDS`
  (SpoolmanManager.cpp, `SPOOLMAN_FIELDS_VERSION`) → `spoolman.py` — a test
  asserts exact parity, so drift fails CI once the list is updated.
- New **middleware setup types** (`VALID_ACTIONS` in middleware config.py) →
  setup prompt, `generate_config`, `fields_for_setup`, `_MACROS_BY_SETUP`.
- New **boards** in the scanner's `platformio.ini` → `constants.BOARDS`
  (single source; the prompt is generated from it).
