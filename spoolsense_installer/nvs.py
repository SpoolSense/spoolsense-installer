# nvs.py — NVS partition CSV generation and binary compilation for ESP32 config

import csv
import io
import os
import subprocess
import sys
from typing import Dict, Union

from .constants import SCRIPT_DIR


def generate_nvs_csv(config: Dict[str, Union[str, int]]) -> str:
    """Generate NVS partition CSV from scanner config dict."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    writer.writerow(["key", "type", "encoding", "value"])
    writer.writerow(["spoolsense", "namespace", "", ""])

    # u16 for port (16-bit field), u8 for booleans, strings for variable-length config
    rows = [
        ("wifi_ssid", "data", "string", config["wifi_ssid"]),
        ("wifi_pass", "data", "string", config["wifi_pass"]),
        ("mqtt_host", "data", "string", config["mqtt_host"]),
        ("mqtt_port", "data", "u16", config["mqtt_port"]),
        ("mqtt_user", "data", "string", config["mqtt_user"]),
        ("mqtt_pass", "data", "string", config["mqtt_pass"]),
        ("mqtt_prefix", "data", "string", config["mqtt_prefix"]),
        ("spoolman_on", "data", "u8", config["spoolman_on"]),
        ("spoolman_url", "data", "string", config["spoolman_url"]),
        ("auto_mode", "data", "u8", config["auto_mode"]),
        ("lcd_on", "data", "u8", config["lcd_on"]),
        ("tft_on", "data", "u8", config["tft_on"]),
        ("tft_driver", "data", "string", config["tft_driver"]),
        ("led_on", "data", "u8", config["led_on"]),
        ("keypad_on", "data", "u8", config["keypad_on"]),
        ("nfc_reader", "data", "string", config["nfc_reader"]),
        ("hostname", "data", "string", config["hostname"]),
        ("moonraker_url", "data", "string", config["moonraker_url"]),
    ]
    for row in rows:
        writer.writerow(row)

    return output.getvalue()


def generate_nvs_bin(csv_content: str, output_path: str, size: int = 0x5000) -> str:
    """Generate NVS partition binary. 0x5000 (20KB) matches esp-idf default."""
    csv_path = output_path + ".csv"
    with open(csv_path, "w", newline="") as f:
        f.write(csv_content)

    # Prefer bundled generator (works offline) over installed esp-idf version
    bundled = os.path.join(SCRIPT_DIR, "lib", "nvs_partition_gen.py")
    if os.path.exists(bundled):
        cmd = [sys.executable, bundled, "generate", csv_path, output_path, hex(size)]
    else:
        cmd = [sys.executable, "-m", "esp_idf_nvs_partition_gen", "generate",
               csv_path, output_path, hex(size)]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\n  ✗ Failed to generate NVS partition: {e}")
        print(f"    Tried: {' '.join(cmd)}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"    {e.stderr.strip()}")
        sys.exit(1)

    os.remove(csv_path)
    return output_path
