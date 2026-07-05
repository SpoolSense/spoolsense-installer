# test_middleware.py — unit tests for config generation and Klipper macro installation
#
# Run: python3 -m unittest discover -s tests -v

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoolsense_installer.middleware import copy_klipper_macros, generate_config

ALL_SETUP_TYPES = ("afc_stage", "afc_lane", "toolhead_stage", "toolchanger", "single",
                   "happy_hare")

MACRO_FILES = ("spoolsense.cfg", "spoolman_macros.cfg", "toolhead_macros_example.cfg")


def make_src_dir(root):
    """Create a fake middleware klipper/ dir with all shipped macro files."""
    src = os.path.join(root, "klipper")
    os.makedirs(src)
    for name in MACRO_FILES:
        with open(os.path.join(src, name), "w") as f:
            f.write(f"# {name} from repo\n")
    return src


class CopyKlipperMacrosTest(unittest.TestCase):
    def _copy(self, setup_type, prepare_dst=None, src_files=MACRO_FILES):
        with tempfile.TemporaryDirectory() as root:
            src = make_src_dir(root)
            for name in MACRO_FILES:
                if name not in src_files:
                    os.unlink(os.path.join(src, name))
            dst = os.path.join(root, "printer_config")
            os.makedirs(dst)
            if prepare_dst:
                prepare_dst(dst)
            results = copy_klipper_macros(setup_type, src_dir=src, dst_dir=dst)
            return results, {n for n in os.listdir(dst)}

    def test_spoolsense_cfg_copied_for_every_setup_type(self):
        """UPDATE_TAG drives filament deduction in ALL modes (#30) — the macro
        file must be installed regardless of setup type."""
        for setup_type in ALL_SETUP_TYPES:
            results, files = self._copy(setup_type)
            self.assertIn("spoolsense.cfg", files,
                          f"spoolsense.cfg missing for {setup_type}")
            self.assertEqual(results["spoolsense.cfg"], "copied")

    def test_spoolman_macros_copied_for_toolhead_modes_only(self):
        """SET_ACTIVE_SPOOL macros are for direct-toolhead setups; AFC manages
        its own Spoolman state (#27)."""
        for setup_type in ("single", "toolchanger", "toolhead_stage"):
            _, files = self._copy(setup_type)
            self.assertIn("spoolman_macros.cfg", files, setup_type)
        for setup_type in ("afc_stage", "afc_lane", "happy_hare"):
            _, files = self._copy(setup_type)
            self.assertNotIn("spoolman_macros.cfg", files, setup_type)

    def test_toolhead_example_copied_for_multi_tool_modes_only(self):
        for setup_type in ("toolchanger", "toolhead_stage"):
            _, files = self._copy(setup_type)
            self.assertIn("toolhead_macros_example.cfg", files, setup_type)
        for setup_type in ("single", "afc_stage", "afc_lane", "happy_hare"):
            _, files = self._copy(setup_type)
            self.assertNotIn("toolhead_macros_example.cfg", files, setup_type)

    def test_spoolsense_cfg_is_refreshed_on_reinstall(self):
        """spoolsense.cfg is SpoolSense-owned — reinstall updates it."""

        def prepare(dst):
            with open(os.path.join(dst, "spoolsense.cfg"), "w") as f:
                f.write("# old version\n")

        with tempfile.TemporaryDirectory() as root:
            src = make_src_dir(root)
            dst = os.path.join(root, "printer_config")
            os.makedirs(dst)
            prepare(dst)
            copy_klipper_macros("single", src_dir=src, dst_dir=dst)
            with open(os.path.join(dst, "spoolsense.cfg")) as f:
                self.assertIn("from repo", f.read())

    def test_user_editable_macros_never_overwritten(self):
        """spoolman_macros/toolhead_macros are templates users customize — an
        existing copy must be left untouched."""
        marker = "# user customized\n"

        def prepare(dst):
            for name in ("spoolman_macros.cfg", "toolhead_macros_example.cfg"):
                with open(os.path.join(dst, name), "w") as f:
                    f.write(marker)

        with tempfile.TemporaryDirectory() as root:
            src = make_src_dir(root)
            dst = os.path.join(root, "printer_config")
            os.makedirs(dst)
            prepare(dst)
            results = copy_klipper_macros("toolchanger", src_dir=src, dst_dir=dst)
            for name in ("spoolman_macros.cfg", "toolhead_macros_example.cfg"):
                with open(os.path.join(dst, name)) as f:
                    self.assertEqual(f.read(), marker, name)
                self.assertEqual(results[name], "kept-existing")

    def test_missing_source_reported_not_fatal(self):
        results, files = self._copy("single", src_files=("spoolsense.cfg",))
        self.assertEqual(results["spoolsense.cfg"], "copied")
        self.assertEqual(results["spoolman_macros.cfg"], "missing-source")


class GenerateConfigTest(unittest.TestCase):
    def test_topic_prefix_matches_compiled_firmware(self):
        scanner_config = {
            "mqtt_host": "broker", "mqtt_port": 1883,
            "mqtt_user": "", "mqtt_pass": "", "spoolman_url": "",
        }
        middleware_config = {
            "setup_type": "single",
            "scanners": [{"action": "toolhead", "toolhead": "T0"}],
            "moonraker_url": "http://localhost:7125",
            "publish_lane_data": False,
        }
        yaml_text = generate_config(scanner_config, middleware_config)
        self.assertIn('scanner_topic_prefix: "spoolsense"', yaml_text)
        self.assertIn('action: "toolhead"', yaml_text)


if __name__ == "__main__":
    unittest.main()
