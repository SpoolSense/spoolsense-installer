# test_update_manager.py — [update_manager spoolsense] moonraker.conf entry (#16)
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import middleware
from spoolsense_installer.middleware import setup_moonraker_update_manager


class UpdateManagerTest(unittest.TestCase):
    def _run(self, initial_content, answer=True):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "moonraker.conf")
            if initial_content is not None:
                with open(conf, "w") as f:
                    f.write(initial_content)
            with mock.patch.object(middleware, "ask_yesno", return_value=answer):
                status = setup_moonraker_update_manager(conf_path=conf)
            content = ""
            if os.path.exists(conf):
                with open(conf) as f:
                    content = f.read()
            return status, content

    def test_appends_stable_channel_git_repo_block(self):
        """The Mainsail update panel needs a git_repo entry; channel stable
        keeps users on tagged releases."""
        status, content = self._run("[server]\nhost: 0.0.0.0\n")
        self.assertEqual(status, "added")
        self.assertIn("[update_manager spoolsense]", content)
        self.assertIn("type: git_repo", content)
        self.assertIn("channel: stable", content)
        self.assertIn("primary_branch: master", content)
        self.assertIn("managed_services: spoolsense", content)
        self.assertIn("origin: https://github.com/SpoolSense/spoolsense_middleware.git", content)
        # Venv options let Moonraker update python deps alongside the repo
        self.assertIn("virtualenv:", content)
        self.assertIn("requirements: middleware/requirements.txt", content)

    def test_venv_aware_section_left_untouched(self):
        original = ("[update_manager spoolsense]\ntype: git_repo\n"
                    "virtualenv: /home/pi/SpoolSense/.venv\n# user tweaked\n")
        status, content = self._run(original)
        self.assertEqual(status, "exists")
        self.assertEqual(content, original)

    def test_pre_venv_section_upgraded_in_place(self):
        """v1.3.0 wrote the block without virtualenv/requirements — without
        migration, Moonraker updates stop updating python deps once the
        middleware runs from a venv."""
        original = ("[server]\nhost: 0.0.0.0\n\n"
                    "[update_manager spoolsense]\n"
                    "type: git_repo\n"
                    "channel: stable\n"
                    "path: /home/pi/SpoolSense\n"
                    "primary_branch: master\n"
                    "managed_services: spoolsense\n\n"
                    "[power printer]\ntype: gpio\n")
        status, content = self._run(original)
        self.assertEqual(status, "upgraded")
        self.assertIn("virtualenv:", content)
        self.assertIn("requirements: middleware/requirements.txt", content)
        # Only ONE spoolsense section, and neighbors untouched
        self.assertEqual(content.count("[update_manager spoolsense]"), 1)
        self.assertIn("[server]\nhost: 0.0.0.0", content)
        self.assertIn("[power printer]\ntype: gpio", content)

    def test_pre_venv_upgrade_declined_leaves_file_alone(self):
        original = "[update_manager spoolsense]\ntype: git_repo\n"
        status, content = self._run(original, answer=False)
        self.assertEqual(status, "declined")
        self.assertEqual(content, original)

    def test_declined_makes_no_change(self):
        original = "[server]\n"
        status, content = self._run(original, answer=False)
        self.assertEqual(status, "declined")
        self.assertEqual(content, original)

    def test_missing_conf_reported(self):
        status, _ = self._run(None)
        self.assertEqual(status, "missing-conf")


if __name__ == "__main__":
    unittest.main()
