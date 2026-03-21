#!/usr/bin/env python3
__version__ = "1.0.0"
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

GITHUB_API = "https://api.github.com/repos/SpoolSense/spoolsense_scanner/releases/latest"
SPOOLMAN_NFC_FIELD_KEY = "nfc_id"
MIDDLEWARE_REPO = "https://github.com/SpoolSense/SpoolSense.git"
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

def ask(prompt, default=None, password=False, validate=None):
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


def ask_choice(prompt, options):
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


def ask_yesno(prompt, default=True):
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


def validate_not_empty(value):
    if not value:
        return "Cannot be empty"
    return None


def validate_ssid(value):
    if not value:
        return "Cannot be empty"
    if len(value) > 32:
        return "WiFi SSID must be 32 characters or less"
    return None


def is_valid_ipv4(value):
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


def is_valid_hostname(value):
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


def validate_host(value):
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


def validate_port(value):
    """Validate a port number."""
    if not value.isdigit():
        return "Must be a number"
    port = int(value)
    if port < 1 or port > 65535:
        return "Port must be between 1 and 65535"
    return None


def validate_url(value):
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

def collect_scanner_config():
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

    return {
        "board": board,
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
    }


def collect_middleware_config():
    """Collect middleware configuration from user input."""
    print(f"\n{C.CYAN}── Middleware Configuration ────────────{C.RESET}\n")

    mode = ask_choice("Toolhead mode:", {
        "single": "Single toolhead",
        "toolchanger": "Toolchanger (MadMax, StealthChanger)",
        "afc": "AFC (Box Turtle, NightOwl)",
    })

    toolheads = ["T0"]
    if mode == "toolchanger":
        th_str = ask("Toolheads (comma-separated)", default="T0,T1")
        toolheads = [t.strip() for t in th_str.split(",") if t.strip()]
    elif mode == "afc":
        lane_str = ask("Lanes (comma-separated)", default="lane1,lane2,lane3,lane4")
        toolheads = [l.strip() for l in lane_str.split(",") if l.strip()]

    moonraker_url = ask("Moonraker URL", default="http://localhost", validate=validate_url)

    return {
        "mode": mode,
        "toolheads": toolheads,
        "moonraker_url": moonraker_url,
    }


# ─── NVS partition generation ─────────────────────────────────────────────────

def generate_nvs_csv(config):
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
    ]
    return "\n".join(lines) + "\n"


def generate_nvs_bin(csv_content, output_path, size=0x5000):
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

def fetch_latest_release():
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


def download_asset(release, suffix):
    """Download a firmware asset matching the given suffix."""
    # Match spoolsense_scanner_<suffix>.bin specifically, not partitions or other files
    target_name = f"spoolsense_scanner_{suffix}.bin"
    for asset in release.get("assets", []):
        if asset["name"] == target_name:
            url = asset["browser_download_url"]
            print(f"  Downloading {asset['name']}...")
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    return resp.read()
            except Exception as e:
                print(f"\n  ✗ Download failed: {e}")
                sys.exit(1)

    print(f"\n  ✗ No firmware binary found for '{suffix}' in release {release.get('tag_name', '?')}")
    print("    Available assets:")
    for asset in release.get("assets", []):
        print(f"      {asset['name']}")
    sys.exit(1)


def detect_usb_port():
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


def verify_flash(port, board_key):
    """Verify the connected chip matches the selected board and has sufficient flash."""
    board_name, expected_chip, _, min_flash, _ = BOARDS[board_key]
    print(f"\n  Verifying chip...")

    cmd = ["esptool.py"]
    if port:
        cmd.extend(["--port", port])
    cmd.append("flash_id")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
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


def setup_spoolman_extra_fields(spoolman_url):
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


def flash_firmware(port, board_key, firmware_bin, nvs_bin_path, partitions_bin_path, bootloader_bin_path):
    """Flash bootloader + partition table + NVS config + firmware to the ESP32."""
    print(f"\n  Flashing firmware...")
    print(f"{C.YELLOW}  ⚠ {C.RESET} Do NOT disconnect the USB cable during flashing!\n")

    cmd = ["esptool.py"]
    if port:
        cmd.extend(["--port", port])

    board_name, chip, _, _, bootloader_offset = BOARDS[board_key]
    cmd.extend(["--chip", chip, "write_flash"])

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
        except FileNotFoundError:
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

def generate_middleware_config(scanner_config, middleware_config):
    """Generate middleware config.yaml from collected settings."""
    template_name = f"config.{middleware_config['mode']}.yaml"
    template_path = os.path.join(SCRIPT_DIR, "templates", template_name)

    if not os.path.exists(template_path):
        # Fall back to generating from scratch
        pass

    toolheads_yaml = "\n".join(f'  - "{t}"' for t in middleware_config["toolheads"])

    config_yaml = f"""# Generated by SpoolSense Installer
# https://github.com/SpoolSense/spoolsense-installer

toolhead_mode: "{middleware_config['mode']}"

toolheads:
{toolheads_yaml}

mqtt:
  broker: "{scanner_config['mqtt_host']}"
  port: {scanner_config['mqtt_port']}
  username: "{scanner_config['mqtt_user']}"
  password: "{scanner_config['mqtt_pass']}"

spoolman_url: "{scanner_config['spoolman_url']}"

moonraker_url: "{middleware_config['moonraker_url']}"

low_spool_threshold: 100
"""
    return config_yaml


def install_middleware(config_yaml):
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
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "--break-system-packages", "-r", req_file],
                       capture_output=True)
    print("  ✓ Dependencies installed")

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


def create_systemd_service():
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

def main():
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
        firmware_bin = download_asset(release, fw_suffix)
        print(f"  {C.GREEN}✓{C.RESET} Firmware downloaded ({len(firmware_bin)} bytes)")

        # Download matching bootloader
        bootloader_name = f"bootloader_{fw_suffix}.bin"
        bootloader_bin = None
        for asset in release.get("assets", []):
            if asset["name"] == bootloader_name:
                print(f"  Downloading {bootloader_name}...")
                with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as resp:
                    bootloader_bin = resp.read()
                print(f"  {C.GREEN}✓{C.RESET} Bootloader downloaded ({len(bootloader_bin)} bytes)")
                break
        if bootloader_bin is None:
            print(f"\n  ✗ Bootloader '{bootloader_name}' not found in release.")
            sys.exit(1)

        # Download matching partition table
        partitions_name = f"partitions_{fw_suffix}.bin"
        partitions_bin = None
        for asset in release.get("assets", []):
            if asset["name"] == partitions_name:
                print(f"  Downloading {partitions_name}...")
                with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as resp:
                    partitions_bin = resp.read()
                print(f"  {C.GREEN}✓{C.RESET} Partition table downloaded ({len(partitions_bin)} bytes)")
                break
        if partitions_bin is None:
            print(f"\n  ✗ Partition table '{partitions_name}' not found in release.")
            sys.exit(1)

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
            "write_flash",
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
        if mode in ("both", "scanner"):
            print(f"  Scanner:    {C.CYAN}http://spoolsense.local{C.GREEN}")
        if mode in ("both", "middleware"):
            print(f"  Middleware: {C.CYAN}systemctl status spoolsense{C.GREEN}")
    print("")
    print(f"  Tap a spool to test.{C.RESET}")
    print(f"{C.GREEN}══════════════════════════════════════════{C.RESET}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInstallation cancelled.")
        sys.exit(1)
