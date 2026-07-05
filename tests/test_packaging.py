# test_packaging.py — keep pyproject.toml and __version__ from drifting
#
# Run: python3 -m unittest discover -s tests -v

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import install

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class VersionSyncTest(unittest.TestCase):
    def test_pyproject_matches_dunder_version(self):
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            match = re.search(r'^version = "([^"]+)"$', f.read(), re.MULTILINE)
        self.assertIsNotNone(match, "no version in pyproject.toml")
        self.assertEqual(match.group(1), install.__version__)


if __name__ == "__main__":
    unittest.main()
