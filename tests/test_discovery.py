# test_discovery.py — discover scanner device IDs from retained MQTT topics
#
# The scanner publishes retained spoolsense/<id>/availability (LWT) and
# spoolsense/<id>/tag/state, so idle scanners are discoverable.
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.discovery import extract_device_id, assign_device_ids


class ExtractDeviceIdTest(unittest.TestCase):
    def test_extracts_from_scanner_topics(self):
        self.assertEqual(extract_device_id("spoolsense/f3d360/availability"), "f3d360")
        self.assertEqual(extract_device_id("spoolsense/abc123/tag/state"), "abc123")

    def test_rejects_foreign_topics(self):
        for topic in ("other/f3d360/availability", "spoolsense", "spoolsense/",
                      "homeassistant/sensor/x/config"):
            self.assertIsNone(extract_device_id(topic), topic)


class AssignDeviceIdsTest(unittest.TestCase):
    def test_single_scanner_single_discovery_auto_assigns(self):
        scanners = [{"action": "toolhead", "toolhead": "T0"}]
        proposals = assign_device_ids(scanners, ["f3d360"])
        self.assertEqual(proposals, [("T0", "f3d360")])

    def test_multiple_scanners_get_positional_proposals(self):
        scanners = [{"action": "afc_lane", "lane": "lane1"},
                    {"action": "afc_lane", "lane": "lane2"},
                    {"action": "afc_lane", "lane": "lane3"}]
        proposals = assign_device_ids(scanners, ["aaa111", "bbb222"])
        self.assertEqual(proposals, [("lane1", "aaa111"), ("lane2", "bbb222"),
                                     ("lane3", None)])

    def test_shared_scanner_label_falls_back_to_action(self):
        scanners = [{"action": "happy_hare_stage"}]
        self.assertEqual(assign_device_ids(scanners, ["ccc333"]),
                         [("happy_hare_stage", "ccc333")])


if __name__ == "__main__":
    unittest.main()
