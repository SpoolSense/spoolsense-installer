# test_firmware.py — unit tests for chip verification and flash safety behavior
#
# Run: python3 -m unittest discover -s tests -v
#
# subprocess.run is stubbed so no esptool or hardware is needed.

import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import firmware


def completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


GOOD_ESP32_OUTPUT = (
    "esptool v5.0\n"
    "Chip is ESP32-D0WD-V3 (revision v3.1)\n"
    "Detected flash size: 4MB\n"
)


class VerifyFlashTest(unittest.TestCase):
    """verify_flash must fail CLOSED: no flashing unless chip and size are confirmed."""

    def _verify(self, run_result, board_key="esp32dev"):
        with mock.patch.object(firmware.subprocess, "run", return_value=run_result):
            return firmware.verify_flash("/dev/ttyUSB0", board_key)

    def test_accepts_matching_chip_and_flash(self):
        self.assertTrue(self._verify(completed(stdout=GOOD_ESP32_OUTPUT)))

    def test_exits_when_esptool_fails(self):
        """Non-zero esptool exit must abort, even if output happens to parse."""
        with self.assertRaises(SystemExit):
            self._verify(completed(returncode=2, stdout=GOOD_ESP32_OUTPUT))

    def test_exits_when_chip_not_detected(self):
        """Unparseable output must abort — never proceed unverified."""
        with self.assertRaises(SystemExit):
            self._verify(completed(stdout="something unexpected\n"))

    def test_exits_when_flash_size_not_detected(self):
        out = "Chip is ESP32-D0WD-V3 (revision v3.1)\nno size here\n"
        with self.assertRaises(SystemExit):
            self._verify(completed(stdout=out))

    def test_exits_on_chip_mismatch(self):
        out = "Chip is ESP32-S3 (QFN56)\nDetected flash size: 4MB\n"
        with self.assertRaises(SystemExit):
            self._verify(completed(stdout=out), board_key="esp32dev")

    def test_exits_when_flash_too_small(self):
        out = "Chip is ESP32-S3 (QFN56)\nDetected flash size: 4MB\n"
        with self.assertRaises(SystemExit):
            self._verify(completed(stdout=out), board_key="esp32s3devkitc")

    def test_exits_cleanly_on_timeout(self):
        """A hung esptool must produce a friendly exit, not a traceback."""
        with mock.patch.object(
            firmware.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd="esptool", timeout=15),
        ):
            with self.assertRaises(SystemExit):
                firmware.verify_flash("/dev/ttyUSB0", "esp32dev")


class FlashFirmwareTest(unittest.TestCase):
    def test_exits_cleanly_on_timeout(self):
        """A flash that exceeds the timeout must exit with a message, not a traceback."""
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name in ("nvs.bin", "part.bin", "boot.bin"):
                p = os.path.join(d, name)
                with open(p, "wb") as f:
                    f.write(b"\x00")
                paths.append(p)

            with mock.patch.object(
                firmware.subprocess, "run",
                side_effect=subprocess.TimeoutExpired(cmd="esptool", timeout=120),
            ):
                with self.assertRaises(SystemExit):
                    firmware.flash_firmware("/dev/ttyUSB0", "esp32dev", b"\x00" * 16,
                                            paths[0], paths[1], paths[2])


if __name__ == "__main__":
    unittest.main()
