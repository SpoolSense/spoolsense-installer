# firmware.py — GitHub release download, ESP32 chip verification, and firmware flashing

import glob
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from typing import Optional

from .constants import BOARDS, C, GITHUB_API


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
    """Download a release asset by exact name or firmware suffix."""
    # Firmware naming convention: board suffix matches PlatformIO env names
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
            # Verify completeness via GitHub metadata
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
        # ttyUSB = standard CDC serial; ttyACM = USB ACM (Nordic chips)
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]
    elif system == "Darwin":
        # macOS: usbserial (FT232), usbmodem (CDC), SLAB (Silabs)
        patterns = ["/dev/cu.usbserial-*", "/dev/cu.usbmodem*", "/dev/cu.SLAB_USB*"]
    elif system == "Windows":
        # Windows COM ports detected by esptool's platform-specific logic
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

    # Prevent flashing wrong board variant (e.g. esp32s3 firmware on esp32 chip)
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

    # Flash size varies: 4MB minimum for most, 16MB for S3-DevKitC (PSRAM)
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


def flash_firmware(port: Optional[str], board_key: str, firmware_bin: bytes,
                   nvs_bin_path: str, partitions_bin_path: str, bootloader_bin_path: str) -> None:
    """Flash bootloader + partition table + NVS config + firmware to the ESP32."""
    print(f"\n  Flashing firmware...")
    print(f"{C.YELLOW}  ⚠ {C.RESET} Do NOT disconnect the USB cable during flashing!\n")

    cmd = ["esptool"]
    if port:
        cmd.extend(["--port", port])

    board_name, chip, _, _, bootloader_offset = BOARDS[board_key]
    cmd.extend(["--chip", chip, "write-flash"])

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fw_file:
        fw_file.write(firmware_bin)
        fw_path = fw_file.name

    try:
        # Flash order: bootloader → partition table → NVS → app firmware
        # Addresses: bootloader offset varies by chip; 0x8000 (partitions), 0x9000 (NVS), 0x10000 (app)
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
