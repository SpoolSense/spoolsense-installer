# ui.py — terminal input helpers and validators for interactive prompts

import getpass
from typing import Callable, Dict, Optional

from .constants import C


# ── Input helpers ────────────────────────────────────────────────────────────

def ask(prompt: str, default: Optional[str] = None, password: bool = False, validate: Optional[Callable[[str], Optional[str]]] = None) -> str:
    """Ask the user for input with optional default, password masking, and validation."""
    while True:
        suffix = f" [{default}]" if default else ""
        if password:
            value = getpass.getpass(f"{prompt}{suffix}: ")
        else:
            value = input(f"{prompt}{suffix}: ").strip()

        if not value and default is not None:
            value = str(default)

        if validate:
            err = validate(value)
            if err:
                print(f"  {C.RED}✗ {err}{C.RESET}")
                continue

        return value


def ask_choice(prompt: str, options: Dict[str, str]) -> str:
    """Ask the user to pick from a numbered list. Returns the key."""
    print(f"\n{prompt}")
    keys = list(options.keys())
    for i, key in enumerate(keys, 1):
        print(f"  [{i}] {options[key]}")

    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print(f"  Please enter 1-{len(keys)}")


def ask_yesno(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question. Returns bool."""
    hint = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{hint}]: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  Please enter y or n")


# ── Validators ───────────────────────────────────────────────────────────────

def validate_not_empty(value: str) -> Optional[str]:
    if not value:
        return "Cannot be empty"
    return None


def validate_ssid(value: str) -> Optional[str]:
    if not value:
        return "Cannot be empty"
    # IEEE 802.11 limits SSID to 32 octets max
    if len(value) > 32:
        return "WiFi SSID must be 32 characters or less"
    return None


def is_valid_ipv4(value: str) -> bool:
    """Validate an IPv4 address using logic, not regex."""
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part or not part.isdigit():
            return False
        # Reject leading zeros to avoid octal interpretation
        if len(part) > 1 and part[0] == "0":
            return False
        num = int(part)
        if num < 0 or num > 255:
            return False
    return True


def is_valid_hostname(value: str) -> bool:
    """Validate a hostname (RFC 952/1123)."""
    # DNS max total length 253 octets; max label (subdomain) length 63 octets
    if len(value) > 253:
        return False
    labels = value.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return False
        # Labels cannot start or end with hyphen per RFC
        if label[0] == "-" or label[-1] == "-":
            return False
        if not all(c.isalnum() or c == "-" for c in label):
            return False
    return True


def validate_host(value: str) -> Optional[str]:
    """Validate a value as an IPv4 address or hostname."""
    if not value:
        return "Cannot be empty"
    if all(c.isdigit() or c == "." for c in value):
        if is_valid_ipv4(value):
            return None
        return "Invalid IP address (e.g. 192.168.1.100)"
    if is_valid_hostname(value):
        return None
    return "Must be a valid IP address (e.g. 192.168.1.100) or hostname (e.g. mqtt.local)"


def validate_port(value: str) -> Optional[str]:
    """Validate a port number."""
    if not value.isdigit():
        return "Must be a number"
    port = int(value)
    # Port 0 is reserved; 65536+ overflows 16-bit field
    if port < 1 or port > 65535:
        return "Port must be between 1 and 65535"
    return None


def validate_url(value: str) -> Optional[str]:
    """Validate an HTTP/HTTPS URL with host validation."""
    if not value:
        return "Cannot be empty"
    if not value.startswith("http://") and not value.startswith("https://"):
        return "Must start with http:// or https://"
    # Extract host — strip scheme, path, and optional port
    remainder = value.split("://", 1)[1]
    host_port = remainder.split("/", 1)[0]
    host = host_port.rsplit(":", 1)[0] if ":" in host_port else host_port
    err = validate_host(host)
    if err:
        return f"Invalid host in URL: {err}"
    if ":" in host_port:
        port_str = host_port.rsplit(":", 1)[1]
        port_err = validate_port(port_str)
        if port_err:
            return f"Invalid port in URL: {port_err}"
    return None
