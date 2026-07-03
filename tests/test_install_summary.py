# test_install_summary.py — the final message must reflect what actually happened
#
# Run: python3 -m unittest discover -s tests -v

import contextlib
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install


def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


def render(mode="both", steps=()):
    scanner_config = {"hostname": "spoolsense"}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        install.print_completion_message(mode, scanner_config, list(steps))
    return strip_ansi(buf.getvalue())


class CompletionMessageTest(unittest.TestCase):
    def test_all_ok_claims_success(self):
        out = render(steps=[("Scanner firmware flashed", "ok", ""),
                            ("Spoolman extra fields", "ok", "")])
        self.assertIn("SpoolSense is installed!", out)
        self.assertIn("✓ Scanner firmware flashed", out)

    def test_failed_step_must_not_claim_success(self):
        """The old installer printed "installed!" even when steps failed."""
        out = render(steps=[("Scanner firmware flashed", "ok", ""),
                            ("systemd service", "fail", "sudo required")])
        self.assertNotIn("SpoolSense is installed!", out)
        self.assertIn("✗ systemd service", out)
        self.assertIn("sudo required", out)

    def test_warn_step_flags_action_needed(self):
        out = render(steps=[("config.yaml written", "ok", ""),
                            ("Replace YOUR_DEVICE_ID in config.yaml", "warn", "")])
        self.assertIn("action needed", out)
        self.assertIn("⚠ Replace YOUR_DEVICE_ID", out)

    def test_skipped_step_rendered_as_skipped(self):
        out = render(steps=[("Spoolman extra fields", "skip", "Spoolman disabled")])
        self.assertIn("− Spoolman extra fields", out)
        self.assertIn("SpoolSense is installed!", out)

    def test_scanner_mode_shows_device_url(self):
        out = render(mode="scanner", steps=[("Scanner firmware flashed", "ok", "")])
        self.assertIn("http://spoolsense.local", out)


if __name__ == "__main__":
    unittest.main()
