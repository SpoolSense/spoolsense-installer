# test_nvs.py — unit tests for NVS partition CSV generation
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.nvs import generate_nvs_csv


def make_scanner_config(**overrides):
    """A scanner config dict as collect_scanner_config() returns it."""
    config = {
        "board": "esp32dev",
        "hostname": "spoolsense",
        "wifi_ssid": "MyWiFi",
        "wifi_pass": "secret",
        "mqtt_host": "192.168.1.10",
        "mqtt_port": 1883,
        "mqtt_user": "",
        "mqtt_pass": "",
        "spoolman_on": 1,
        "spoolman_url": "http://spoolman.local:7912",
        "auto_mode": 0,
        "lcd_on": 0,
        "tft_on": 0,
        "tft_driver": "st7789",
        "led_on": 1,
        "keypad_on": 0,
        "nfc_reader": "pn5180",
        "moonraker_url": "",
    }
    config.update(overrides)
    return config


class GenerateNvsCsvTest(unittest.TestCase):
    def test_does_not_write_dead_mqtt_prefix_key(self):
        """The firmware never reads mqtt_prefix (its topic prefix is compile-time);
        the installer must not prompt for it or write it to NVS."""
        csv_text = generate_nvs_csv(make_scanner_config())
        self.assertNotIn("mqtt_prefix", csv_text)

    def test_namespace_and_expected_keys_present(self):
        csv_text = generate_nvs_csv(make_scanner_config())
        self.assertIn("spoolsense,namespace,,", csv_text)
        for key in ("wifi_ssid", "wifi_pass", "mqtt_host", "mqtt_port", "mqtt_user",
                    "mqtt_pass", "spoolman_on", "spoolman_url", "auto_mode", "lcd_on",
                    "tft_on", "tft_driver", "led_on", "keypad_on", "nfc_reader",
                    "hostname", "moonraker_url"):
            self.assertIn(f"{key},data,", csv_text)

    def test_values_with_commas_are_escaped(self):
        """A comma in the SSID must not corrupt the CSV row structure (#19)."""
        csv_text = generate_nvs_csv(make_scanner_config(wifi_ssid="My,WiFi"))
        self.assertIn('"My,WiFi"', csv_text)


if __name__ == "__main__":
    unittest.main()
