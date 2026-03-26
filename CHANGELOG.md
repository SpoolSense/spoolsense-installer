# Changelog

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
