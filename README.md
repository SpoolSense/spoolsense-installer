<p align="center">
  <img src="https://raw.githubusercontent.com/SpoolSense/spoolsense_scanner/main/docs/spoolsense-logo.png" width="200" alt="SpoolSense">
</p>

# SpoolSense Installer

Interactive CLI installer for the [SpoolSense](https://github.com/SpoolSense) ecosystem. Sets up both the scanner firmware and the middleware in one pass.

## Quick Start

```bash
curl -sL https://raw.githubusercontent.com/SpoolSense/spoolsense-installer/main/install.sh -o /tmp/install.sh && bash /tmp/install.sh
```

## How It Works

The installer asks a series of questions (WiFi, MQTT, board type, etc.) and then:

1. **Scanner** — Downloads a pre-built firmware binary, generates a per-user NVS config partition, verifies the connected chip, and flashes both to the ESP32 via `esptool`
2. **Middleware** — Clones SpoolSense, installs Python dependencies, generates `config.yaml`, and creates a systemd service
3. **Spoolman** — Optionally creates extra fields in Spoolman (`nfc_id`, `tag_format`, `aspect`, `dry_temp`, `dry_time_hours`) needed for full tag data tracking


## Recommended Setup

Run this installer **from your printer host** (Raspberry Pi) with the ESP32 connected via USB. This installs everything in one pass — scanner firmware and middleware.

If your printer host has no free USB port:
1. Flash the scanner from your laptop (choose "Scanner only")
2. Run the installer again on the Pi (choose "Middleware only")

After installation, open `http://spoolsense.local` in your browser to retrieve your **Scanner Device ID** — you'll need this for the middleware configuration.

**Note:** SpoolSense middleware must run on the printer host.

## Supported Boards

| Board | Flash | Status |
|-------|-------|--------|
| ESP32-WROOM DevKit | 4MB | Tested |
| ESP32-S3-Zero (Waveshare) | 4MB | Tested |

Other boards: compile from source via [PlatformIO](https://github.com/SpoolSense/spoolsense_scanner).

The installer verifies the connected chip type and flash size before flashing to prevent accidental misconfiguration.

## What Gets Installed

### Scanner (ESP32)
- Pre-built firmware binary (from GitHub Releases)
- NVS config partition with your WiFi, MQTT, and Spoolman settings
- Config is stored separately from firmware — update settings without reflashing

### Middleware (Raspberry Pi)
- SpoolSense Python middleware (cloned to `~/SpoolSense`)
- Python dependencies
- Generated `config.yaml` with your settings
- systemd service (`spoolsense.service`) — starts on boot

## Requirements

- Python 3.6+
- git
- USB cable (for scanner flashing)
- Network access (to download firmware and clone repos)

## Re-running the Installer

Run the same command again to update or reconfigure. The installer will:
- Download the latest firmware release
- Warn before overwriting existing middleware config
- Reflash the scanner with new settings
