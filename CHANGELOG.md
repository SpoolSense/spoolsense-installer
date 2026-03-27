# Changelog

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
