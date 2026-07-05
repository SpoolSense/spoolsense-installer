# test_dedup.py — single sources of truth for boards and the [spoolman] block
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import spoolman
from spoolsense_installer.config import board_choices
from spoolsense_installer.constants import BOARDS
from spoolsense_installer.spoolman import setup_moonraker_spoolman


class BoardChoicesTest(unittest.TestCase):
    def test_derived_from_constants(self):
        """The board prompt must be generated from BOARDS — a second
        hand-maintained list is how the C3 label drifted last time."""
        choices = board_choices()
        for key, (display, *_rest) in BOARDS.items():
            self.assertIn(key, choices)
            self.assertIn(display, choices[key])
        self.assertIn("other", choices)
        self.assertEqual(set(choices), set(BOARDS) | {"other"})


class MoonrakerSpoolmanTest(unittest.TestCase):
    URL = "http://spoolman.local:7912"

    def _run(self, initial_content, answer=True):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "moonraker.conf")
            if initial_content is not None:
                with open(conf, "w") as f:
                    f.write(initial_content)
            with mock.patch.object(spoolman, "ask_yesno", return_value=answer):
                status = setup_moonraker_spoolman(self.URL, conf_path=conf)
            content = ""
            if os.path.exists(conf):
                with open(conf) as f:
                    content = f.read()
            return status, content

    def test_appends_block(self):
        status, content = self._run("[server]\n")
        self.assertEqual(status, "added")
        self.assertIn("[spoolman]", content)
        self.assertIn(f"server: {self.URL}", content)
        self.assertIn("sync_rate: 5", content)

    def test_existing_section_untouched(self):
        original = "[spoolman]\nserver: http://old:7912\n"
        status, content = self._run(original)
        self.assertEqual(status, "exists")
        self.assertEqual(content, original)

    def test_declined_and_missing(self):
        status, content = self._run("[server]\n", answer=False)
        self.assertEqual(status, "declined")
        self.assertEqual(content, "[server]\n")
        status, _ = self._run(None)
        self.assertEqual(status, "missing-conf")


if __name__ == "__main__":
    unittest.main()
