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
from spoolsense_installer.errors import InstallerError


def completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


GOOD_ESP32_OUTPUT = (
    "esptool v5.0\n"
    "Chip is ESP32-D0WD-V3 (revision v3.1)\n"
    "Detected flash size: 4MB\n"
)

# Real-world S3-DevKitC output: the PSRAM size appears BEFORE the flash size.
# Naive "first NN MB" parsing reads 8MB and falsely aborts a valid 16MB board.
S3_DEVKITC_PSRAM_OUTPUT = (
    "esptool v5.0\n"
    "Chip is ESP32-S3 (QFN56) (revision v0.1)\n"
    "Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)\n"
    "Manufacturer: 20\n"
    "Device: 4017\n"
    "Detected flash size: 16MB\n"
)


class VerifyFlashTest(unittest.TestCase):
    """verify_flash must fail CLOSED: no flashing unless chip and size are confirmed."""

    def _verify(self, run_result, board_key="esp32dev"):
        with mock.patch.object(firmware.subprocess, "run", return_value=run_result):
            return firmware.verify_flash("/dev/ttyUSB0", board_key)

    def test_accepts_matching_chip_and_flash(self):
        self.assertTrue(self._verify(completed(stdout=GOOD_ESP32_OUTPUT)))

    def test_psram_size_not_mistaken_for_flash_size(self):
        """S3 boards list 'Embedded PSRAM 8MB' before 'Detected flash size: 16MB' —
        the parser must anchor on the labeled flash line, not the first MB value."""
        self.assertTrue(self._verify(completed(stdout=S3_DEVKITC_PSRAM_OUTPUT),
                                     board_key="esp32s3devkitc"))

    def test_exits_when_esptool_fails(self):
        """Non-zero esptool exit must abort, even if output happens to parse."""
        with self.assertRaises(InstallerError):
            self._verify(completed(returncode=2, stdout=GOOD_ESP32_OUTPUT))

    def test_exits_when_chip_not_detected(self):
        """Unparseable output must abort — never proceed unverified."""
        with self.assertRaises(InstallerError):
            self._verify(completed(stdout="something unexpected\n"))

    def test_exits_when_flash_size_not_detected(self):
        out = "Chip is ESP32-D0WD-V3 (revision v3.1)\nno size here\n"
        with self.assertRaises(InstallerError):
            self._verify(completed(stdout=out))

    def test_exits_on_chip_mismatch(self):
        out = "Chip is ESP32-S3 (QFN56)\nDetected flash size: 4MB\n"
        with self.assertRaises(InstallerError):
            self._verify(completed(stdout=out), board_key="esp32dev")

    def test_exits_when_flash_too_small(self):
        out = "Chip is ESP32-S3 (QFN56)\nDetected flash size: 4MB\n"
        with self.assertRaises(InstallerError):
            self._verify(completed(stdout=out), board_key="esp32s3devkitc")

    def test_exits_cleanly_on_timeout(self):
        """A hung esptool must produce a friendly exit, not a traceback."""
        with mock.patch.object(
            firmware.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd="esptool", timeout=15),
        ):
            with self.assertRaises(InstallerError):
                firmware.verify_flash("/dev/ttyUSB0", "esp32dev")


def make_release_with_checksums(payload, digest):
    return {
        "tag_name": "v1.7.6",
        "assets": [
            {"name": "spoolsense_scanner_esp32dev.bin",
             "browser_download_url": "http://x/fw.bin", "size": len(payload)},
            {"name": "spoolsense_scanner_esp32dev.bin.sha256",
             "browser_download_url": "http://x/fw.bin.sha256", "size": 71},
        ],
    }


class DownloadChecksumTest(unittest.TestCase):
    """Release assets are verified against their .sha256 sidecar when present."""

    PAYLOAD = b"\xe9firmware-bytes"

    def _download(self, sha_body):
        import io

        def fake_urlopen(url, timeout=None):
            body = self.PAYLOAD if url.endswith("fw.bin") else sha_body

            class R(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R(body)

        release = make_release_with_checksums(self.PAYLOAD, sha_body)
        with mock.patch.object(firmware.urllib.request, "urlopen", fake_urlopen):
            return firmware.download_asset(release, suffix="esp32dev")

    def test_valid_checksum_accepted(self):
        import hashlib
        good = hashlib.sha256(self.PAYLOAD).hexdigest().encode() + b"  fw.bin\n"
        self.assertEqual(self._download(good), self.PAYLOAD)

    def test_corrupted_download_rejected(self):
        bad = b"0" * 64 + b"  fw.bin\n"
        with self.assertRaises(InstallerError):
            self._download(bad)

    def test_release_without_checksums_still_works(self):
        """Scanner releases don't publish .sha256 yet — absence is not fatal."""
        import io

        release = {"tag_name": "v1.7.6", "assets": [
            {"name": "spoolsense_scanner_esp32dev.bin",
             "browser_download_url": "http://x/fw.bin", "size": len(self.PAYLOAD)},
        ]}

        def fake_urlopen(url, timeout=None):
            class R(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R(self.PAYLOAD)

        with mock.patch.object(firmware.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(firmware.download_asset(release, suffix="esp32dev"),
                             self.PAYLOAD)


class FetchReleaseTest(unittest.TestCase):
    def test_version_pin_requests_tag_endpoint(self):
        """--firmware-version must fetch that exact tag, not releases/latest."""
        import io
        import json as jsonlib
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url

            class R(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R(jsonlib.dumps({"tag_name": "v1.7.4", "assets": []}).encode())

        with mock.patch.object(firmware.urllib.request, "urlopen", fake_urlopen):
            release = firmware.fetch_release(version="1.7.4")
        self.assertIn("/releases/tags/v1.7.4", seen["url"])
        self.assertEqual(release["tag_name"], "v1.7.4")

    def test_default_requests_latest(self):
        import io
        import json as jsonlib
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url

            class R(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R(jsonlib.dumps({"tag_name": "v1.7.6", "assets": []}).encode())

        with mock.patch.object(firmware.urllib.request, "urlopen", fake_urlopen):
            firmware.fetch_release()
        self.assertIn("/releases/latest", seen["url"])


class DetectUsbPortTest(unittest.TestCase):
    def test_eof_during_port_selection_aborts_cleanly(self):
        """Non-interactive stdin used to spin the selection prompt forever."""
        first = {"done": False}

        def fake_glob(pattern):
            if first["done"]:
                return []
            first["done"] = True
            return ["/dev/ttyUSB0", "/dev/ttyUSB1"]

        with mock.patch.object(firmware.glob, "glob", side_effect=fake_glob), \
             mock.patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(InstallerError):
                firmware.detect_usb_port()


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
                with self.assertRaises(InstallerError):
                    firmware.flash_firmware("/dev/ttyUSB0", "esp32dev", b"\x00" * 16,
                                            paths[0], paths[1], paths[2])


if __name__ == "__main__":
    unittest.main()
