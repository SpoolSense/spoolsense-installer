# discovery.py — find scanner device IDs on the MQTT broker
#
# The scanner publishes retained spoolsense/<id>/availability (LWT birth
# message) and retained spoolsense/<id>/tag/state, so a short subscription
# discovers every scanner the broker has seen — even idle ones. This replaces
# the YOUR_DEVICE_ID placeholder dance for most installs.

import time
from typing import List, Optional, Tuple

from .constants import C

_TOPICS = ("spoolsense/+/availability", "spoolsense/+/tag/state")


def extract_device_id(topic: str) -> Optional[str]:
    """spoolsense/<device_id>/... -> device_id, else None."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0] == "spoolsense" and parts[1]:
        return parts[1]
    return None


def discover_device_ids(mqtt_host: str, mqtt_port: int, username: str = "",
                        password: str = "", timeout: float = 5.0) -> List[str]:
    """Listen briefly for retained scanner topics; return sorted device IDs.

    Best-effort: returns [] on any failure (no paho, broker unreachable,
    auth rejected) — the caller falls back to placeholder IDs.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return []

    found = set()

    def on_message(client, userdata, msg):
        device_id = extract_device_id(msg.topic)
        if device_id:
            found.add(device_id)

    try:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # paho >= 2.0
        except AttributeError:
            client = mqtt.Client()
        if username:
            client.username_pw_set(username, password)
        client.on_message = on_message
        client.connect(mqtt_host, mqtt_port, keepalive=10)
        for topic in _TOPICS:
            client.subscribe(topic)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            client.loop(timeout=0.5)
        client.disconnect()
    except Exception:  # noqa: BLE001 — discovery is a convenience, never fatal
        return []
    return sorted(found)


def assign_device_ids(scanners: List[dict], discovered: List[str]) -> List[Tuple[str, Optional[str]]]:
    """Positional proposals: [(scanner_label, proposed_id_or_None), ...].

    Labels come from the scanner's lane/toolhead (or action for shared
    scanners) so the user can sanity-check which physical scanner maps where.
    """
    proposals = []
    for i, s in enumerate(scanners):
        label = s.get("lane") or s.get("toolhead") or s.get("action", f"scanner {i + 1}")
        proposals.append((label, discovered[i] if i < len(discovered) else None))
    return proposals


def prompt_device_ids(scanners: List[dict], scanner_config: dict, ask) -> None:
    """Discover IDs and let the user confirm/edit one per scanner, in place.

    Mutates each scanner dict with a ``device_id`` key when the user accepts
    or types one; leaves it absent (placeholder) when skipped.
    """
    discovered = discover_device_ids(
        scanner_config.get("mqtt_host", ""),
        int(scanner_config.get("mqtt_port", 1883)),
        scanner_config.get("mqtt_user", ""),
        scanner_config.get("mqtt_pass", ""),
    )
    if discovered:
        print(f"\n  {C.GREEN}✓{C.RESET} Found {len(discovered)} scanner(s) on MQTT: "
              f"{', '.join(discovered)}")
    else:
        print(f"\n  {C.DIM}No scanners found on MQTT (yet) — you can enter IDs now")
        print(f"  or fill in YOUR_DEVICE_ID in config.yaml later.{C.RESET}")

    for scanner, (label, proposal) in zip(scanners, assign_device_ids(scanners, discovered)):
        # With a proposal, Enter accepts it and '-' skips (retained topics can
        # be stale); without one, Enter keeps the placeholder.
        if proposal:
            value = ask(f"Device ID for {label} ('-' = fill in later)",
                        default=proposal)
        else:
            value = ask(f"Device ID for {label} (blank = fill in later)", default="")
        value = value.strip()
        if value and value != "-":
            scanner["device_id"] = value
