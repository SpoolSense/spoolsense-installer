# firmware.py — GitHub release download, ESP32 chip verification, and firmware flashing

import glob
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from typing import Optional

from .constants import BOARDS, C, GITHUB_API, GITHUB_RELEASES_API
from .errors import InstallerError

# 16MB boards (S3-DevKitC) can exceed the old 2-minute budget at low baud rates
FLASH_TIMEOUT = 300


def fetch_release(version: str = "") -> dict:
    """Fetch release info from GitHub: a specific tag if given, else latest.

    ``version`` accepts "1.7.4" or "v1.7.4".
    """
    if version:
        tag = version if version.startswith("v") else f"v{version}"
        url = f"{GITHUB_RELEASES_API}/tags/{tag}"
        print(f"\n  Fetching release {tag}...")
    else:
        url = GITHUB_API
        print("\n  Fetching latest release...")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"\n  ✗ Failed to fetch release info: {e}")
        if version:
            print(f"    Check that release {version} exists:")
            print("    https://github.com/SpoolSense/spoolsense_scanner/releases")
        else:
            print("    Check your network connection and try again.")
        raise InstallerError


def _verify_sha256(release: dict, asset_name: str, data: bytes) -> None:
    """Verify data against the asset's .sha256 sidecar, if the release has one.

    Fails closed on mismatch. Absence is tolerated — scanner releases predate
    checksum publishing (tracked upstream) — so this hardens automatically
    once the scanner's release workflow ships sidecars.
    """
    sidecar = next((a for a in release.get("assets", [])
                    if a["name"] == f"{asset_name}.sha256"), None)
    if sidecar is None:
        return
    try:
        with urllib.request.urlopen(sidecar["browser_download_url"], timeout=30) as resp:
            expected = resp.read().decode().split()[0].strip().lower()
    except Exception as e:  # noqa: BLE001
        print(f"\n  ✗ Could not download checksum for {asset_name}: {e}")
        raise InstallerError

    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        print(f"\n  ✗ Checksum mismatch for {asset_name}!")
        print(f"    Expected: {expected}")
        print(f"    Got:      {actual}")
        print("    The download may be corrupted or tampered with. Aborting.")
        raise InstallerError
    print(f"  {C.GREEN}✓{C.RESET} SHA256 verified: {asset_name}")


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
                raise InstallerError
            # Verify completeness via GitHub metadata
            if expected_size and len(data) != expected_size:
                print(f"\n  ✗ Download incomplete: got {len(data)} bytes, expected {expected_size}")
                raise InstallerError
            _verify_sha256(release, target_name, data)
            return data

    print(f"\n  ✗ Asset '{target_name}' not found in release {release.get('tag_name', '?')}")
    print("    Available assets:")
    for asset in release.get("assets", []):
        print(f"      {asset['name']}")
    raise InstallerError


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
        raise InstallerError

    if len(ports) == 1:
        print(f"  Found: {ports[0]}")
        return ports[0]

    print("  Multiple USB devices found:")
    for i, port in enumerate(ports, 1):
        print(f"    [{i}] {port}")
    while True:
        try:
            choice = input("  Select port: ").strip()
        except EOFError:
            # Non-interactive stdin — never spin on a prompt nobody can answer
            print("\n  ✗ Cannot select a port: input is not interactive.")
            raise InstallerError
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                return ports[idx]
        except ValueError:
            pass


def verify_flash(port: Optional[str], board_key: str) -> bool:
    """Verify the connected chip matches the selected board and has sufficient flash.

    Fails CLOSED: if the chip or flash size cannot be positively confirmed, the
    installer aborts rather than flashing an unverified device.
    """
    board_name, expected_chip, _, min_flash, _ = BOARDS[board_key]
    print(f"\n  Verifying chip...")

    cmd = ["esptool"]
    if port:
        cmd.extend(["--port", port])
    cmd.append("flash-id")

    try:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (FileNotFoundError, OSError):
            cmd[0] = sys.executable
            cmd.insert(1, "-m")
            cmd.insert(2, "esptool")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        print(f"\n  ✗ Chip verification timed out — the device is not responding.")
        print("    Unplug and reconnect the USB cable, then try again.")
        print("    If using an ESP32-S3/C3, hold BOOT while connecting.")
        raise InstallerError

    output = result.stdout + result.stderr

    if result.returncode != 0:
        print(f"\n  ✗ Could not read chip info (esptool exited with {result.returncode}).")
        tail = output.strip().splitlines()[-3:]
        for line in tail:
            print(f"    {line}")
        print("    Check the USB cable and serial permissions, then try again.")
        raise InstallerError

    # Prevent flashing wrong board variant (e.g. esp32s3 firmware on esp32 chip).
    # Match the chip FAMILY exactly — substring checks would accept esp32s3 for esp32.
    family_match = re.search(r"Chip is (ESP32(?:-S2|-S3|-C3|-C6|-H2|-P4)?)", output)
    display_match = re.search(r"Chip is (ESP32[^\s]*)", output)
    if not family_match:
        print(f"\n  ✗ Could not identify the connected chip from esptool output.")
        print("    Refusing to flash an unverified device.")
        print("    Unplug and reconnect the USB cable, then try again.")
        raise InstallerError

    detected_family = family_match.group(1).lower().replace("-", "")
    detected_display = display_match.group(1) if display_match else family_match.group(1)
    if detected_family != expected_chip:
        print(f"\n  ✗ Chip mismatch!")
        print(f"    Selected board: {board_name} (expects {expected_chip})")
        print(f"    Detected chip:  {detected_display}")
        print(f"    Please select the correct board type and try again.")
        raise InstallerError
    print(f"  Chip: {detected_display} ✓")

    # Flash size varies: 4MB minimum for most, 16MB for S3-DevKitC (PSRAM).
    # Anchor on the labeled line — S3 output lists "Embedded PSRAM 8MB" in
    # Features BEFORE "Detected flash size: 16MB", and a bare first-match
    # would read the PSRAM size and falsely reject valid boards.
    flash_match = re.search(r"flash size:?\s*(\d+)\s*MB", output, re.IGNORECASE)
    if not flash_match:
        print(f"\n  ✗ Could not determine flash size from esptool output.")
        print("    Refusing to flash an unverified device.")
        print("    Unplug and reconnect the USB cable, then try again.")
        raise InstallerError

    flash_bytes = int(flash_match.group(1)) * 1024 * 1024
    if flash_bytes < min_flash:
        print(f"\n  ✗ Flash too small!")
        print(f"    Required: {min_flash // (1024*1024)}MB")
        print(f"    Detected: {flash_match.group(1)}MB")
        print(f"    This board cannot run SpoolSense firmware.")
        raise InstallerError
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
            try:
                result = subprocess.run(cmd, timeout=FLASH_TIMEOUT)
            except (FileNotFoundError, OSError):
                cmd[0] = sys.executable
                cmd.insert(1, "-m")
                cmd.insert(2, "esptool")
                result = subprocess.run(cmd, timeout=FLASH_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"\n  ✗ Flashing timed out after {FLASH_TIMEOUT // 60} minutes.")
            print("    The device may be in a bad state — power-cycle it and")
            print("    run the installer again.")
            raise InstallerError

        if result.returncode != 0:
            print("\n  ✗ Flash failed!")
            print("")
            print("  If the device is unresponsive:")
            print("    1. Hold the BOOT button on the ESP32")
            print("    2. Press and release the RESET button")
            print("    3. Release the BOOT button")
            print("    4. Run the installer again")
            raise InstallerError

        print("\n  ✓ Firmware flashed successfully!")
    finally:
        os.unlink(fw_path)
