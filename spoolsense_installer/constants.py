# constants.py — shared constants and terminal color codes

import os

GITHUB_API = "https://api.github.com/repos/SpoolSense/spoolsense_scanner/releases/latest"
SPOOLMAN_NFC_FIELD_KEY = "nfc_id"
MIDDLEWARE_REPO = "https://github.com/SpoolSense/spoolsense_middleware.git"
MIDDLEWARE_DIR = os.path.expanduser("~/SpoolSense")
MOONRAKER_CONF_PATH = os.path.expanduser("~/printer_data/config/moonraker.conf")

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Bootloader offset: esp32 uses 0x1000, esp32s3 uses 0x0 (rev2 bootloader in ROM)
BOARDS = {
    "esp32dev": ("ESP32-WROOM DevKit (4MB)", "esp32", "esp32dev", 4 * 1024 * 1024, 0x1000),
    "esp32s3zero": ("ESP32-S3-Zero by Waveshare (4MB)", "esp32s3", "esp32s3zero", 4 * 1024 * 1024, 0x0),
    "esp32s3devkitc": ("ESP32-S3-DevKitC-1-N16R8 (16MB+8MB PSRAM)", "esp32s3", "esp32s3devkitc", 16 * 1024 * 1024, 0x0),
}


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
