# preflight.py — verify the host can complete the install BEFORE any prompts

import grp
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from typing import Callable, List, NamedTuple, Tuple

from .constants import C, GITHUB_API, MIDDLEWARE_DIR
from .errors import InstallerError


class Check(NamedTuple):
    label: str
    probe: Callable[[], Tuple[bool, str]]  # -> (ok, fix_hint)
    fatal: bool = True


# ── Individual probes (each returns a closure so assembly stays declarative) ──

def check_command(cmd: str, hint: str = "") -> Callable[[], Tuple[bool, str]]:
    def probe():
        if shutil.which(cmd):
            return True, ""
        return False, hint or f"'{cmd}' not found on PATH"
    return probe


def check_module(module: str, hint: str = "") -> Callable[[], Tuple[bool, str]]:
    def probe():
        if importlib.util.find_spec(module) is not None:
            return True, ""
        return False, hint or f"pip install {module}"
    return probe


def check_esptool() -> Callable[[], Tuple[bool, str]]:
    """esptool may be a console script OR an importable module — either works."""
    def probe():
        if shutil.which("esptool") or importlib.util.find_spec("esptool"):
            return True, ""
        return False, "pip install esptool (or re-run install.sh)"
    return probe


def check_network(url: str, name: str) -> Callable[[], Tuple[bool, str]]:
    def probe():
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10):
                return True, ""
        except Exception as e:  # noqa: BLE001
            return False, f"{name} unreachable ({e}) — check your network/DNS"
    return probe


def check_serial_group() -> Callable[[], Tuple[bool, str]]:
    """On Linux, flashing needs read/write on the serial device (dialout)."""
    def probe():
        if platform.system() != "Linux":
            return True, ""
        try:
            groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
        except Exception:  # noqa: BLE001 — can't determine: don't block
            return True, ""
        if groups & {"dialout", "uucp", "root"} or os.geteuid() == 0:
            return True, ""
        return False, f"sudo usermod -aG dialout {os.environ.get('USER', '$USER')} (then re-login)"
    return probe


def check_systemd() -> Callable[[], Tuple[bool, str]]:
    def probe():
        if platform.system() != "Linux":
            return True, ""
        if shutil.which("systemctl"):
            return True, ""
        return False, "no systemctl — the service must be started manually"
    return probe


def check_venv_capable() -> Callable[[], Tuple[bool, str]]:
    """Debian ships python without ensurepip; venv creation fails mid-install."""
    def probe():
        result = subprocess.run([sys.executable, "-m", "venv", "--help"],
                                capture_output=True)
        if result.returncode == 0 and importlib.util.find_spec("ensurepip"):
            return True, ""
        return False, "sudo apt install python3-venv"
    return probe


def check_writable(path: str, label_hint: str) -> Callable[[], Tuple[bool, str]]:
    def probe():
        probe_dir = path
        while probe_dir and not os.path.exists(probe_dir):
            probe_dir = os.path.dirname(probe_dir)
        if probe_dir and os.access(probe_dir, os.W_OK):
            return True, ""
        return False, f"{label_hint} ({path}) is not writable"
    return probe


# ── Assembly + runner ────────────────────────────────────────────────────────

def preflight_checks(mode: str) -> List[Check]:
    """The checks a given install mode needs, in display order."""
    scanner = mode in ("both", "scanner")
    middleware = mode in ("both", "middleware")
    config_only = mode == "config"

    checks: List[Check] = []
    if scanner or config_only:
        checks.append(Check("NVS generator (esp-idf-nvs-partition-gen)",
                            check_module("esp_idf_nvs_partition_gen",
                                         "pip install esp-idf-nvs-partition-gen")))
    if scanner:
        checks.append(Check("esptool available", check_esptool()))
        # The API host covers both needs: release metadata AND repo clones
        checks.append(Check("GitHub reachable",
                            check_network(GITHUB_API, "api.github.com")))
        checks.append(Check("serial port permissions", check_serial_group(), fatal=False))
    if middleware:
        checks.append(Check("git available",
                            check_command("git", "sudo apt install git")))
        if not any(c.label == "GitHub reachable" for c in checks):
            checks.append(Check("GitHub reachable",
                                check_network("https://github.com", "github.com")))
        checks.append(Check("python venv support", check_venv_capable()))
        checks.append(Check("systemd available", check_systemd(), fatal=False))
        checks.append(Check("middleware install path writable",
                            check_writable(MIDDLEWARE_DIR, "install path")))
    return checks


def run_preflight(checks: List[Check]) -> None:
    """Run checks, print a status line each, abort if any fatal check fails."""
    if not checks:
        return
    print(f"\n{C.CYAN}── Preflight Checks ───────────────────{C.RESET}\n")
    failed = []
    for check in checks:
        ok, hint = check.probe()
        if ok:
            print(f"  {C.GREEN}✓{C.RESET} {check.label}")
        elif check.fatal:
            print(f"  {C.RED}✗{C.RESET} {check.label} {C.DIM}— {hint}{C.RESET}")
            failed.append(check.label)
        else:
            print(f"  {C.YELLOW}⚠{C.RESET} {check.label} {C.DIM}— {hint}{C.RESET}")

    if failed:
        print(f"\n  {C.RED}Fix the item(s) above and run the installer again.{C.RESET}")
        raise InstallerError
    print()
