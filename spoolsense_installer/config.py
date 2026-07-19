# config.py — interactive config collection for scanner and middleware setup

import sys
from typing import Dict, List, Optional, Union

from .constants import BOARDS, C
from .ui import ask, ask_choice, ask_yesno, validate_ssid, validate_not_empty, validate_host, validate_port, validate_url


def board_choices() -> Dict[str, str]:
    """Board prompt options, generated from the canonical BOARDS table."""
    choices = {key: display for key, (display, *_rest) in BOARDS.items()}
    choices["esp32dev"] += " — most common"
    choices["other"] = "Other / not sure"
    return choices


def collect_scanner_config() -> Dict[str, Union[str, int]]:
    """Collect scanner configuration from user input."""
    print(f"\n{C.CYAN}── Scanner Configuration ──────────────{C.RESET}\n")

    board = ask_choice("Scanner board:", board_choices())

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
    # No topic-prefix prompt: the pre-built firmware publishes under a
    # compile-time "spoolsense" prefix (UserConfig.h) — it is not configurable.

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

    prusalink_on, prusalink_url, prusalink_key = 0, "", ""
    if ask_yesno("PrusaLink printer (MK4/XL/MINI)?", default=False):
        prusalink_on = 1
        prusalink_url = ask("PrusaLink URL", default="http://prusa.local",
                            validate=validate_url)
        prusalink_key = ask("PrusaLink API key (Settings → Network on the printer)",
                            validate=validate_not_empty)

    u1_on, u1_channel = 0, 0
    if ask_yesno("Snapmaker U1 printer (direct mode)?", default=False):
        u1_on = 1
        u1_channel = int(ask("U1 material channel (0-3)", default=0,
                             validate=lambda v: None if v.isdigit() and int(v) <= 3
                             else "Must be 0-3"))

    print(f"\n{C.CYAN}── Behavior ───────────────────────────{C.RESET}\n")

    def validate_grams(value: str) -> Optional[str]:
        return None if value.isdigit() else "Must be a non-negative number"

    low_spool_g = int(ask("Low-spool alert threshold (grams)", default=100,
                          validate=validate_grams))
    bambu_dash = ask_yesno("Enable the Bambu AMS dashboard view?", default=False)
    # Keep-awake trades battery/heat for lower scan latency
    wifi_awake = ask_yesno("Keep WiFi always awake (faster scans, more power)?",
                           default=False)

    return {
        "board": board,
        "hostname": hostname,
        "wifi_ssid": wifi_ssid,
        "wifi_pass": wifi_pass,
        "mqtt_host": mqtt_host,
        "mqtt_port": int(mqtt_port),
        "mqtt_user": mqtt_user,
        "mqtt_pass": mqtt_pass,
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
        "wifi_awake": 1 if wifi_awake else 0,
        "low_spool_g": low_spool_g,
        "bambu_dash": 1 if bambu_dash else 0,
        "prusalink_on": prusalink_on,
        "prusalink_url": prusalink_url,
        "prusalink_key": prusalink_key,
        "u1_on": u1_on,
        "u1_channel": u1_channel,
    }


def validate_toolhead_list(value: str) -> Optional[str]:
    names = [t.strip() for t in value.split(",")]
    if not names or any(not n for n in names):
        return "Comma-separated names, e.g. T0,T1"
    for n in names:
        if not all(c.isalnum() or c in "_-" for c in n):
            return f"'{n}' — only letters, numbers, hyphens, and underscores"
    return None


def collect_middleware_config(low_spool_default: int = 100) -> Dict[str, Union[str, List[str]]]:
    """Collect middleware configuration from user input.

    ``low_spool_default`` seeds the threshold prompt (pass the scanner's
    answer in combined installs so the two stay consistent by default).
    """
    print(f"\n{C.CYAN}── Middleware Configuration ────────────{C.RESET}\n")

    setup_type = ask_choice("Scanner setup:", {
        "afc_stage": "AFC shared scanner (scan spool, load any lane)",
        "afc_lane": "AFC per-lane scanners (one scanner per lane)",
        "toolhead_stage": "Toolchanger shared scanner (scan spool, assign via macro or keypad)",
        "toolchanger": "Toolchanger per-toolhead scanners (one scanner per tool)",
        "single": "Single toolhead (one scanner, one extruder)",
        "happy_hare": "Happy Hare MMU (scan spool, bind to the selected gate)",
    })

    scanners: list[dict] = []
    toolheads: List[str] = []
    if setup_type == "happy_hare":
        # Requires middleware >= 1.8.6 (binding via HH's MMU_SPOOLMAN command);
        # fresh installs get it automatically via the latest-release pin.
        print(f"\n  {C.YELLOW}Note:{C.RESET} Requires Happy Hare in {C.BOLD}pull mode{C.RESET} (spoolman_support: pull)")
        print("  and SpoolSense middleware 1.8.6 or newer (installed automatically).")
        print("  Workflow: select a gate (MMU_SELECT GATE=N), scan a tag, and the")
        print("  middleware binds the spool via Happy Hare's MMU_SPOOLMAN command.\n")
        print(f"  {C.YELLOW}Note:{C.RESET} After flashing your scanner, find its device ID")
        print("  from the MQTT topic: spoolsense/<device_id>/tag/state\n")
        scanners.append({"action": "happy_hare_stage"})
    elif setup_type == "afc_stage":
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
        # Explicit toolheads list (#24) — the mobile app picker needs it
        th_str = ask("Toolheads (comma-separated)", default="T0,T1",
                     validate=validate_toolhead_list)
        toolheads = [t.strip() for t in th_str.split(",") if t.strip()]
        scanners.append({"action": "toolhead_stage"})
    elif setup_type == "toolchanger":
        th_str = ask("Toolheads (comma-separated)", default="T0,T1",
                     validate=validate_toolhead_list)
        toolheads = [t.strip() for t in th_str.split(",") if t.strip()]
        print(f"\n  {C.YELLOW}Note:{C.RESET} After flashing your scanners, update config.yaml")
        print("  with each scanner's device ID from MQTT.\n")
        for th in toolheads:
            scanners.append({"action": "toolhead", "toolhead": th})
    elif setup_type == "single":
        scanners.append({"action": "toolhead", "toolhead": "T0"})

    moonraker_url = ask("Moonraker URL", default="http://localhost:7125", validate=validate_url)

    def validate_grams(value: str) -> Optional[str]:
        return None if value.isdigit() else "Must be a non-negative number"

    low_spool_threshold = int(ask("Low-spool alert threshold (grams)",
                                  default=low_spool_default, validate=validate_grams))

    print(f"\n  {C.YELLOW}Web config panel:{C.RESET} the middleware can serve a browser UI +")
    print("  mobile REST API on port 5001 for editing config and mobile scans.")
    if setup_type == "happy_hare":
        print("  Mobile scans assign a tag to any MMU gate from your phone (v1.8.6+).")
    print()
    mobile_enabled = ask_yesno("Enable the web config panel (port 5001)?", default=False)

    # The happy_hare_stage mobile action requires the gate count so the app
    # can offer G0..G{n-1}; the middleware derives the gates itself. The
    # physical select-then-scan flow works without it, so only ask when
    # mobile is enabled.
    num_gates = 0
    if setup_type == "happy_hare" and mobile_enabled:
        def validate_gates(value: str) -> Optional[str]:
            return None if value.isdigit() and 1 <= int(value) <= 32 else "Must be 1-32"

        num_gates = int(ask("Number of MMU gates", default=4, validate=validate_gates))

    publish_lane_data = False
    if setup_type == "afc_stage":
        print(f"\n  {C.YELLOW}Slicer integration:{C.RESET} Slicers like Orca Slicer can auto-populate")
        print("  tool colors, materials, and temps from your scanned spools.")
        print("\n  AFC handles lane data for its own lanes automatically.")
        print("  Enable this if you also have direct toolheads (e.g. a toolchanger")
        print("  with a Box Turtle) and want slicer data for those tools too.")
        print("  This also enables the ASSIGN_SPOOL macro for tool assignment.\n")
        publish_lane_data = ask_yesno("Enable slicer integration for toolheads?", default=False)
    elif setup_type not in ("afc_lane", "happy_hare"):
        print(f"\n  {C.YELLOW}Slicer integration:{C.RESET} Slicers like Orca Slicer can auto-populate")
        print("  tool colors, materials, and temps from your scanned spools.\n")
        publish_lane_data = ask_yesno("Enable slicer integration?", default=False)

    return {
        "setup_type": setup_type,
        "scanners": scanners,
        "toolheads": toolheads,
        "moonraker_url": moonraker_url,
        "low_spool_threshold": low_spool_threshold,
        "mobile_enabled": mobile_enabled,
        "num_gates": num_gates,
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
