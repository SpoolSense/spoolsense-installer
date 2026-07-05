# test_release_pinning.py — pin the middleware clone to the latest release tag
#
# Uses real throwaway git repos (no network). Run:
#   python3 -m unittest discover -s tests -v

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import middleware
from spoolsense_installer.middleware import latest_release_tag, pin_repo_to_release


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, check=True).stdout.strip()


def make_repo(root):
    """Repo with: commit A (tag v1.7.3) -> commit B (master head, = origin/master)."""
    repo = os.path.join(root, "mw")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "master", repo], check=True)
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "f.txt"), "w") as f:
        f.write("a\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-qm", "A")
    git(repo, "tag", "v1.7.3")
    with open(os.path.join(repo, "f.txt"), "w") as f:
        f.write("b\n")
    git(repo, "commit", "-aqm", "B")
    # Simulate a fresh clone: origin/master ref at the same commit as HEAD
    git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    return repo


class PinRepoTest(unittest.TestCase):
    def test_pins_clean_clone_back_to_release_tag(self):
        with tempfile.TemporaryDirectory() as root:
            repo = make_repo(root)
            self.assertTrue(pin_repo_to_release(repo, "v1.7.3"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"),
                             git(repo, "rev-parse", "v1.7.3"))
            # Must stay on the master BRANCH (update_manager requires it)
            self.assertEqual(git(repo, "rev-parse", "--abbrev-ref", "HEAD"), "master")

    def test_refuses_when_local_commits_diverge(self):
        """Never destroy user work: only pin when HEAD == origin/master."""
        with tempfile.TemporaryDirectory() as root:
            repo = make_repo(root)
            with open(os.path.join(repo, "local.txt"), "w") as f:
                f.write("user work\n")
            git(repo, "add", "local.txt")
            git(repo, "commit", "-qm", "user local commit")  # HEAD ahead of origin/master
            head_before = git(repo, "rev-parse", "HEAD")
            self.assertFalse(pin_repo_to_release(repo, "v1.7.3"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), head_before)

    def test_refuses_dirty_worktree(self):
        """reset --hard would destroy uncommitted edits even when HEAD ==
        origin/master — a dirty worktree must block pinning."""
        with tempfile.TemporaryDirectory() as root:
            repo = make_repo(root)
            edited = os.path.join(repo, "f.txt")
            with open(edited, "w") as f:
                f.write("uncommitted user edit\n")
            head_before = git(repo, "rev-parse", "HEAD")
            self.assertFalse(pin_repo_to_release(repo, "v1.7.3"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), head_before)
            with open(edited) as f:
                self.assertEqual(f.read(), "uncommitted user edit\n")

    def test_refuses_unknown_tag(self):
        with tempfile.TemporaryDirectory() as root:
            repo = make_repo(root)
            head_before = git(repo, "rev-parse", "HEAD")
            self.assertFalse(pin_repo_to_release(repo, "v9.9.9"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), head_before)


class LatestReleaseTagTest(unittest.TestCase):
    def test_returns_tag_name(self):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"tag_name": "v1.7.3"}).encode()

        with mock.patch.object(middleware.urllib.request, "urlopen",
                               return_value=FakeResp()):
            self.assertEqual(latest_release_tag(), "v1.7.3")

    def test_returns_none_on_error(self):
        with mock.patch.object(middleware.urllib.request, "urlopen",
                               side_effect=OSError("offline")):
            self.assertIsNone(latest_release_tag())


if __name__ == "__main__":
    unittest.main()
