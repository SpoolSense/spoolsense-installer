#!/usr/bin/env python3
__version__ = "1.2.4"
"""
SpoolSense Installer — interactive CLI for scanner firmware + middleware setup.

Recommended: Run from your printer host (Raspberry Pi) with the ESP32 connected
via USB. This installs everything in one pass.

If your printer host has no free USB port, flash the scanner from a laptop
(choose "Scanner only"), then run this installer again on the Pi to install
the middleware (choose "Middleware only").

Note: SpoolSense middleware must run on the printer host.
"""

import csv
import getpass
import glob
import io
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable, Dict, List, Optional, Union

GITHUB_API = "https://api.github.com/repos/SpoolSense/spoolsense_scanner/releases/latest"
SPOOLMAN_NFC_FIELD_KEY = "nfc_id"
MIDDLEWARE_REPO = "https://github.com/SpoolSense/spoolsense_middleware.git"
MIDDLEWARE_DIR = os.path.expanduser("~/SpoolSense")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Terminal colors ──────────────────────────────────────────────────────────

class C:
    """ANSI color codes — degrades gracefully if terminal doesn't support them."""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"
    RESET = "\033[0m"

# Board definitions: board_key -> (display name, chip type, firmware suffix, flash size min, bootloader offset)
BOARDS = {
    "esp32dev": ("ESP32-WROOM DevKit (4MB)", "esp32", "esp32dev", 4 * 1024 * 1024, 0x1000),
    "esp32s3zero": ("ESP32-S3-Zero by Waveshare (4MB)", "esp32s3", "esp32s3zero", 4 * 1024 * 1024, 0x0),
}


# ─── Input helpers ────────────────────────────────────────────────────────────

def ask(prompt: str, default: Optional[str] = None, password: bool = False, validate: Optional[Callable[[str], Optional[str]]] = None) -> str:
    """Ask the user for input with optional default, password masking, and validation."""
    while True:
        suffix = f" [{default}]" if default else ""
        if password:
            value = getpass.getpass(f"{prompt}{suffix}: ")
        else:
            value = input(f"{prompt}{suffix}: ").strip()

        if not value and default is not None:
            value = str(default)

        if validate:
            err = validate(value)
            if err:
                print(f"  {C.RED}✗ {err}{C.RESET}")
                continue

        return value


def ask_choice(prompt: str, options: Dict[str, str]) -> str:
    """Ask the user to pick from a numbered list. Returns the key."""
    print(f"\n{prompt}")
    keys = list(options.keys())
    for i, key in enumerate(keys, 1):
        print(f"  [{i}] {options[key]}")

    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(f"  Please enter 1-{len(keys)}")


def ask_yesno(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question. Returns bool."""
    hint = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{hint}]: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  Please enter y or n")


def validate_not_empty(value: str) -> Optional[str]:
    if not value:
        return "Cannot be empty"
    return None


def validate_ssid(value: str) -> Optional[str]:
    if not value:
        return "Cannot be empty"
    if len(value) > 32:
        return "WiFi SSID must be 32 characters or less"
    return None


def is_valid_ipv4(value: str) -> bool:
    """Validate an IPv4 address using logic, not regex."""
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part:
            return False
        if not part.isdigit():
            return False
        if len(part) > 1 and part[0] == "0":
            return False  # no leading zeros (e.g. 01, 001)
        num = int(part)
        if num < 0 or num > 255:
            return False
    return True


def is_valid_hostname(value: str) -> bool:
    """Validate a hostname (RFC 952/1123)."""
    if len(value) > 253:
        return False
    labels = value.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
    return True


def validate_host(value: str) -> Optional[str]:
    """Validate a value as an IPv4 address or hostname."""
    if not value:
        return "Cannot be empty"
    # If it's all digits and dots, it must be a valid IPv4
    if all(c.isdigit() or c == "." for c in value):
        if is_valid_ipv4(value):
            return None
        return "Invalid IP address (e.g. 192.168.1.100)"
    # Otherwise validate as hostname
    if is_valid_hostname(value):
        return None
    return "Must be a valid IP address (e.g. 192.168.1.100) or hostname (e.g. mqtt.local)"


def validate_port(value: str) -> Optional[str]:
    """Validate a port number."""
    if not value.isdigit():
        return "Must be a number"
    port = int(value)
    if port < 1 or port > 65535:
        return "Port must be between 1 and 65535"
    return None


def validate_url(value: str) -> Optional[str]:
    """Validate an HTTP/HTTPS URL with host validation."""
    if not value:
        return "Cannot be empty"
    if not value.startswith("http://") and not value.startswith("https://"):
        return "Must start with http:// or https://"
    # Extract host from URL — strip scheme, path, and optional port
    remainder = value.split("://", 1)[1]
    host_port = remainder.split("/", 1)[0]
    host = host_port.rsplit(":", 1)[0] if ":" in host_port else host_port
    err = validate_host(host)
    if err:
        return f"Invalid host in URL: {err}"
    # Validate port if present
    if ":" in host_port:
        port_str = host_port.rsplit(":", 1)[1]
        port_err = validate_port(port_str)
        if port_err:
            return f"Invalid port in URL: {port_err}"
    return None


# ─── Config collection ────────────────────────────────────────────────────────

def collect_scanner_config() -> Dict[str, Union[str, int]]:
    """Collect scanner configuration from user input."""
    print(f"\n{C.CYAN}── Scanner Configuration ──────────────{C.RESET}\n")

    board = ask_choice("Scanner board:", {
        "esp32dev": "ESP32-WROOM DevKit (4MB) — most common",
        "esp32s3zero": "ESP32-S3-Zero by Waveshare (4MB)",
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
            return None  # empty = use default "spoolsense"
        if len(v) > 32:
            return "Max 32 characters"
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
    if not lcd_on:
        tft_on = ask_yesno("TFT display attached (ST7789 240x240)?", default=False)
    if tft_on:
        lcd_on = False  # mutual exclusion — shared GPIO 22/23 on WROOM
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

    # Lane data publishing — for slicer integration (Orca Slicer, etc.)
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


# ─── NVS partition generation ─────────────────────────────────────────────────

def generate_nvs_csv(config: Dict[str, Union[str, int]]) -> str:
    """Generate NVS partition CSV from scanner config dict."""
    lines = [
        "key,type,encoding,value",
        "spoolsense,namespace,,",
        f"wifi_ssid,data,string,{config['wifi_ssid']}",
        f"wifi_pass,data,string,{config['wifi_pass']}",
        f"mqtt_host,data,string,{config['mqtt_host']}",
        f"mqtt_port,data,u16,{config['mqtt_port']}",
        f"mqtt_user,data,string,{config['mqtt_user']}",
        f"mqtt_pass,data,string,{config['mqtt_pass']}",
        f"mqtt_prefix,data,string,{config['mqtt_prefix']}",
        f"spoolman_on,data,u8,{config['spoolman_on']}",
        f"spoolman_url,data,string,{config['spoolman_url']}",
        f"auto_mode,data,u8,{config['auto_mode']}",
        f"lcd_on,data,u8,{config['lcd_on']}",
        f"tft_on,data,u8,{config['tft_on']}",
        f"led_on,data,u8,{config['led_on']}",
        f"keypad_on,data,u8,{config['keypad_on']}",
        f"nfc_reader,data,string,{config['nfc_reader']}",
        f"hostname,data,string,{config['hostname']}",
        f"moonraker_url,data,string,{config['moonraker_url']}",
    ]
    return "\n".join(lines) + "\n"


def generate_nvs_bin(csv_content: str, output_path: str, size: int = 0x5000) -> str:
    """Generate NVS partition binary using esptool's nvs_partition_gen or a bundled version."""
    csv_path = output_path + ".csv"
    with open(csv_path, "w") as f:
        f.write(csv_content)

    # Try the bundled nvs_partition_gen first, then fall back to installed version
    bundled = os.path.join(SCRIPT_DIR, "lib", "nvs_partition_gen.py")
    if os.path.exists(bundled):
        cmd = [sys.executable, bundled, "generate", csv_path, output_path, hex(size)]
    else:
        # Try finding it via esp-idf or esptool install
        cmd = [sys.executable, "-m", "esp_idf_nvs_partition_gen", "generate",
               csv_path, output_path, hex(size)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\n  ✗ Failed to generate NVS partition: {e}")
        print(f"    Tried: {' '.join(cmd)}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"    {e.stderr.strip()}")
        sys.exit(1)

    os.remove(csv_path)
    return output_path


# ─── Firmware download + flash ────────────────────────────────────────────────

def fetch_latest_release() -> dict:
    """Fetch latest release info from GitHub API."""
    print("\n  Fetching latest release...")
    try:
        req = urllib.request.Request(GITHUB_API, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"\n  ✗ Failed to fetch release info: {e}")
        print("    Check your network connection and try again.")
        sys.exit(1)


def download_asset(release: dict, name: str = "", suffix: str = "") -> bytes:
    """Download a release asset by exact name or firmware suffix.

    Args:
        release: GitHub release dict with 'assets' list
        name: Exact asset filename (e.g. 'bootloader_esp32dev.bin')
        suffix: Firmware suffix — expands to 'spoolsense_scanner_{suffix}.bin'
    """
    target_name = name or f"spoolsense_scanner_{suffix}.bin"
    for asset in release.get("assets", []):
        if asset["name"] == target_name:
            url = asset["browser_download_url"]
            expected_size = asset.get("size", 0)
            print(f"  Downloading {asset['name']}...")
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    data = resp.read()
            except Exception as e:
                print(f"\n  ✗ Download failed: {e}")
                sys.exit(1)
            if expected_size and len(data) != expected_size:
                print(f"\n  ✗ Download incomplete: got {len(data)} bytes, expected {expected_size}")
                sys.exit(1)
            return data

    print(f"\n  ✗ Asset '{target_name}' not found in release {release.get('tag_name', '?')}")
    print("    Available assets:")
    for asset in release.get("assets", []):
        print(f"      {asset['name']}")
    sys.exit(1)


def detect_usb_port() -> Optional[str]:
    """Auto-detect the ESP32 USB port."""
    print(f"\n{C.CYAN}── Detecting ESP32 ─────────────────────{C.RESET}\n")

    patterns = []
    system = platform.system()
    if system == "Linux":
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]
    elif system == "Darwin":
        patterns = ["/dev/cu.usbserial-*", "/dev/cu.usbmodem*", "/dev/cu.SLAB_USB*"]
    elif system == "Windows":
        # On Windows, esptool can auto-detect
        return None

    ports = []
    for pattern in patterns:
        ports.extend(glob.glob(pattern))

    if not ports:
        print("  ✗ No ESP32 USB device found.")
        print("")
        print("  Make sure the ESP32 is connected via USB and try again.")
        print("  If using an ESP32-S3, you may need to hold BOOT while connecting.")
        sys.exit(1)

    if len(ports) == 1:
        print(f"  Found: {ports[0]}")
        return ports[0]

    print("  Multiple USB devices found:")
    for i, port in enumerate(ports, 1):
        print(f"    [{i}] {port}")
    while True:
        choice = input("  Select port: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                return ports[idx]
        except ValueError:
            pass


def verify_flash(port: Optional[str], board_key: str) -> bool:
    """Verify the connected chip matches the selected board and has sufficient flash."""
    board_name, expected_chip, _, min_flash, _ = BOARDS[board_key]
    print(f"\n  Verifying chip...")

    cmd = ["esptool"]
    if port:
        cmd.extend(["--port", port])
    cmd.append("flash-id")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError):
        cmd[0] = sys.executable
        cmd.insert(1, "-m")
        cmd.insert(2, "esptool")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

    output = result.stdout + result.stderr

    # Check chip type
    chip_match = re.search(r"Chip is (ESP32[^\s]*)", output)
    if chip_match:
        detected_chip = chip_match.group(1).lower().replace("-", "")
        if expected_chip not in detected_chip:
            print(f"\n  ✗ Chip mismatch!")
            print(f"    Selected board: {board_name} (expects {expected_chip})")
            print(f"    Detected chip:  {chip_match.group(1)}")
            print(f"    Please select the correct board type and try again.")
            sys.exit(1)
        print(f"  Chip: {chip_match.group(1)} ✓")

    # Check flash size
    flash_match = re.search(r"(\d+)\s*MB", output)
    if flash_match:
        flash_bytes = int(flash_match.group(1)) * 1024 * 1024
        if flash_bytes < min_flash:
            print(f"\n  ✗ Flash too small!")
            print(f"    Required: {min_flash // (1024*1024)}MB")
            print(f"    Detected: {flash_match.group(1)}MB")
            print(f"    This board cannot run SpoolSense firmware.")
            sys.exit(1)
        print(f"  Flash: {flash_match.group(1)}MB ✓")

    return True


def setup_spoolman_extra_fields(spoolman_url: str) -> None:
    """Create extra fields in Spoolman for tag data enrichment."""
    # Fields to create: (entity_type, key, field_type, display_name)
    fields = [
        ("spool", "nfc_id", "text", "NFC Tag ID"),
        ("spool", "tag_format", "text", "Tag Format"),
        ("filament", "aspect", "text", "Aspect/Finish"),
        ("filament", "dry_temp", "text", "Dry Temp (°C)"),
        ("filament", "dry_time_hours", "text", "Dry Time (hrs)"),
    ]

    for entity_type, key, field_type, display_name in fields:
        # Check if field already exists
        try:
            req = urllib.request.Request(f"{spoolman_url}/api/v1/field/{entity_type}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                existing = json.loads(resp.read())
                if any(f.get("key") == key for f in existing):
                    print(f"  {C.GREEN}✓{C.RESET} {entity_type}.{key} already exists")
                    continue
        except Exception as e:
            print(f"  {C.YELLOW}!{C.RESET} Could not check {entity_type}.{key}: {e}")
            continue

        # Create the field
        try:
            body = json.dumps({"field_type": field_type, "name": display_name}).encode()
            req = urllib.request.Request(
                f"{spoolman_url}/api/v1/field/{entity_type}/{key}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    print(f"  {C.GREEN}✓{C.RESET} Created {entity_type}.{key}")
        except Exception as e:
            print(f"  {C.YELLOW}!{C.RESET} Could not create {entity_type}.{key}: {e}")


def flash_firmware(port: Optional[str], board_key: str, firmware_bin: bytes, nvs_bin_path: str, partitions_bin_path: str, bootloader_bin_path: str) -> None:
    """Flash bootloader + partition table + NVS config + firmware to the ESP32."""
    print(f"\n  Flashing firmware...")
    print(f"{C.YELLOW}  ⚠ {C.RESET} Do NOT disconnect the USB cable during flashing!\n")

    cmd = ["esptool"]
    if port:
        cmd.extend(["--port", port])

    board_name, chip, _, _, bootloader_offset = BOARDS[board_key]
    cmd.extend(["--chip", chip, "write-flash"])

    # Write bootloader, partition table, NVS config, and firmware
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fw_file:
        fw_file.write(firmware_bin)
        fw_path = fw_file.name

    try:
        cmd.extend([
            hex(bootloader_offset), bootloader_bin_path,
            "0x8000", partitions_bin_path,
            "0x9000", nvs_bin_path,
            "0x10000", fw_path,
        ])

        try:
            result = subprocess.run(cmd, timeout=120)
        except (FileNotFoundError, OSError):
            cmd[0] = sys.executable
            cmd.insert(1, "-m")
            cmd.insert(2, "esptool")
            result = subprocess.run(cmd, timeout=120)

        if result.returncode != 0:
            print("\n  ✗ Flash failed!")
            print("")
            print("  If the device is unresponsive:")
            print("    1. Hold the BOOT button on the ESP32")
            print("    2. Press and release the RESET button")
            print("    3. Release the BOOT button")
            print("    4. Run the installer again")
            sys.exit(1)

        print("\n  ✓ Firmware flashed successfully!")
    finally:
        os.unlink(fw_path)


# ─── Middleware install ────────────────────────────────────────────────────────

def generate_middleware_config(scanner_config: dict, middleware_config: dict) -> str:
    """Generate middleware config.yaml from collected settings."""

    # Build scanners YAML block
    scanners = middleware_config.get("scanners", [])
    scanner_lines: list[str] = []
    for i, s in enumerate(scanners):
        device_id = f"YOUR_DEVICE_ID_{i + 1}" if len(scanners) > 1 else "YOUR_DEVICE_ID"
        scanner_lines.append(f'  "{device_id}":')
        scanner_lines.append(f'    action: "{s["action"]}"')
        if "lane" in s:
            scanner_lines.append(f'    lane: "{s["lane"]}"')
        if "toolhead" in s:
            scanner_lines.append(f'    toolhead: "{s["toolhead"]}"')
    scanners_yaml = "\n".join(scanner_lines)

    config_yaml = f"""# Generated by SpoolSense Installer
# https://github.com/SpoolSense/spoolsense-installer
#
# After flashing your scanner(s), find each device ID from MQTT:
#   spoolsense/<device_id>/tag/state
# Replace YOUR_DEVICE_ID below with the actual device ID.

mqtt:
  broker: "{scanner_config['mqtt_host']}"
  port: {scanner_config['mqtt_port']}
  username: "{scanner_config['mqtt_user']}"
  password: "{scanner_config['mqtt_pass']}"

spoolman_url: "{scanner_config['spoolman_url']}"

moonraker_url: "{middleware_config['moonraker_url']}"

low_spool_threshold: 100

scanner_topic_prefix: "spoolsense"

scanners:
{scanners_yaml}

# Slicer integration — publish spool data to Moonraker's lane_data database
# so Orca Slicer (and other slicers) can auto-populate tool colors/materials/temps.
# Only enable if AFC or Happy Hare is NOT handling lane data.
publish_lane_data: {str(middleware_config.get('publish_lane_data', False)).lower()}
"""
    return config_yaml


def install_middleware(config_yaml: str) -> None:
    """Clone SpoolSense middleware, install deps, write config, create service."""
    print(f"\n{C.CYAN}── Installing Middleware ────────────────{C.RESET}\n")

    # Clone or update
    if os.path.isdir(MIDDLEWARE_DIR):
        print("  SpoolSense middleware directory exists, updating...")
        subprocess.run(["git", "-C", MIDDLEWARE_DIR, "pull", "--quiet"], check=True)
    else:
        print("  Cloning SpoolSense middleware...")
        subprocess.run(["git", "clone", "--quiet", MIDDLEWARE_REPO, MIDDLEWARE_DIR], check=True)
    print("  ✓ Repository ready")

    # Install Python deps
    print("  Installing Python dependencies...")
    req_file = os.path.join(MIDDLEWARE_DIR, "middleware", "requirements.txt")
    if os.path.exists(req_file):
        try:
            result = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                                     "--break-system-packages", "-r", req_file],
                                    capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print(f"  {C.RED}✗ pip install timed out after 5 minutes{C.RESET}")
            print(f"    Try manually: pip3 install -r {req_file}")
            sys.exit(1)
        if result.returncode != 0:
            print(f"  {C.RED}✗ Failed to install Python dependencies{C.RESET}")
            output = result.stderr.strip() if result.stderr else result.stdout.strip()
            if output:
                print(f"    {output}")
            print(f"    Try manually: pip3 install -r {req_file}")
            sys.exit(1)
        print("  ✓ Dependencies installed")
    else:
        print(f"  {C.RED}✗ requirements.txt not found at {req_file}{C.RESET}")
        print("    The middleware repository may be incomplete. Try deleting")
        print(f"    {MIDDLEWARE_DIR} and running the installer again.")
        sys.exit(1)

    # Write config
    config_path = os.path.join(MIDDLEWARE_DIR, "middleware", "config.yaml")
    if os.path.exists(config_path):
        print(f"  ⚠  Existing config found at {config_path}")
        if not ask_yesno("  Overwrite?", default=False):
            print("  Skipping config write.")
            return
    with open(config_path, "w") as f:
        f.write(config_yaml)
    print(f"  {C.GREEN}✓{C.RESET} Config written to {config_path}")

    # Create systemd service
    if platform.system() == "Linux" and shutil.which("systemctl"):
        create_systemd_service()


def create_systemd_service() -> None:
    """Create and enable systemd service for SpoolSense middleware."""
    service_content = f"""[Unit]
Description=SpoolSense Middleware
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={os.environ.get('USER', 'pi')}
WorkingDirectory={MIDDLEWARE_DIR}/middleware
ExecStart={sys.executable} {MIDDLEWARE_DIR}/middleware/spoolsense.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    service_path = "/etc/systemd/system/spoolsense.service"
    tmp_path = os.path.join(tempfile.gettempdir(), "spoolsense.service")

    with open(tmp_path, "w") as f:
        f.write(service_content)

    print("  Creating systemd service...")
    try:
        subprocess.run(["sudo", "cp", tmp_path, service_path], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "spoolsense"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "spoolsense"], check=True)
        print("  ✓ SpoolSense service started and enabled on boot")
    except subprocess.CalledProcessError:
        print(f"{C.YELLOW}  ⚠ {C.RESET} Could not create systemd service (requires sudo)")
        print(f"     Manual setup: copy {tmp_path} to {service_path}")
    finally:
        os.unlink(tmp_path)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Python version check — middleware uses features that require 3.9+
    if sys.version_info < (3, 9):
        print(f"\n  {C.RED}✗ Python 3.9 or newer is required.{C.RESET}")
        print(f"    You have: Python {sys.version_info.major}.{sys.version_info.minor}")
        print("    Install a newer Python or use pyenv.")
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
    print("  in one pass.")
    print("")
    print(f"  No free USB on the Pi? Flash the scanner from a laptop")
    print("  (Scanner only), then run again on the Pi (Middleware only).")
    print("")
    print(f"  {C.YELLOW}Note:{C.RESET} SpoolSense middleware must run on the printer host.")
    print("")

    mode = ask_choice("What do you want to install?", {
        "both": "Scanner + Middleware (recommended)",
        "scanner": "Scanner only",
        "middleware": "Middleware only",
        "config": f"{C.RED}Config only (source builds){C.RESET} — write NVS config for OTA compatibility",
    })

    scanner_config = None
    middleware_config = None

    # Collect scanner config (needed for scanner, config-only, and middleware MQTT settings)
    if mode in ("both", "scanner", "config"):
        scanner_config = collect_scanner_config()

    if mode in ("both", "middleware"):
        # If middleware-only, we still need MQTT settings
        if scanner_config is None:
            print("\n── Connection Settings ─────────────────\n")
            print("  (These must match your scanner's config)\n")
            scanner_config = {
                "mqtt_host": ask("MQTT broker host", validate=validate_not_empty),
                "mqtt_port": int(ask("MQTT port", default=1883, validate=validate_port)),
                "mqtt_user": ask("MQTT username", default=""),
                "mqtt_pass": ask("MQTT password", password=True, default=""),
                "spoolman_url": ask("Spoolman URL", default="http://spoolman.local:7912",
                                    validate=validate_url),
            }
        middleware_config = collect_middleware_config()

    # ── Scanner install ───────────────────────────────────────────────────────
    if mode in ("both", "scanner"):
        print(f"\n{C.CYAN}── Installing Scanner ──────────────────{C.RESET}\n")

        # Download firmware, bootloader, and partition table
        release = fetch_latest_release()
        board_key = scanner_config["board"]
        _, _, fw_suffix, _, _ = BOARDS[board_key]
        firmware_bin = download_asset(release, suffix=fw_suffix)
        print(f"  {C.GREEN}✓{C.RESET} Firmware downloaded ({len(firmware_bin)} bytes)")

        bootloader_bin = download_asset(release, name=f"bootloader_{fw_suffix}.bin")
        print(f"  {C.GREEN}✓{C.RESET} Bootloader downloaded ({len(bootloader_bin)} bytes)")

        partitions_bin = download_asset(release, name=f"partitions_{fw_suffix}.bin")
        print(f"  {C.GREEN}✓{C.RESET} Partition table downloaded ({len(partitions_bin)} bytes)")

        # Generate NVS config partition
        print("  Generating NVS config partition...")
        nvs_csv = generate_nvs_csv(scanner_config)
        nvs_bin_path = os.path.join(tempfile.gettempdir(), "spoolsense_nvs.bin")
        generate_nvs_bin(nvs_csv, nvs_bin_path)
        print("  ✓ NVS config generated")

        # Detect and verify USB
        port = detect_usb_port()
        verify_flash(port, board_key)

        # Write bootloader and partitions binaries to temp files
        bootloader_bin_path = os.path.join(tempfile.gettempdir(), "spoolsense_bootloader.bin")
        with open(bootloader_bin_path, "wb") as f:
            f.write(bootloader_bin)

        partitions_bin_path = os.path.join(tempfile.gettempdir(), "spoolsense_partitions.bin")
        with open(partitions_bin_path, "wb") as f:
            f.write(partitions_bin)

        # Flash
        flash_firmware(port, board_key, firmware_bin, nvs_bin_path, partitions_bin_path, bootloader_bin_path)

        # Cleanup
        for p in [nvs_bin_path, bootloader_bin_path, partitions_bin_path]:
            if os.path.exists(p):
                os.unlink(p)

        # Set up Spoolman nfc_id extra field if Spoolman is enabled
        if scanner_config.get("spoolman_on") and scanner_config.get("spoolman_url"):
            print("")
            if ask_yesno("Create Spoolman extra fields for tag data? (nfc_id, tag format, aspect, dry temps)", default=True):
                print("  Setting up Spoolman extra fields...")
                setup_spoolman_extra_fields(scanner_config["spoolman_url"])

    # ── Config only (source builds) ─────────────────────────────────────────
    if mode == "config":
        print(f"\n{C.CYAN}── Writing NVS Config ──────────────────{C.RESET}\n")
        print(f"  {C.RED}{C.BOLD}For source builds only!{C.RESET}")
        print(f"  This writes your settings to NVS so OTA updates preserve your config.\n")

        # Generate NVS binary
        nvs_csv = generate_nvs_csv(scanner_config)
        nvs_bin_path = os.path.join(tempfile.gettempdir(), "spoolsense_nvs.bin")
        generate_nvs_bin(nvs_csv, nvs_bin_path)
        print(f"  {C.GREEN}✓{C.RESET} NVS config generated")

        # Detect USB and write NVS
        port = detect_usb_port()
        board_key = scanner_config["board"]
        _, chip, _, _, _ = BOARDS[board_key]

        print(f"  Writing NVS config to {port}...")
        cmd = [
            sys.executable, "-m", "esptool",
            "--chip", chip,
            "--port", port,
            "write-flash",
            "0x9000", nvs_bin_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"\n  {C.RED}✗ Failed to write NVS:{C.RESET}")
            print(result.stderr)
            sys.exit(1)
        print(f"  {C.GREEN}✓{C.RESET} NVS config written")

        # Cleanup
        if os.path.exists(nvs_bin_path):
            os.unlink(nvs_bin_path)

        # Spoolman nfc_id field
        if scanner_config.get("spoolman_on") and scanner_config.get("spoolman_url"):
            print("")
            if ask_yesno("Create Spoolman extra fields for tag data? (nfc_id, tag format, aspect, dry temps)", default=True):
                print("  Setting up Spoolman extra fields...")
                setup_spoolman_extra_fields(scanner_config["spoolman_url"])

    # ── Middleware install ─────────────────────────────────────────────────────
    if mode in ("both", "middleware"):
        config_yaml = generate_middleware_config(scanner_config, middleware_config)
        install_middleware(config_yaml)

        # Copy Klipper macro for toolhead_stage users
        if middleware_config.get("setup_type") == "toolhead_stage":
            klipper_cfg_src = os.path.join(MIDDLEWARE_DIR, "middleware", "klipper", "spoolsense.cfg")
            klipper_cfg_dst = os.path.expanduser("~/printer_data/config/spoolsense.cfg")
            if os.path.exists(klipper_cfg_src):
                os.makedirs(os.path.dirname(klipper_cfg_dst), exist_ok=True)
                shutil.copy2(klipper_cfg_src, klipper_cfg_dst)
                print(f"  {C.GREEN}✓{C.RESET} Klipper macro copied to {klipper_cfg_dst}")
                print(f"\n  {C.YELLOW}Important:{C.RESET} Add this line to your printer.cfg:")
                print(f"    [include spoolsense.cfg]")
                print(f"  Then restart Klipper.\n")

    # ── Done ──────────────────────────────────────────────────────────────────
    print("")
    print(f"{C.GREEN}══════════════════════════════════════════")
    if mode == "config":
        print(f"  {C.BOLD}NVS config written!{C.RESET}{C.GREEN}")
        print("")
        print(f"  Your settings are now stored in NVS.")
        print(f"  OTA updates will preserve your config.")
    else:
        print(f"  {C.BOLD}SpoolSense is installed!{C.RESET}{C.GREEN}")
        print("")
        hn = scanner_config.get("hostname", "spoolsense") if scanner_config else "spoolsense"
        if mode in ("both", "scanner"):
            print(f"  Scanner:    {C.CYAN}http://{hn}.local{C.GREEN}")
            print(f"  Device ID:  Shown on the landing page (needed for middleware config)")
        if mode in ("both", "middleware"):
            print(f"  Middleware: {C.CYAN}systemctl status spoolsense{C.GREEN}")
            print(f"  Config:     {C.CYAN}~/SpoolSense/middleware/config.yaml{C.GREEN}")
            print(f"  {C.YELLOW}Remember:{C.RESET}{C.GREEN} Replace YOUR_DEVICE_ID in config.yaml with")
            print(f"  the device ID from {C.CYAN}http://{hn}.local{C.GREEN}")
    print("")
    print(f"  Tap a spool to test.{C.RESET}")
    print(f"{C.GREEN}══════════════════════════════════════════{C.RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
