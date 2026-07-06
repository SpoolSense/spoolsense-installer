# test_venv.py — middleware runs from its own virtualenv (issue #21)
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.middleware import ensure_venv, service_content, venv_python


class VenvPathTest(unittest.TestCase):
    def test_python_path_inside_venv(self):
        p = venv_python("/home/pi/SpoolSense/.venv")
        self.assertTrue(p.startswith("/home/pi/SpoolSense/.venv"))
        self.assertIn("python", os.path.basename(p))


class EnsureVenvTest(unittest.TestCase):
    def test_creates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            venv_dir = os.path.join(d, ".venv")
            python = ensure_venv(venv_dir)
            self.assertTrue(os.path.exists(python), python)
            mtime = os.path.getmtime(python)
            # Second call must reuse, not rebuild
            self.assertEqual(ensure_venv(venv_dir), python)
            self.assertEqual(os.path.getmtime(python), mtime)


class ServiceContentTest(unittest.TestCase):
    def test_execstart_uses_given_python(self):
        """The systemd unit must run the middleware with the venv python —
        system-python units break once deps live in the venv (#21)."""
        content = service_content("/home/pi/SpoolSense/.venv/bin/python")
        self.assertIn("ExecStart=/home/pi/SpoolSense/.venv/bin/python", content)
        self.assertIn("[Unit]", content)
        self.assertIn("Restart=on-failure", content)


if __name__ == "__main__":
    unittest.main()
