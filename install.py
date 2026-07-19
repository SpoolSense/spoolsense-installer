#!/usr/bin/env python3
"""
SpoolSense Installer — interactive CLI for scanner firmware + middleware setup.

Recommended: Run from your printer host (Raspberry Pi) with the ESP32 connected
via USB. This installs everything in one pass.

If your printer host has no free USB port, flash the scanner from a laptop
(choose "Scanner only"), then run this installer again on the Pi to install
the middleware (choose "Middleware only").

Note: SpoolSense middleware must run on the printer host.
"""

__version__ = "1.5.0"

import argparse
import os
import shutil
import sys
import tempfile

from spoolsense_installer.constants import C, BOARDS, MIDDLEWARE_DIR
from spoolsense_installer.errors import InstallerError
from spoolsense_installer.preflight import preflight_checks, run_preflight
from spoolsense_installer.discovery import prompt_device_ids
from spoolsense_installer.ui import ask_choice, ask, validate_url
from spoolsense_installer.config import collect_scanner_config, collect_middleware_config, collect_middleware_mqtt_settings
from spoolsense_installer.nvs import generate_nvs_csv, generate_nvs_bin
from spoolsense_installer.firmware import fetch_release, download_asset, detect_usb_port, verify_flash, flash_firmware
from spoolsense_installer.middleware import (generate_config as generate_middleware_config,
                                             install as install_middleware, copy_klipper_macros,
                                             setup_moonraker_update_manager)
from spoolsense_installer.spoolman import (setup_extra_fields, setup_moonraker_spoolman,
                                           print_failed_fields_summary, fields_for_setup)


# ── Install flow orchestration ───────────────────────────────────────────────

def run_scanner_install(scanner_config: dict, setup_type: str = "",
                        firmware_version: str = "") -> list:
    """Download firmware, generate NVS, flash the ESP32.

    ``setup_type`` widens the Spoolman field set for mode-specific fields
    (e.g. Happy Hare); ``firmware_version`` pins a specific scanner release.
    Returns the list of Spoolman extra fields that could NOT be created
    (empty if Spoolman setup was skipped or fully succeeded).
    """
    board_key = scanner_config["board"]
    _, _, fw_suffix, _, _ = BOARDS[board_key]

    port = detect_usb_port()
    verify_flash(port, board_key)

    release = fetch_release(version=firmware_version)
    firmware_bin = download_asset(release, suffix=fw_suffix)
    bootloader_bin = download_asset(release, name=f"bootloader_{fw_suffix}.bin")
    partitions_bin = download_asset(release, name=f"partitions_{fw_suffix}.bin")

    # Private working dir: no collisions between concurrent runs, no stale
    # sensitive config in the shared temp dir after a crash
    workdir = tempfile.mkdtemp(prefix="spoolsense-install-")
    try:
        nvs_csv = generate_nvs_csv(scanner_config)
        nvs_path = os.path.join(workdir, "spoolsense_nvs.bin")
        generate_nvs_bin(nvs_csv, nvs_path)

        boot_path = os.path.join(workdir, f"bootloader_{fw_suffix}.bin")
        part_path = os.path.join(workdir, f"partitions_{fw_suffix}.bin")
        with open(boot_path, "wb") as f:
            f.write(bootloader_bin)
        with open(part_path, "wb") as f:
            f.write(partitions_bin)

        flash_firmware(port, board_key, firmware_bin, nvs_path, part_path, boot_path)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Setup Spoolman extra fields if enabled
    spoolman_url = scanner_config.get("spoolman_url") or ""
    if scanner_config.get("spoolman_on") and spoolman_url:
        print(f"\n{C.CYAN}── Spoolman Setup ─────────────────────{C.RESET}\n")
        return setup_extra_fields(spoolman_url, fields_for_setup(setup_type))
    return []


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


def run_middleware_install(scanner_config: dict, middleware_config: dict, dev: bool = False) -> list:
    """Generate middleware config, install repo, create systemd service.

    Returns summary steps: a list of (label, status, detail) tuples.
    """
    # Resolve real device IDs from retained MQTT topics before writing config —
    # most installs never need to touch YOUR_DEVICE_ID by hand anymore
    prompt_device_ids(middleware_config.get("scanners", []), scanner_config, ask)

    config_yaml = generate_middleware_config(scanner_config, middleware_config)
    result = install_middleware(config_yaml, dev=dev)

    pinned = result.get("pinned")
    version_note = f"{MIDDLEWARE_DIR} @ {pinned}" if pinned else f"{MIDDLEWARE_DIR} @ branch head"
    steps = [("Middleware repo + dependencies", "ok", version_note)]
    config_path = os.path.join(MIDDLEWARE_DIR, "config.yaml")
    if result["config"] == "written":
        steps.append(("config.yaml written", "ok", config_path))
        if "YOUR_DEVICE_ID" in config_yaml:
            steps.append(("Replace YOUR_DEVICE_ID in config.yaml", "warn",
                          "device ID shown at http://spoolsense.local"))
    else:
        steps.append(("config.yaml kept (existing file untouched)", "skip", config_path))

    if result["service"] is True:
        steps.append(("systemd service (spoolsense.service)", "ok", "enabled on boot"))
    elif result["service"] is False:
        steps.append(("systemd service (spoolsense.service)", "fail", "see manual setup above"))
    else:
        steps.append(("systemd service", "skip", "not a systemd host"))

    # Klipper macros — UPDATE_TAG drives filament deduction in every mode (#30)
    setup_type = middleware_config.get("setup_type", "")
    macro_dst = os.path.expanduser("~/printer_data/config")
    try:
        macro_results = copy_klipper_macros(setup_type)
    except OSError as e:
        print(f"  {C.YELLOW}!{C.RESET} Could not copy Klipper macros: {e}")
        macro_results = {}
        steps.append(("Klipper macros", "fail", str(e)))

    copied = [n for n, s in macro_results.items() if s == "copied"]
    kept = [n for n, s in macro_results.items() if s == "kept-existing"]
    missing = [n for n, s in macro_results.items() if s == "missing-source"]
    for name in copied:
        print(f"  {C.GREEN}✓{C.RESET} Copied {name} to {macro_dst}")
    for name in kept:
        print(f"  {C.DIM}−{C.RESET} Kept existing {name} (not overwritten)")
    if copied or kept:
        includes = ", ".join(f"[include {n}]" for n in sorted(copied + kept)
                             if n != "toolhead_macros_example.cfg")
        print(f"\n  {C.YELLOW}Klipper setup:{C.RESET} add to your printer.cfg: {includes}")
        print(f"  For automatic filament tracking, add {C.BOLD}UPDATE_TAG{C.RESET} to your")
        print("  PRINT_END macro — the middleware deducts usage and writes it")
        print("  back to the spool's NFC tag on the next scan.")
        if "toolhead_macros_example.cfg" in copied + kept:
            print(f"  Multi-tool: adapt toolhead_macros_example.cfg into your T0-Tn macros.")
        steps.append(("Klipper macros installed", "ok", ", ".join(sorted(copied + kept))))
        steps.append(("Add UPDATE_TAG to your PRINT_END macro", "warn",
                      "enables automatic filament tracking"))
    if missing:
        steps.append(("Klipper macros missing from middleware checkout", "warn",
                      ", ".join(sorted(missing))))

    # Mainsail/Fluidd update button (#16)
    um_status = setup_moonraker_update_manager()
    steps.append({
        "added": ("Moonraker update_manager entry", "warn", "restart Moonraker to apply"),
        "exists": ("Moonraker update_manager entry", "ok", "already configured"),
        "upgraded": ("Moonraker update_manager entry", "warn",
                     "upgraded for venv — restart Moonraker"),
        "declined": ("Moonraker update_manager entry", "skip", "declined"),
        "missing-conf": ("Moonraker update_manager entry", "warn",
                         "moonraker.conf not found — add manually"),
        "failed": ("Moonraker update_manager entry", "fail", "could not write moonraker.conf"),
    }[um_status])

    if middleware_config.get("mobile_enabled"):
        steps.append(("Web config panel", "ok", "http://<printer-host>:5001 after service start"))
    return steps


# Summary rendering: ok/warn/fail/skip per step, header reflects the worst outcome
_STEP_ICONS = {
    "ok": f"{C.GREEN}✓{C.RESET}",
    "warn": f"{C.YELLOW}⚠{C.RESET}",
    "fail": f"{C.RED}✗{C.RESET}",
    "skip": f"{C.DIM}−{C.RESET}",
}


def print_completion_message(mode: str, scanner_config: dict, steps: list) -> None:
    """Print a truthful install summary: every step with its actual outcome."""
    failed = any(status == "fail" for _, status, _ in steps)
    warned = any(status == "warn" for _, status, _ in steps)
    if failed:
        color, title = C.RED, "Install finished with errors — see below"
    elif warned:
        color, title = C.YELLOW, "SpoolSense is installed — action needed"
    else:
        color, title = C.GREEN, "SpoolSense is installed!"

    print(f"\n{color}{'═' * 42}")
    print(f"  {title}")
    print(f"{'═' * 42}{C.RESET}\n")

    for label, status, detail in steps:
        icon = _STEP_ICONS.get(status, " ")
        line = f"  {icon} {label}"
        if detail:
            line += f" {C.DIM}— {detail}{C.RESET}"
        print(line)

    print()
    if mode in ("both", "scanner"):
        hostname = scanner_config.get("hostname", "spoolsense")
        print(f"  Scanner:    http://{hostname}.local")
    if mode in ("both", "middleware"):
        print(f"  Middleware: systemctl status spoolsense")
        print(f"  Config:     {MIDDLEWARE_DIR}/config.yaml")
    if mode == "config":
        print(f"  NVS binary: spoolsense_nvs.bin (flash with esptool)")
    print()


# ── Entry point ──────────────────────────────────────────────────────────────

def run_setup_fields(spoolman_url: str, happy_hare: bool = False) -> int:
    """Re-run only Spoolman extra-field creation. Returns a process exit code."""
    if happy_hare:
        # Deprecated no-op kept so old invocations don't argparse-error:
        # since middleware v1.8.6, Happy Hare's mmu_server declares its own
        # Spoolman fields on startup — the installer no longer creates any.
        print(f"\n  {C.YELLOW}Note:{C.RESET} --happy-hare is no longer needed — Happy Hare declares")
        print("  its own Spoolman fields since middleware v1.8.6. Creating the")
        print("  standard scanner fields only.")
    if not spoolman_url:
        spoolman_url = ask("Spoolman URL (e.g. http://localhost:7912)", validate=validate_url)

    print(f"\n{C.CYAN}── Spoolman Field Setup ───────────────{C.RESET}\n")
    failed = setup_extra_fields(spoolman_url, fields_for_setup(""))
    if failed:
        print_failed_fields_summary(spoolman_url, failed)
        return 1
    print(f"\n  {C.GREEN}✓{C.RESET} All Spoolman extra fields are present.")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="SpoolSense installer — scanner firmware + middleware setup.",
    )
    parser.add_argument(
        "--setup-fields",
        action="store_true",
        help="Only (re)create the required Spoolman extra fields, then exit.",
    )
    parser.add_argument(
        "--spoolman-url",
        default="",
        help="Spoolman base URL (e.g. http://localhost:7912). Used with --setup-fields.",
    )
    parser.add_argument(
        "--happy-hare",
        action="store_true",
        help="Deprecated no-op: Happy Hare declares its own Spoolman fields since middleware v1.8.6.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Track the middleware branch head instead of pinning to the latest release.",
    )
    parser.add_argument(
        "--firmware-version",
        default="",
        metavar="X.Y.Z",
        help="Flash a specific scanner firmware release instead of the latest.",
    )
    return parser.parse_args(argv)


def main() -> None:
    """CLI entry point: run the install, translating failures to exit codes.

    Library modules raise InstallerError (after printing their guidance)
    instead of exiting — this is the only place that turns one into exit(1).
    """
    try:
        _main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
    except InstallerError as e:
        if str(e):
            print(f"\n  {C.RED}✗ {e}{C.RESET}")
        sys.exit(1)


def _main() -> None:
    args = parse_args()

    if args.setup_fields:
        sys.exit(run_setup_fields(args.spoolman_url, happy_hare=args.happy_hare))

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
{C.DIM}          NFC Filament Intelligence for 3D Printers
          Installer v{__version__}{C.RESET}
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
        "middleware": "Middleware only (also after using the Web Flasher)",
        "config": f"{C.RED}Config only (source builds){C.RESET} — write NVS config for OTA compatibility",
    })

    # Verify the host can finish this install BEFORE asking 20 questions
    run_preflight(preflight_checks(mode))

    scanner_config = None
    middleware_config = None

    if mode in ("both", "scanner", "config"):
        scanner_config = collect_scanner_config()

    if mode in ("both", "middleware"):
        if scanner_config is None:
            scanner_config = collect_middleware_mqtt_settings()
        middleware_config = collect_middleware_config(
            low_spool_default=scanner_config.get("low_spool_g", 100))

    setup_type = (middleware_config or {}).get("setup_type", "")

    # Happy Hare binding writes spool extras — Spoolman is mandatory there.
    # Check the enabled flag too: the middleware-only settings collector fills
    # spoolman_url even when Spoolman was declined.
    if setup_type == "happy_hare" and not (scanner_config.get("spoolman_on")
                                           and scanner_config.get("spoolman_url")):
        print(f"\n  {C.YELLOW}Happy Hare requires Spoolman{C.RESET} — the middleware binds spools")
        print("  to MMU gates by writing Spoolman extra fields.\n")
        scanner_config["spoolman_url"] = ask("Spoolman URL", default="http://spoolman.local:7912",
                                             validate=validate_url)
        scanner_config["spoolman_on"] = 1

    failed_fields = []
    steps = []
    if mode in ("both", "scanner"):
        failed_fields = run_scanner_install(scanner_config, setup_type,
                                            firmware_version=args.firmware_version)
        steps.append(("Scanner firmware flashed", "ok",
                      BOARDS[scanner_config["board"]][0]))
        if scanner_config.get("spoolman_on") and scanner_config.get("spoolman_url"):
            if failed_fields:
                steps.append(("Spoolman extra fields", "fail",
                              f"{len(failed_fields)} field(s) not created — see below"))
            else:
                steps.append(("Spoolman extra fields", "ok", ""))
        else:
            steps.append(("Spoolman extra fields", "skip", "Spoolman disabled"))

    if mode == "config":
        run_config_only(scanner_config)
        steps.append(("NVS config generated", "ok", "spoolsense_nvs.bin"))

    # Middleware-only installs still need the extra fields (the scanner step
    # that normally creates them didn't run)
    if mode == "middleware" and scanner_config.get("spoolman_on") and scanner_config.get("spoolman_url"):
        print(f"\n{C.CYAN}── Spoolman Setup ─────────────────────{C.RESET}\n")
        failed_fields = setup_extra_fields(scanner_config["spoolman_url"],
                                           fields_for_setup(setup_type))
        if failed_fields:
            steps.append(("Spoolman extra fields", "fail",
                          f"{len(failed_fields)} field(s) not created — see below"))
        else:
            steps.append(("Spoolman extra fields", "ok", ""))

    if mode in ("both", "middleware"):
        steps.extend(run_middleware_install(scanner_config, middleware_config, dev=args.dev))

    # Moonraker Spoolman config (independent of mode)
    spoolman_url = scanner_config.get("spoolman_url") or ""
    if scanner_config.get("spoolman_on") and spoolman_url:
        moonraker_status = setup_moonraker_spoolman(spoolman_url)
        steps.append({
            "added": ("Moonraker [spoolman] config", "warn", "restart Moonraker to apply"),
            "exists": ("Moonraker [spoolman] config", "ok", "already configured"),
            "declined": ("Moonraker [spoolman] config", "skip", "declined"),
            "missing-conf": ("Moonraker [spoolman] config", "warn",
                             "moonraker.conf not found — add manually"),
            "failed": ("Moonraker [spoolman] config", "fail", "could not write moonraker.conf"),
        }[moonraker_status])

    print_completion_message(mode, scanner_config, steps)

    # Print last so a field-creation failure is the final thing the user sees.
    print_failed_fields_summary(spoolman_url, failed_fields)


if __name__ == "__main__":
    main()
