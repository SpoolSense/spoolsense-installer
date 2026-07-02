# test_spoolman.py — unit tests for Spoolman extra-field creation
#
# Run: python3 -m unittest discover -s tests -v
#
# urllib.request.urlopen is stubbed so no real network access happens. time.sleep
# is patched out so retry/backoff paths run instantly.

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer import spoolman
from spoolsense_installer.spoolman import setup_extra_fields, EXTRA_FIELDS

URL = "http://spoolman.local:7912"


class FakeResp:
    """Minimal context-manager stand-in for an http.client.HTTPResponse."""

    def __init__(self, body=b"[]", status=200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def make_urlopen(router):
    """Build a fake urlopen that delegates to `router(req) -> FakeResp` (may raise)."""

    def _fake(req, timeout=None):
        return router(req)

    return _fake


class SetupExtraFieldsTest(unittest.TestCase):
    def setUp(self):
        # Never actually sleep during retry/backoff.
        p = mock.patch.object(spoolman.time, "sleep", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, router):
        with mock.patch.object(spoolman.urllib.request, "urlopen", make_urlopen(router)):
            return setup_extra_fields(URL)

    def test_readiness_timeout_marks_all_fields_failed(self):
        """If Spoolman never responds, every field is reported failed (not skipped)."""

        def router(req):
            raise ConnectionRefusedError("down")

        failed = self._run(router)
        self.assertEqual(failed, [(e, k) for e, k, _, _ in EXTRA_FIELDS])

    def test_all_created_success(self):
        """Readiness ok, all fields missing then POSTed -> no failures."""

        def router(req):
            method = req.get_method()
            if method == "GET":
                return FakeResp(body=b"[]", status=200)
            return FakeResp(body=b"{}", status=200)  # POST create

        self.assertEqual(self._run(router), [])

    def test_non_200_2xx_counts_as_success(self):
        """A 201 Created on POST must not be treated as a failure."""

        def router(req):
            if req.get_method() == "GET":
                return FakeResp(body=b"[]", status=200)
            return FakeResp(body=b"", status=201)

        self.assertEqual(self._run(router), [])

    def test_existing_field_skipped(self):
        """A field that already exists is a success, and no POST is attempted."""
        posted = []

        def router(req):
            if req.get_method() == "GET":
                # Report every requested field already exists.
                return FakeResp(body=json.dumps(
                    [{"key": k} for _, k, _, _ in EXTRA_FIELDS]
                ).encode(), status=200)
            posted.append(req.full_url)
            return FakeResp(status=200)

        self.assertEqual(self._run(router), [])
        self.assertEqual(posted, [])  # nothing created

    def test_post_failure_is_reported(self):
        """Readiness + GET ok but POST always fails -> field in failed list."""

        def router(req):
            if req.get_method() == "GET":
                return FakeResp(body=b"[]", status=200)
            raise OSError("post boom")

        failed = self._run(router)
        self.assertEqual(failed, [(e, k) for e, k, _, _ in EXTRA_FIELDS])

    def test_retry_succeeds_after_transient_failures(self):
        """Two transient POST errors then success -> field created, no failure."""
        # readiness passes on first call; then per-field GET ok; POST fails twice.
        state = {"post_calls": 0}

        def router(req):
            if req.get_method() == "GET":
                return FakeResp(body=b"[]", status=200)
            state["post_calls"] += 1
            if state["post_calls"] <= 2:
                raise TimeoutError("transient")
            return FakeResp(status=200)

        # Only test the first field to keep POST-call bookkeeping simple.
        with mock.patch.object(spoolman, "EXTRA_FIELDS", [EXTRA_FIELDS[0]]):
            failed = self._run(router)
        self.assertEqual(failed, [])
        self.assertEqual(state["post_calls"], 3)  # 2 failures + 1 success


class WaitForSpoolmanTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(spoolman.time, "sleep", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_returns_true_when_reachable(self):
        with mock.patch.object(spoolman.urllib.request, "urlopen",
                               make_urlopen(lambda req: FakeResp())):
            self.assertTrue(spoolman._wait_for_spoolman(URL))

    def test_returns_false_when_never_reachable(self):
        def boom(req):
            raise ConnectionRefusedError("down")

        with mock.patch.object(spoolman.urllib.request, "urlopen", make_urlopen(boom)):
            self.assertFalse(spoolman._wait_for_spoolman(URL))


if __name__ == "__main__":
    unittest.main()
