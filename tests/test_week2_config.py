# test_week2_config.py — Happy Hare support, low-spool threshold, toolheads list
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        yaml_text = generate_config(scanner_cfg(), middleware_cfg(
            setup_type="happy_hare",
            scanners=[{"action": "happy_hare_stage"}],
            printer_name="MyVoron",
        ))
        self.assertIn('action: "happy_hare_stage"', yaml_text)
        self.assertIn("happy_hare:", yaml_text)
        self.assertIn("enabled: true", yaml_text)
        self.assertIn('printer_name: "MyVoron"', yaml_text)

    def test_non_happy_hare_setup_has_no_block(self):
        yaml_text = generate_config(scanner_cfg(), middleware_cfg())
        self.assertNotIn("happy_hare:", yaml_text)


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
        yaml_text = generate_config(scanner_cfg(), middleware_cfg(low_spool_threshold=250))
        self.assertIn("low_spool_threshold: 250", yaml_text)

    def test_threshold_defaults_to_100(self):
        yaml_text = generate_config(scanner_cfg(), middleware_cfg())
        self.assertIn("low_spool_threshold: 100", yaml_text)


class ToolheadStageToolheadsTest(unittest.TestCase):
    def test_toolhead_stage_writes_toolheads_list(self):
        """#24: toolhead_stage needs an explicit toolheads list so the mobile
        app picker doesn't fall back to hardcoded defaults."""
        yaml_text = generate_config(scanner_cfg(), middleware_cfg(
            setup_type="toolhead_stage",
            scanners=[{"action": "toolhead_stage"}],
            toolheads=["T0", "T1", "T2"],
        ))
        self.assertIn("toolheads:", yaml_text)
        self.assertIn('- "T0"', yaml_text)
        self.assertIn('- "T2"', yaml_text)

    def test_no_toolheads_key_when_absent(self):
        yaml_text = generate_config(scanner_cfg(), middleware_cfg())
        self.assertNotIn("toolheads:", yaml_text)


class MobilePanelTest(unittest.TestCase):
    def test_mobile_block_written_when_enabled(self):
        """Middleware v1.7.0 web config panel (port 5001) — installer should
        be able to enable it."""
        yaml_text = generate_config(scanner_cfg(), middleware_cfg(mobile_enabled=True))
        self.assertIn("mobile:", yaml_text)
        self.assertIn("enabled: true", yaml_text)
        self.assertIn("port: 5001", yaml_text)

    def test_no_mobile_block_by_default(self):
        yaml_text = generate_config(scanner_cfg(), middleware_cfg())
        self.assertNotIn("mobile:", yaml_text)


if __name__ == "__main__":
    unittest.main()
