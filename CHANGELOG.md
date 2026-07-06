# Changelog

## [1.4.0] - 2026-07-06

### Added
- **Preflight checks** — mode-aware host verification (esptool/NVS generator/GitHub/serial-group for scanner installs; git/venv-capability/systemd/writable paths for middleware) runs right after mode selection, aborting with the exact fix command before the user answers any questions.
- **MQTT device-ID discovery** — the installer listens ~5s for the scanner's retained `spoolsense/<id>/availability`/`tag/state` topics and proposes real device IDs per scanner (labeled by lane/toolhead); `YOUR_DEVICE_ID` placeholders only remain when nothing is found or the user skips. Best-effort — broker problems degrade to the old flow.
- `RELEASING.md` release checklist; stale-bot window lengthened with `accepted`/`tracking` label exemptions (five accepted issues were previously stale-closed unimplemented).
- **All firmware v1.7.x NVS keys are now provisionable** — WiFi keep-awake, low-spool grams, Bambu dashboard, PrusaLink (URL + API key), and Snapmaker U1 (channel 0-3), gated behind feature questions so the default flow barely grows. Previously these were only settable via the scanner's AP-mode web UI.
- **`--firmware-version X.Y.Z`** — flash a specific scanner release instead of always trusting `releases/latest`; installs become reproducible.
- **SHA256 verification of firmware downloads** — assets are checked against their `.sha256` sidecar when the release publishes one, failing closed on mismatch. (Scanner releases don't ship sidecars yet; verification activates automatically when they do.)
- **pip-installable** — `pyproject.toml` with a `spoolsense-install` console entry point and pinned-minimum deps.
- **Config backups** — `config.yaml` and `moonraker.conf` get a `.bak` copy before the installer modifies them.

### Fixed
- **config.yaml generated with `yaml.safe_dump`** — passwords containing quotes/backslashes/`#` no longer corrupt the generated config (prompt validators remain as defense in depth).
- URL validation rewritten on `urllib.parse` — bracketed IPv6 hosts accepted, malformed ports rejected consistently.
- The multi-device port-selection prompt aborts cleanly on non-interactive stdin instead of looping forever; scanner install artifacts (including the credentials-bearing NVS binary) now use a private temp dir removed on exit.

### Changed
- **Virtualenv everywhere (#21)** — middleware deps install into `~/SpoolSense/.venv` (systemd unit runs the venv python), the installer bootstraps its own venv, and `--break-system-packages` is gone. The `[update_manager spoolsense]` entry now includes `virtualenv`/`requirements` so Moonraker updates deps alongside the repo.
- Library modules raise a typed `InstallerError` instead of calling `sys.exit()` — failures are testable and cleanup runs; the CLI entry point owns process exit.
- The board prompt is generated from the single `BOARDS` table and the Moonraker `[spoolman]` block from one helper (previously three hand-synced copies).

---

## [1.3.0] - 2026-07-05

### Added
- **Happy Hare MMU setup type** (middleware #83) — new "Happy Hare MMU" option generates the `happy_hare_stage` scanner action and `happy_hare:` config block (enabled + printer_name), requires a Spoolman URL, and creates the `spool.mmu_gate` (integer) and `spool.printer_name` (text) extra fields the middleware PATCHes at bind time. `--setup-fields --happy-hare` re-creates them standalone.
- **Moonraker `[update_manager spoolsense]` entry** (#16) — the installer offers to register the middleware with Moonraker's update manager (`channel: stable`), giving users a one-click update button in Mainsail/Fluidd that follows tagged releases.
- **Middleware pinned to the latest release** — fresh installs check out the latest middleware release tag instead of whatever is on branch head (only when the clone is clean; never touches local commits). `--dev` opts back into branch head.
- **Low-spool threshold prompt** — `low_spool_threshold` is now asked (default 100 g) instead of hardcoded.
- **Toolheads list for `toolhead_stage`** (#24) — shared toolchanger scanners now prompt for the toolhead list and write `toolheads:` so the mobile app picker stops falling back to defaults.
- **Web config panel option** (middleware v1.7.0) — the installer can enable the middleware's browser UI / mobile REST API (`mobile:` block, port 5001) and surfaces the URL in the summary.
- **Middleware-only installs now create Spoolman extra fields** — previously only the scanner path did, leaving middleware-only users without `nfc_id`.
- **Robust Spoolman extra-field creation** (#17, #33) — waits for Spoolman to come up (~45s budget), retries transient failures with backoff, never silently skips a field, and prints a prominent summary with copy-paste `curl` commands for anything that failed. New `--setup-fields` flag re-runs just the field creation. *(shipped earlier on `main`, previously unlogged)*
- **Klipper macros installed for every setup type** (#27, #30) — `spoolsense.cfg` (ASSIGN_SPOOL/UPDATE_TAG) is now copied for all setups, not just `toolhead_stage`; without it, automatic filament deduction never fires. `spoolman_macros.cfg` is copied for direct-toolhead setups and `toolhead_macros_example.cfg` for multi-tool setups (existing copies are never overwritten). The installer now prints PRINT_END/UPDATE_TAG guidance.
- **Honest install summary** — the final message now lists every step with its actual outcome (✓/⚠/✗) instead of always claiming "SpoolSense is installed!". Failed systemd creation, skipped config writes, unwritten Moonraker config, and pending YOUR_DEVICE_ID edits are called out explicitly.
- **CI** — GitHub Actions now runs the test suite and critical lint checks on every PR (Python 3.9 and 3.12).
- Installer version is now shown in the banner.

### Fixed
- **Chip verification fails closed** — flashing now aborts if `esptool flash-id` exits non-zero, times out, or its output can't be parsed (previously verification was silently skipped and flashing proceeded). Chip family matching is exact: selecting `esp32dev` with an ESP32-S3 connected is now rejected (substring matching previously let it through).
- **Flash timeout handled** — a hung flash now exits with guidance instead of a traceback; timeout raised from 2 to 5 minutes for 16MB boards.
- **Removed the dead `mqtt_prefix` prompt/NVS key** — the pre-built firmware's MQTT topic prefix is compile-time (`spoolsense`) and the NVS key was never read; prompting for it falsely implied custom prefixes work.
- Declining the `config.yaml` overwrite prompt no longer skips systemd service creation.
- The manual systemd setup instruction no longer points at a temp file that was already deleted.
- `nvs_keys.csv` documentation regenerated to match the generator (namespace row fixed, `tft_driver` added, dead `mqtt_prefix` removed).

### Changed
- README: corrected Python requirement (3.9+, was "3.6+"), documented all four supported boards (ESP32-C3 and S3-DevKitC-1 were missing), the Config-only mode, `--setup-fields`, and the Web Flasher alternative.
- ESP32-C3 board label aligned with spoolsense.org: "ESP32-C3 SuperMini / DevKitM-1".
- pip dependency installation now streams its output instead of running silently.
- Moonraker URL default in middleware setup is now `http://localhost:7125` (was a bare `http://localhost`).
- Spoolman extra-field list synced to scanner firmware fields v2 (#36): adds `spool.active_toolhead` and `spool.nfc_link` (durable user-link marker, scanner #218); display names now match the firmware's exactly.

---

## [1.2.6] - 2026-05-09

### Added
- **ESP32-C3 board support** — `ESP32-C3-DevKitM-1 (4MB)` now selectable in the scanner board prompt. Matches the existing `esp32c3` PlatformIO env in the scanner firmware. Bootloader offset `0x0` (newer-ROM behavior, same as S3 family).

---

## [1.2.5] - 2026-04-06

### Added
- **Moonraker Spoolman config** — installer offers to add `[spoolman]` section to `moonraker.conf` when Spoolman is enabled. Required for real-time filament usage tracking on UID-only, TigerTag, and OpenSpool tags. Skips if already configured, handles missing file and permission errors gracefully. (#28)

---

## [1.2.4] - 2026-03-28

### Added
- NFC reader selection prompt (`pn5180` or `pn532`) during scanner setup. Written to NVS as `nfc_reader` string key.
- `nfc_reader` entry added to `nvs_keys.csv` documentation.
- Device ID reminder in post-flash output for all install modes.

### Fixed
- Validator for NFC reader prompt now returns error string instead of bool (was rejecting valid inputs).

---

## [1.2.3] - 2026-03-27

### Added
- Keypad and Moonraker URL prompts during scanner setup. Writes `keypad_on` and `moonraker_url` to NVS.
- Slicer integration prompt now shown for `afc_stage` users with hybrid setups (toolchanger + AFC). Explains that `publish_lane_data` enables ASSIGN_SPOOL macro watcher for direct toolheads alongside AFC lanes.

---

## [1.2.2] - 2026-03-27

### Added
- Prompts for optional hardware (16x2 I2C LCD display, status LED) during scanner setup. Answers are written to NVS (`lcd_on`, `led_on`) so the firmware enables only attached hardware on boot.

### Fixed
- Deprecated `esptool.py` replaced with `esptool`, `write_flash` with `write-flash`, `flash_id` with `flash-id` to suppress deprecation warnings.

---

## [1.2.1] - 2026-03-26

### Added
- **Klipper macro copy** — when `toolhead_stage` is selected, copies `spoolsense.cfg` to `~/printer_data/config/` and reminds the user to add `[include spoolsense.cfg]` to their printer.cfg.

---

## [1.2.0] - 2026-03-25

### Added
- Slicer integration option — installer asks whether to enable `publish_lane_data` for Orca Slicer integration. Only shown for non-AFC setups. AFC and Happy Hare users are told they already have this feature.

---

## [1.0.0] - 2026-03-21

Initial public release.

- Interactive CLI for scanner firmware + middleware setup
- Downloads latest firmware from GitHub releases
- Configures WiFi, MQTT, Spoolman, automation mode
- Writes NVS configuration for OTA-safe settings
- Creates Spoolman extra fields (nfc_id, tag_format, aspect, dry_temp, dry_time_hours)
- Supports ESP32-WROOM and ESP32-S3-Zero boards
- Installs and configures SpoolSense middleware as a systemd service
