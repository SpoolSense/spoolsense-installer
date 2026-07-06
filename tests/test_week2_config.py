# test_week2_config.py — Happy Hare support, low-spool threshold, toolheads list
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.config import validate_printer_name, validate_toolhead_list
from spoolsense_installer.middleware import generate_config
from spoolsense_installer.spoolman import EXTRA_FIELDS, HAPPY_HARE_FIELDS, fields_for_setup


def scanner_cfg(**overrides):
    cfg = {"mqtt_host": "broker", "mqtt_port": 1883, "mqtt_user": "",
           "mqtt_pass": "", "spoolman_url": "http://spoolman.local:7912"}
    cfg.update(overrides)
    return cfg


def middleware_cfg(**overrides):
    cfg = {"setup_type": "single",
           "scanners": [{"action": "toolhead", "toolhead": "T0"}],
           "moonraker_url": "http://localhost:7125",
           "publish_lane_data": False}
    cfg.update(overrides)
    return cfg


class HappyHareConfigTest(unittest.TestCase):
    def test_happy_hare_setup_writes_integration_block(self):
        """Middleware v1.7.3 requires happy_hare.enabled + printer_name and a
        happy_hare_stage scanner action (middleware #83)."""
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg(
            setup_type="happy_hare",
            scanners=[{"action": "happy_hare_stage"}],
            printer_name="MyVoron",
        )))
        self.assertEqual(parsed["scanners"]["YOUR_DEVICE_ID"]["action"], "happy_hare_stage")
        self.assertEqual(parsed["happy_hare"], {"enabled": True, "printer_name": "MyVoron"})

    def test_non_happy_hare_setup_has_no_block(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg()))
        self.assertNotIn("happy_hare", parsed)


class ScannerFieldsV2Test(unittest.TestCase):
    def test_matches_firmware_required_fields_v2(self):
        """#36: the installer's base field list must match the scanner
        firmware's REQUIRED_EXTRA_FIELDS (fields version 2, 7 fields) so
        fresh installs don't depend on the firmware's first-sync path."""
        expected = {
            ("filament", "aspect"): ("text", "Aspect/Finish"),
            ("filament", "dry_temp"): ("text", "Dry Temp (C)"),
            ("filament", "dry_time_hours"): ("text", "Dry Time (hrs)"),
            ("spool", "nfc_id"): ("text", "nfc_id"),
            ("spool", "tag_format"): ("text", "Tag Format"),
            ("spool", "active_toolhead"): ("text", "active_toolhead"),
            ("spool", "nfc_link"): ("text", "nfc_link"),
        }
        actual = {(e, k): (t, n) for e, k, t, n in EXTRA_FIELDS}
        self.assertEqual(actual, expected)


class ExtraFieldsSelectionTest(unittest.TestCase):
    def test_happy_hare_fields_have_correct_types(self):
        """mmu_gate must be integer, printer_name text — Spoolman rejects
        writes to undeclared/mistyped fields with HTTP 400."""
        fields = {(e, k): t for e, k, t, _ in HAPPY_HARE_FIELDS}
        self.assertEqual(fields[("spool", "mmu_gate")], "integer")
        self.assertEqual(fields[("spool", "printer_name")], "text")

    def test_happy_hare_setup_includes_hh_fields(self):
        fields = fields_for_setup("happy_hare")
        for f in EXTRA_FIELDS + HAPPY_HARE_FIELDS:
            self.assertIn(f, fields)

    def test_other_setups_exclude_hh_fields(self):
        fields = fields_for_setup("single")
        for f in HAPPY_HARE_FIELDS:
            self.assertNotIn(f, fields)
        self.assertEqual(fields, EXTRA_FIELDS)


class LowSpoolThresholdTest(unittest.TestCase):
    def test_threshold_from_config_not_hardcoded(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg(low_spool_threshold=250)))
        self.assertEqual(parsed["low_spool_threshold"], 250)

    def test_threshold_defaults_to_100(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg()))
        self.assertEqual(parsed["low_spool_threshold"], 100)


class ToolheadStageToolheadsTest(unittest.TestCase):
    def test_toolhead_stage_writes_toolheads_list(self):
        """#24: toolhead_stage needs an explicit toolheads list so the mobile
        app picker doesn't fall back to hardcoded defaults."""
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg(
            setup_type="toolhead_stage",
            scanners=[{"action": "toolhead_stage"}],
            toolheads=["T0", "T1", "T2"],
        )))
        self.assertEqual(parsed["toolheads"], ["T0", "T1", "T2"])

    def test_no_toolheads_key_when_absent(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg()))
        self.assertNotIn("toolheads", parsed)


class YamlSafeValidatorsTest(unittest.TestCase):
    """printer_name and toolhead names are spliced into generated YAML via
    f-strings — quotes/backslashes would silently corrupt config.yaml."""

    def test_printer_name_rejects_yaml_breaking_chars(self):
        self.assertIsNone(validate_printer_name("MyVoron 2.4"))
        for bad in ('My "Voron"', "back\\slash", "", "line\nbreak"):
            self.assertIsNotNone(validate_printer_name(bad), repr(bad))

    def test_toolhead_list_allows_simple_names_only(self):
        self.assertIsNone(validate_toolhead_list("T0,T1"))
        self.assertIsNone(validate_toolhead_list("T0, extruder_1"))
        for bad in ('T0,"T1"', "T0,,T1", "", "T0,ba d"):
            self.assertIsNotNone(validate_toolhead_list(bad), repr(bad))


class MobilePanelTest(unittest.TestCase):
    def test_mobile_block_written_when_enabled(self):
        """Middleware v1.7.0 web config panel (port 5001) — installer should
        be able to enable it."""
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg(mobile_enabled=True)))
        self.assertTrue(parsed["mobile"]["enabled"])
        self.assertEqual(parsed["mobile"]["port"], 5001)

    def test_no_mobile_block_by_default(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg()))
        self.assertNotIn("mobile", parsed)


if __name__ == "__main__":
    unittest.main()
