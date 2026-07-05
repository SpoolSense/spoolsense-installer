<p align="center">
  <img src="https://raw.githubusercontent.com/SpoolSense/spoolsense_scanner/main/docs/spoolsense-logo.png" width="200" alt="SpoolSense">
</p>

# SpoolSense Installer

Interactive CLI installer for the [SpoolSense](https://github.com/SpoolSense) ecosystem. Sets up both the scanner firmware and the middleware in one pass.

## Quick Start

```bash
curl -sL https://raw.githubusercontent.com/SpoolSense/spoolsense-installer/main/install.sh -o /tmp/install.sh && bash /tmp/install.sh
```

Prefer a browser? You can flash the scanner firmware without installing anything using the [Web Flasher](https://spoolsense.org/installation/web-flasher/) (Chrome/Edge), then run this installer with "Middleware only" on your printer host.

## How It Works

The installer asks a series of questions (WiFi, MQTT, board type, etc.) and then:

1. **Scanner** — Downloads a pre-built firmware binary, generates a per-user NVS config partition, verifies the connected chip, and flashes both to the ESP32 via `esptool`
2. **Middleware** — Clones SpoolSense, installs Python dependencies, generates `config.yaml`, and creates a systemd service. The installer asks for your setup type and generates the appropriate scanner config:
   - **AFC shared scanner** (`afc_stage`) — one scanner for all BoxTurtle/NightOwl lanes
   - **AFC per-lane** (`afc_lane`) — one scanner per lane
   - **Toolchanger shared scanner** (`toolhead_stage`) — one scanner for all toolheads (klipper-toolchanger)
   - **Toolchanger per-toolhead** (`toolhead`) — one scanner per tool
   - **Single toolhead** (`single`) — one scanner, one extruder
   - **Happy Hare MMU** (`happy_hare_stage`) — one shared scanner; scan a spool to bind it to the currently selected MMU gate (requires Happy Hare in pull mode and Spoolman)
3. **Klipper macros** — Copies the macros your setup needs to `~/printer_data/config/`: `spoolsense.cfg` (ASSIGN_SPOOL/UPDATE_TAG, all setups), `spoolman_macros.cfg` (direct-toolhead setups), and `toolhead_macros_example.cfg` (multi-tool setups). Add `UPDATE_TAG` to your `PRINT_END` macro for automatic filament tracking.
4. **Spoolman** — Optionally creates extra fields in Spoolman (`nfc_id`, `tag_format`, `aspect`, `dry_temp`, `dry_time_hours`, plus `mmu_gate`/`printer_name` for Happy Hare) needed for full tag data tracking, and offers to add the `[spoolman]` section to `moonraker.conf`
5. **Updates** — Offers to register the middleware with Moonraker's update manager (`[update_manager spoolsense]`, stable channel) so updates show up in Mainsail/Fluidd. Fresh installs are pinned to the latest middleware release (use `--dev` for branch head).

### Install modes

- **Scanner + Middleware** — everything in one pass (recommended, run on the printer host)
- **Scanner only** — flash the ESP32 (e.g. from a laptop)
- **Middleware only** — printer-host setup without flashing (also the right choice after using the Web Flasher)
- **Config only** — for source builds: writes `spoolsense_nvs.csv`/`.bin` to the current directory so you can flash config without reflashing firmware

### Extra flags

```bash
python3 install.py --setup-fields [--spoolman-url http://spoolman.local:7912] [--happy-hare]
```

Re-creates just the required Spoolman extra fields (useful if Spoolman wasn't running during the initial install). `--happy-hare` also creates the `mmu_gate`/`printer_name` fields.

```bash
python3 install.py --dev
```

Tracks the middleware branch head instead of pinning to the latest release tag.


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
| ESP32-C3 SuperMini / DevKitM-1 | 4MB | Tested |
| ESP32-S3-DevKitC-1-N16R8 | 16MB + 8MB PSRAM | Tested |

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
- Optional slicer integration (`publish_lane_data`) — publishes spool data for Orca Slicer. AFC and Happy Hare users don't need this.
- systemd service (`spoolsense.service`) — starts on boot

## Requirements

- Python 3.9+
- git
- USB cable (for scanner flashing)
- Network access (to download firmware and clone repos)

## Re-running the Installer

Run the same command again to update or reconfigure. The installer will:
- Download the latest firmware release
- Warn before overwriting existing middleware config
- Reflash the scanner with new settings
