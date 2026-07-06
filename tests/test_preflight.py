# test_preflight.py — fail early with fixes, not mid-install with tracebacks
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import preflight
from spoolsense_installer.errors import InstallerError
from spoolsense_installer.preflight import Check, preflight_checks, run_preflight


class PreflightSelectionTest(unittest.TestCase):
    def _labels(self, mode):
        return [c.label for c in preflight_checks(mode)]

    def test_scanner_mode_checks_flash_toolchain(self):
        labels = " ".join(self._labels("scanner")).lower()
        self.assertIn("esptool", labels)
        self.assertIn("nvs", labels)
        self.assertIn("github", labels)

    def test_middleware_mode_checks_host_toolchain(self):
        labels = " ".join(self._labels("middleware")).lower()
        self.assertIn("git", labels)
        self.assertIn("github", labels)
        self.assertNotIn("esptool", labels)

    def test_both_mode_is_superset(self):
        both = set(self._labels("both"))
        self.assertTrue(set(self._labels("scanner")) <= both)
        self.assertTrue(set(self._labels("middleware")) <= both)

    def test_config_mode_is_minimal(self):
        labels = " ".join(self._labels("config")).lower()
        self.assertIn("nvs", labels)
        self.assertNotIn("git ", labels)


class RunPreflightTest(unittest.TestCase):
    def test_all_ok_passes(self):
        checks = [Check("thing A", lambda: (True, "")),
                  Check("thing B", lambda: (True, ""))]
        run_preflight(checks)  # must not raise

    def test_hard_failure_aborts_before_any_prompts(self):
        checks = [Check("thing A", lambda: (True, "")),
                  Check("esptool available", lambda: (False, "pip install esptool"))]
        with self.assertRaises(InstallerError):
            run_preflight(checks)

    def test_warn_does_not_abort(self):
        checks = [Check("serial permissions", lambda: (False, "add yourself to dialout"),
                        fatal=False)]
        run_preflight(checks)  # warn only — must not raise


class IndividualChecksTest(unittest.TestCase):
    def test_module_check(self):
        ok, _ = preflight.check_module("json")()
        self.assertTrue(ok)
        ok, hint = preflight.check_module("definitely_not_a_module_xyz")()
        self.assertFalse(ok)
        self.assertTrue(hint)

    def test_command_check(self):
        ok, _ = preflight.check_command("git")()
        self.assertTrue(ok)
        ok, hint = preflight.check_command("definitely-not-a-command-xyz")()
        self.assertFalse(ok)

    def test_network_check_handles_failure(self):
        with mock.patch.object(preflight.urllib.request, "urlopen",
                               side_effect=OSError("offline")):
            ok, hint = preflight.check_network("https://api.github.com", "GitHub")()
        self.assertFalse(ok)
        self.assertTrue(hint)


if __name__ == "__main__":
    unittest.main()
