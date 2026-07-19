# test_week2_config.py — Happy Hare support, low-spool threshold, toolheads list
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.config import validate_toolhead_list
from spoolsense_installer.middleware import generate_config
from spoolsense_installer.spoolman import EXTRA_FIELDS, fields_for_setup


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


def hh_cfg(**overrides):
    return middleware_cfg(setup_type="happy_hare",
                          scanners=[{"action": "happy_hare_stage"}], **overrides)


class HappyHareConfigTest(unittest.TestCase):
    """Middleware v1.8.6: binding goes through HH's own MMU_SPOOLMAN command;
    printer_name is legacy (tolerated but ignored) and must not be written."""

    def test_happy_hare_block_is_enabled_only(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), hh_cfg()))
        self.assertEqual(parsed["scanners"]["YOUR_DEVICE_ID"]["action"], "happy_hare_stage")
        self.assertEqual(parsed["happy_hare"], {"enabled": True})

    def test_legacy_printer_name_never_written(self):
        """Even if an old collected config carries printer_name, drop it."""
        parsed = yaml.safe_load(generate_config(scanner_cfg(),
                                                hh_cfg(printer_name="MyVoron")))
        self.assertNotIn("printer_name", parsed["happy_hare"])

    def test_num_gates_written_when_provided(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), hh_cfg(num_gates=8)))
        self.assertEqual(parsed["happy_hare"]["num_gates"], 8)

    def test_num_gates_absent_when_not_provided(self):
        """Physical select-then-scan needs no num_gates — don't write one."""
        parsed = yaml.safe_load(generate_config(scanner_cfg(), hh_cfg()))
        self.assertNotIn("num_gates", parsed["happy_hare"])

    def test_non_happy_hare_setup_has_no_block(self):
        parsed = yaml.safe_load(generate_config(scanner_cfg(), middleware_cfg()))
        self.assertNotIn("happy_hare", parsed)


class HappyHareMobileTest(unittest.TestCase):
    """v1.8.6 adds mobile.action: happy_hare_stage — phone scans assign a tag
    to any gate. Middleware requires num_gates + spoolman_url for this action
    and derives gates itself, so NO explicit toolheads list may be written."""

    def _parsed(self, **overrides):
        return yaml.safe_load(generate_config(
            scanner_cfg(), hh_cfg(mobile_enabled=True, num_gates=4, **overrides)))

    def test_mobile_action_is_happy_hare_stage(self):
        parsed = self._parsed()
        self.assertEqual(parsed["mobile"]["action"], "happy_hare_stage")
        self.assertTrue(parsed["mobile"]["enabled"])
        self.assertEqual(parsed["mobile"]["port"], 5001)
        # mobile.toolhead is meaningless for this action
        self.assertNotIn("toolhead", parsed["mobile"])

    def test_num_gates_present_with_mobile(self):
        self.assertEqual(self._parsed()["happy_hare"]["num_gates"], 4)

    def test_no_explicit_toolheads_list_for_hh(self):
        """The middleware derives G0..G{n-1} itself; an explicit toolheads:
        list is rejected for HH mobile — never write one, even defensively."""
        parsed = self._parsed(toolheads=["G0", "G1"])
        self.assertNotIn("toolheads", parsed)

    def test_malformed_gate_counts_raise_installer_error_not_valueerror(self):
        """int('garbage') must not traceback out of the generator — the CLI
        only catches InstallerError. Floats truncate silently and bool is an
        int subclass, so both are rejected rather than coerced."""
        from spoolsense_installer.errors import InstallerError
        for bad in ("garbage", "4.5", 4.9, True, [], "²"):
            with self.assertRaises(InstallerError, msg=repr(bad)):
                generate_config(scanner_cfg(), hh_cfg(mobile_enabled=True, num_gates=bad))
            # Invalid values fail even without mobile — never silently dropped
            with self.assertRaises(InstallerError, msg=repr(bad)):
                generate_config(scanner_cfg(), hh_cfg(num_gates=bad))

    def test_decimal_string_gate_count_accepted(self):
        parsed = yaml.safe_load(generate_config(
            scanner_cfg(), hh_cfg(mobile_enabled=True, num_gates="8")))
        self.assertEqual(parsed["happy_hare"]["num_gates"], 8)

    def test_hh_mobile_without_gate_count_refused(self):
        """num_gates is middleware-mandatory for the happy_hare_stage mobile
        action — the generator must fail fast rather than emit a config the
        middleware rejects at startup. (num_gates WITHOUT mobile stays legal:
        it's only mandatory for the mobile action.)"""
        from spoolsense_installer.errors import InstallerError
        for bad_gates in (None, 0, 33):
            cfg = hh_cfg(mobile_enabled=True)
            if bad_gates is not None:
                cfg["num_gates"] = bad_gates
            with self.assertRaises(InstallerError, msg=repr(bad_gates)):
                generate_config(scanner_cfg(), cfg)


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
    def test_happy_hare_adds_no_extra_fields(self):
        """Since middleware v1.8.6 the bind goes through HH's MMU_SPOOLMAN
        command and HH's mmu_server declares its own Spoolman fields
        (mmu_gate_map, printer_name) on startup. The old installer-created
        spool.mmu_gate was never read by any HH version — stop creating it.
        (Existing users' fields are left alone; we only stop creating.)"""
        self.assertEqual(fields_for_setup("happy_hare"), EXTRA_FIELDS)

    def test_all_setups_get_base_fields(self):
        for setup in ("single", "toolchanger", "afc_stage", "happy_hare", ""):
            self.assertEqual(fields_for_setup(setup), EXTRA_FIELDS, setup)


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
