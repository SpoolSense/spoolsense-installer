# test_ui_validators.py — characterization tests for the pure input validators
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.ui import (
    is_valid_hostname,
    is_valid_ipv4,
    validate_host,
    validate_not_empty,
    validate_port,
    validate_ssid,
    validate_url,
)


class Ipv4Test(unittest.TestCase):
    def test_valid_addresses(self):
        for addr in ("192.168.1.1", "10.0.0.0", "255.255.255.255", "0.0.0.0"):
            self.assertTrue(is_valid_ipv4(addr), addr)

    def test_invalid_addresses(self):
        for addr in ("192.168.1", "192.168.1.1.1", "256.1.1.1", "1.2.3.04",
                     "a.b.c.d", "", "192.168..1"):
            self.assertFalse(is_valid_ipv4(addr), addr)


class HostnameTest(unittest.TestCase):
    def test_valid_hostnames(self):
        for host in ("mqtt.local", "spoolman", "my-broker.example.com", "a"):
            self.assertTrue(is_valid_hostname(host), host)

    def test_invalid_hostnames(self):
        for host in ("-bad.local", "bad-.local", "under_score", "a." + "b" * 64,
                     "", "dot..dot"):
            self.assertFalse(is_valid_hostname(host), host)


class ValidateHostTest(unittest.TestCase):
    def test_accepts_ip_and_hostname(self):
        self.assertIsNone(validate_host("192.168.1.10"))
        self.assertIsNone(validate_host("mqtt.local"))

    def test_rejects_bad_values(self):
        self.assertIsNotNone(validate_host(""))
        self.assertIsNotNone(validate_host("999.1.1.1"))
        self.assertIsNotNone(validate_host("bad_host"))


class ValidatePortTest(unittest.TestCase):
    def test_accepts_valid_range(self):
        for port in ("1", "1883", "65535"):
            self.assertIsNone(validate_port(port), port)

    def test_rejects_invalid(self):
        for port in ("0", "65536", "-1", "abc", ""):
            self.assertIsNotNone(validate_port(port), port)


class ValidateUrlTest(unittest.TestCase):
    def test_accepts_http_https_with_port_and_path(self):
        for url in ("http://spoolman.local:7912", "https://example.com",
                    "http://192.168.1.5:7125/path"):
            self.assertIsNone(validate_url(url), url)

    def test_rejects_bad_urls(self):
        for url in ("", "spoolman.local", "ftp://x", "http://", "http://bad_host",
                    "http://host:notaport"):
            self.assertIsNotNone(validate_url(url), url)

    def test_accepts_ipv6_urls(self):
        """The hand-rolled parser choked on bracketed IPv6 hosts."""
        for url in ("http://[::1]:7912", "http://[fe80::1]"):
            self.assertIsNone(validate_url(url), url)

    def test_malformed_ipv6_returns_error_not_exception(self):
        """urlsplit raises ValueError on 'http://[::1' — a typo must re-prompt,
        never traceback out of the input loop."""
        for url in ("http://[::1", "http://[abc"):
            self.assertIsNotNone(validate_url(url), url)


class SimpleValidatorsTest(unittest.TestCase):
    def test_not_empty(self):
        self.assertIsNotNone(validate_not_empty(""))
        self.assertIsNone(validate_not_empty("x"))

    def test_ssid_length_limit(self):
        self.assertIsNone(validate_ssid("MyWiFi"))
        self.assertIsNone(validate_ssid("x" * 32))
        self.assertIsNotNone(validate_ssid("x" * 33))
        self.assertIsNotNone(validate_ssid(""))


if __name__ == "__main__":
    unittest.main()
