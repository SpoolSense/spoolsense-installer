#!/usr/bin/env python3
__version__ = "1.2.5"
"""
SpoolSense Installer — interactive CLI for scanner firmware + middleware setup.

Recommended: Run from your printer host (Raspberry Pi) with the ESP32 connected
via USB. This installs everything in one pass.

If your printer host has no free USB port, flash the scanner from a laptop
(choose "Scanner only"), then run this installer again on the Pi to install
the middleware (choose "Middleware only").

Note: SpoolSense middleware must run on the printer host.
"""

import os
import sys
import tempfile

from spoolsense_installer.constants import C, BOARDS, MIDDLEWARE_DIR
from spoolsense_installer.ui import ask_choice, ask_yesno
from spoolsense_installer.config import collect_scanner_config, collect_middleware_config, collect_middleware_mqtt_settings
from spoolsense_installer.nvs import generate_nvs_csv, generate_nvs_bin
from spoolsense_installer.firmware import fetch_latest_release, download_asset, detect_usb_port, verify_flash, flash_firmware
from spoolsense_installer.middleware import generate_config as generate_middleware_config, install as install_middleware
from spoolsense_installer.spoolman import setup_extra_fields, setup_moonraker_spoolman


# ── Install flow orchestration ───────────────────────────────────────────────

def run_scanner_install(scanner_config: dict) -> None:
    """Download firmware, generate NVS, flash the ESP32."""
    board_key = scanner_config["board"]
    _, _, fw_suffix, _, _ = BOARDS[board_key]

    port = detect_usb_port()
    verify_flash(port, board_key)

    release = fetch_latest_release()
    firmware_bin = download_asset(release, suffix=fw_suffix)
    bootloader_bin = download_asset(release, name=f"bootloader_{fw_suffix}.bin")
    partitions_bin = download_asset(release, name=f"partitions_{fw_suffix}.bin")

    nvs_csv = generate_nvs_csv(scanner_config)
    nvs_path = os.path.join(tempfile.gettempdir(), "spoolsense_nvs.bin")
    generate_nvs_bin(nvs_csv, nvs_path)

    # Write temp files for bootloader/partitions (flash_firmware needs file paths)
    temp_paths = []
    boot_path = os.path.join(tempfile.gettempdir(), f"bootloader_{fw_suffix}.bin")
    part_path = os.path.join(tempfile.gettempdir(), f"partitions_{fw_suffix}.bin")
    with open(boot_path, "wb") as f:
        f.write(bootloader_bin)
    with open(part_path, "wb") as f:
        f.write(partitions_bin)
    temp_paths.extend([boot_path, part_path, nvs_path])

    try:
        flash_firmware(port, board_key, firmware_bin, nvs_path, part_path, boot_path)
    finally:
        for p in temp_paths:
            if os.path.exists(p):
                os.unlink(p)

    # Setup Spoolman extra fields if enabled
    spoolman_url = scanner_config.get("spoolman_url") or ""
    if scanner_config.get("spoolman_on") and spoolman_url:
        print(f"\n{C.CYAN}── Spoolman Setup ─────────────────────{C.RESET}\n")
        setup_extra_fields(spoolman_url)


def run_config_only(scanner_config: dict) -> None:
    """Generate NVS binary only — for users who compile from source."""
    nvs_csv = generate_nvs_csv(scanner_config)

    # Save to current directory for easy access
    out_dir = os.getcwd()
    csv_path = os.path.join(out_dir, "spoolsense_nvs.csv")
    bin_path = os.path.join(out_dir, "spoolsense_nvs.bin")

    with open(csv_path, "w") as f:
        f.write(nvs_csv)

    generate_nvs_bin(nvs_csv, bin_path)

    print(f"\n  {C.GREEN}✓{C.RESET} NVS config generated:")
    print(f"    CSV: {csv_path}")
    print(f"    BIN: {bin_path}")
    print(f"\n  Flash with: esptool write-flash 0x9000 {bin_path}")


def run_middleware_install(scanner_config: dict, middleware_config: dict) -> None:
    """Generate middleware config, install repo, create systemd service."""
    config_yaml = generate_middleware_config(scanner_config, middleware_config)
    install_middleware(config_yaml)

    # Copy Klipper macro if toolchanger setup
    setup_type = middleware_config.get("setup_type", "")
    if setup_type != "toolhead_stage":
        return
    macro_src = os.path.join(MIDDLEWARE_DIR, "middleware", "klipper", "spoolsense.cfg")
    macro_dst = os.path.expanduser("~/printer_data/config/spoolsense.cfg")
    if not os.path.exists(macro_src):
        return
    try:
        import shutil
        shutil.copy2(macro_src, macro_dst)
        print(f"  {C.GREEN}✓{C.RESET} Copied spoolsense.cfg to {macro_dst}")
        print(f"  {C.YELLOW}Note:{C.RESET} Add [include spoolsense.cfg] to your printer.cfg")
    except Exception as e:
        print(f"  {C.YELLOW}!{C.RESET} Could not copy Klipper macro: {e}")


def print_completion_message(mode: str, scanner_config: dict) -> None:
    """Print the final success message with next steps."""
    print(f"\n{C.GREEN}{'═' * 42}")
    print(f"  SpoolSense is installed!")
    print(f"{'═' * 42}{C.RESET}\n")

    if mode in ("both", "scanner"):
        hostname = scanner_config.get("hostname", "spoolsense")
        print(f"  Scanner:    http://{hostname}.local")
    if mode in ("both", "middleware"):
        print(f"  Middleware:  systemctl status spoolsense")
        print(f"  Config:     {MIDDLEWARE_DIR}/config.yaml")
    if mode == "config":
        print(f"  NVS binary: spoolsense_nvs.bin (flash with esptool)")

    print(f"\n{C.RED}{C.BOLD}  ⚠  IMPORTANT: Replace YOUR_DEVICE_ID in the middleware config")
    print(f"     with your scanner's device ID.")
    print(f"     Find it at http://spoolsense.local (shown on landing page).{C.RESET}\n")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    if sys.version_info < (3, 9):
        print(f"\n  {C.RED}✗ Python 3.9 or newer is required.{C.RESET}")
        print(f"    You have: Python {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)

    print(f"""{C.CYAN}{C.BOLD}
  ____                    _ ____
 / ___| _ __   ___   ___ | / ___|  ___ _ __  ___  ___
 \\___ \\| '_ \\ / _ \\ / _ \\| \\___ \\ / _ \\ '_ \\/ __|/ _ \\
  ___) | |_) | (_) | (_) | |___) |  __/ | | \\__ \\  __/
 |____/| .__/ \\___/ \\___/|_|____/ \\___|_| |_|___/\\___|
       |_|{C.RESET}
{C.DIM}          NFC Filament Intelligence for 3D Printers{C.RESET}
    """)

    print(f"  {C.GREEN}RECOMMENDED:{C.RESET} Run from your printer host (Raspberry Pi)")
    print("  with the ESP32 connected via USB. Installs everything")
    print("  in one pass.\n")
    print(f"  No free USB on the Pi? Flash the scanner from a laptop")
    print("  (Scanner only), then run again on the Pi (Middleware only).\n")
    print(f"  {C.YELLOW}Note:{C.RESET} SpoolSense middleware must run on the printer host.\n")

    mode = ask_choice("What do you want to install?", {
        "both": "Scanner + Middleware (recommended)",
        "scanner": "Scanner only",
        "middleware": "Middleware only",
        "config": f"{C.RED}Config only (source builds){C.RESET} — write NVS config for OTA compatibility",
    })

    scanner_config = None
    middleware_config = None

    if mode in ("both", "scanner", "config"):
        scanner_config = collect_scanner_config()

    if mode in ("both", "middleware"):
        if scanner_config is None:
            scanner_config = collect_middleware_mqtt_settings()
        middleware_config = collect_middleware_config()

    if mode in ("both", "scanner"):
        run_scanner_install(scanner_config)

    if mode == "config":
        run_config_only(scanner_config)

    if mode in ("both", "middleware"):
        run_middleware_install(scanner_config, middleware_config)

    # Moonraker Spoolman config (independent of mode)
    spoolman_url = scanner_config.get("spoolman_url") or ""
    if scanner_config.get("spoolman_on") and spoolman_url:
        setup_moonraker_spoolman(spoolman_url)

    print_completion_message(mode, scanner_config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
