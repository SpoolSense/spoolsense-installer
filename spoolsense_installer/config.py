# config.py — interactive config collection for scanner and middleware setup

import sys
from typing import Dict, List, Optional, Union

from .constants import C
from .ui import ask, ask_choice, ask_yesno, validate_ssid, validate_not_empty, validate_host, validate_port, validate_url


def collect_scanner_config() -> Dict[str, Union[str, int]]:
    """Collect scanner configuration from user input."""
    print(f"\n{C.CYAN}── Scanner Configuration ──────────────{C.RESET}\n")

    board = ask_choice("Scanner board:", {
        "esp32dev": "ESP32-WROOM DevKit (4MB) — most common",
        "esp32s3zero": "ESP32-S3-Zero by Waveshare (4MB)",
        "esp32s3devkitc": "ESP32-S3-DevKitC-1-N16R8 (16MB + 8MB PSRAM)",
        "other": "Other / not sure",
    })

    if board == "other":
        print("\n  For unsupported boards, compile from source with PlatformIO:")
        print("  https://github.com/SpoolSense/spoolsense_scanner")
        print("  The installer cannot safely flash untested board configurations.")
        sys.exit(0)

    def validate_mdns_hostname(value: str) -> Optional[str]:
        v = value.strip().lower()
        if not v:
            return None  # empty = firmware default
        if len(v) > 32:
            return "Max 32 characters"  # ESP32 NVS string limit
        if not all(c.isalnum() or c == "-" for c in v):
            return "Only lowercase letters, numbers, and hyphens"
        if v[0] == "-" or v[-1] == "-":
            return "Cannot start or end with a hyphen"
        return None

    hostname = ask("mDNS hostname (e.g. spoolsense-lane1)", default="spoolsense",
                   validate=validate_mdns_hostname)
    hostname = hostname.strip().lower() or "spoolsense"

    wifi_ssid = ask("WiFi SSID", validate=validate_ssid)
    wifi_pass = ask("WiFi Password", password=True, validate=validate_not_empty)
    mqtt_host = ask("MQTT broker host", validate=validate_host)
    mqtt_port = ask("MQTT port", default=1883, validate=validate_port)
    mqtt_user = ask("MQTT username", default="")
    mqtt_pass = ask("MQTT password", password=True, default="")
    mqtt_prefix = ask("MQTT topic prefix", default="spoolsense")

    spoolman_on = ask_yesno("Enable Spoolman?", default=True)
    spoolman_url = ""
    if spoolman_on:
        spoolman_url = ask("Spoolman URL", default="http://spoolman.local:7912",
                           validate=validate_url)

    auto_mode = ask_choice("Automation mode:", {
        "0": "Self Directed — scanner auto-deducts filament weight",
        "1": "Controlled by HA — Home Assistant controls deduction",
    })

    print(f"\n{C.CYAN}── Optional Hardware ──────────────────{C.RESET}\n")
    lcd_on = ask_yesno("16x2 I2C LCD display attached?", default=False)
    tft_on = False
    tft_driver = "st7789"
    if not lcd_on:
        tft_on = ask_yesno("TFT display attached (240x240)?", default=False)
    if tft_on:
        lcd_on = False
        tft_driver = ask_choice("TFT display driver:", {
            "st7789": "ST7789 (square 240x240)",
            "gc9a01": "GC9A01 (round 240x240)",
        })
    led_on = ask_yesno("Status LED attached?", default=True)
    keypad_on = ask_yesno("3x4 matrix keypad attached?", default=False)
    nfc_reader = ask("NFC reader model", default="pn5180",
                     validate=lambda v: None if v.lower() in ("pn5180", "pn532")
                     else "Must be pn5180 or pn532")
    nfc_reader = nfc_reader.lower()

    print(f"\n{C.CYAN}── Printer Integration ────────────────{C.RESET}\n")
    moonraker_url = ""
    if ask_yesno("Klipper / Moonraker printer?", default=False):
        moonraker_url = ask("Moonraker URL", default="http://localhost:7125",
                            validate=validate_url)

    return {
        "board": board,
        "hostname": hostname,
        "wifi_ssid": wifi_ssid,
        "wifi_pass": wifi_pass,
        "mqtt_host": mqtt_host,
        "mqtt_port": int(mqtt_port),
        "mqtt_user": mqtt_user,
        "mqtt_pass": mqtt_pass,
        "mqtt_prefix": mqtt_prefix,
        "spoolman_on": 1 if spoolman_on else 0,
        "spoolman_url": spoolman_url,
        "auto_mode": int(auto_mode),
        "lcd_on": 1 if lcd_on else 0,
        "tft_on": 1 if tft_on else 0,
        "tft_driver": tft_driver,
        "led_on": 1 if led_on else 0,
        "keypad_on": 1 if keypad_on else 0,
        "nfc_reader": nfc_reader,
        "moonraker_url": moonraker_url,
    }


def collect_middleware_config() -> Dict[str, Union[str, List[str]]]:
    """Collect middleware configuration from user input."""
    print(f"\n{C.CYAN}── Middleware Configuration ────────────{C.RESET}\n")

    setup_type = ask_choice("Scanner setup:", {
        "afc_stage": "AFC shared scanner (scan spool, load any lane)",
        "afc_lane": "AFC per-lane scanners (one scanner per lane)",
        "toolhead_stage": "Toolchanger shared scanner (scan spool, assign via macro or keypad)",
        "toolchanger": "Toolchanger per-toolhead scanners (one scanner per tool)",
        "single": "Single toolhead (one scanner, one extruder)",
    })

    scanners: list[dict] = []
    if setup_type == "afc_stage":
        print(f"\n  {C.YELLOW}Note:{C.RESET} After flashing your scanner, find its device ID")
        print("  from the MQTT topic: spoolsense/<device_id>/tag/state\n")
        scanners.append({"action": "afc_stage"})
    elif setup_type == "afc_lane":
        lane_str = ask("Lanes (comma-separated)", default="lane1,lane2,lane3,lane4")
        lanes = [l.strip() for l in lane_str.split(",") if l.strip()]
        print(f"\n  {C.YELLOW}Note:{C.RESET} After flashing your scanners, update config.yaml")
        print("  with each scanner's device ID from MQTT.\n")
        for lane in lanes:
            scanners.append({"action": "afc_lane", "lane": lane})
    elif setup_type == "toolhead_stage":
        print(f"\n  {C.YELLOW}Note:{C.RESET} Scan a spool, then assign it to a tool using the")
        print("  ASSIGN_SPOOL macro in Klipper console or the 3x4 keypad.\n")
        print(f"  {C.YELLOW}Note:{C.RESET} After flashing your scanner, find its device ID")
        print("  from the MQTT topic: spoolsense/<device_id>/tag/state\n")
        scanners.append({"action": "toolhead_stage"})
    elif setup_type == "toolchanger":
        th_str = ask("Toolheads (comma-separated)", default="T0,T1")
        toolheads = [t.strip() for t in th_str.split(",") if t.strip()]
        print(f"\n  {C.YELLOW}Note:{C.RESET} After flashing your scanners, update config.yaml")
        print("  with each scanner's device ID from MQTT.\n")
        for th in toolheads:
            scanners.append({"action": "toolhead", "toolhead": th})
    elif setup_type == "single":
        scanners.append({"action": "toolhead", "toolhead": "T0"})

    moonraker_url = ask("Moonraker URL", default="http://localhost", validate=validate_url)

    publish_lane_data = False
    if setup_type == "afc_stage":
        print(f"\n  {C.YELLOW}Slicer integration:{C.RESET} Slicers like Orca Slicer can auto-populate")
        print("  tool colors, materials, and temps from your scanned spools.")
        print("\n  AFC handles lane data for its own lanes automatically.")
        print("  Enable this if you also have direct toolheads (e.g. a toolchanger")
        print("  with a Box Turtle) and want slicer data for those tools too.")
        print("  This also enables the ASSIGN_SPOOL macro for tool assignment.\n")
        publish_lane_data = ask_yesno("Enable slicer integration for toolheads?", default=False)
    elif setup_type not in ("afc_lane",):
        print(f"\n  {C.YELLOW}Slicer integration:{C.RESET} Slicers like Orca Slicer can auto-populate")
        print("  tool colors, materials, and temps from your scanned spools.\n")
        publish_lane_data = ask_yesno("Enable slicer integration?", default=False)

    return {
        "setup_type": setup_type,
        "scanners": scanners,
        "moonraker_url": moonraker_url,
        "publish_lane_data": publish_lane_data,
    }


def collect_middleware_mqtt_settings() -> dict:
    """Collect MQTT settings when installing middleware without scanner (no NVS needed)."""
    print(f"\n{C.CYAN}── Connection Settings ─────────────────{C.RESET}\n")
    print("  (These must match your scanner's config)\n")
    return {
        "mqtt_host": ask("MQTT broker host", validate=validate_host),
        "mqtt_port": int(ask("MQTT port", default=1883, validate=validate_port)),
        "mqtt_user": ask("MQTT username", default=""),
        "mqtt_pass": ask("MQTT password", password=True, default=""),
        "spoolman_on": 1 if ask_yesno("Spoolman enabled?", default=True) else 0,
        "spoolman_url": ask("Spoolman URL", default="http://spoolman.local:7912", validate=validate_url),
    }
