# spoolman.py — Spoolman extra field setup and Moonraker integration config

import json
import os
import re
import urllib.request

from .constants import C, MOONRAKER_CONF_PATH
from .ui import ask_yesno


def setup_extra_fields(spoolman_url: str) -> None:
    """Create extra fields in Spoolman for tag data enrichment.

    Text fields allow the scanner to write tag UID, format, and filament properties.
    nfc_id enables spool lookup by tag UID; tag_format tracks which NFC protocol was used.
    """
    fields = [
        ("spool", "nfc_id", "text", "NFC Tag ID"),
        ("spool", "tag_format", "text", "Tag Format"),
        ("filament", "aspect", "text", "Aspect/Finish"),
        ("filament", "dry_temp", "text", "Dry Temp (°C)"),
        ("filament", "dry_time_hours", "text", "Dry Time (hrs)"),
    ]

    for entity_type, key, field_type, display_name in fields:
        try:
            req = urllib.request.Request(f"{spoolman_url}/api/v1/field/{entity_type}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                existing = json.loads(resp.read())
                if any(f.get("key") == key for f in existing):
                    print(f"  {C.GREEN}✓{C.RESET} {entity_type}.{key} already exists")
                    continue
        except Exception as e:
            print(f"  {C.YELLOW}!{C.RESET} Could not check {entity_type}.{key}: {e}")
            continue

        try:
            body = json.dumps({"field_type": field_type, "name": display_name}).encode()
            req = urllib.request.Request(
                f"{spoolman_url}/api/v1/field/{entity_type}/{key}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    print(f"  {C.GREEN}✓{C.RESET} Created {entity_type}.{key}")
        except Exception as e:
            print(f"  {C.YELLOW}!{C.RESET} Could not create {entity_type}.{key}: {e}")


def setup_moonraker_spoolman(spoolman_url: str) -> None:
    """Offer to add [spoolman] section to moonraker.conf if not already present.

    Moonraker's built-in Spoolman integration tracks filament usage in real-time
    during prints. Without this, tracking won't work for UID-only tags.
    """
    if not os.path.exists(MOONRAKER_CONF_PATH):
        print(f"  {C.YELLOW}!{C.RESET} moonraker.conf not found at {MOONRAKER_CONF_PATH}")
        print(f"    If your moonraker.conf is in a different location, add this manually:")
        print(f"    [spoolman]")
        print(f"    server: {spoolman_url}")
        print(f"    sync_rate: 5")
        return

    with open(MOONRAKER_CONF_PATH, "r") as f:
        content = f.read()

    if re.search(r'^\[spoolman\]\s*$', content, re.MULTILINE):
        print(f"  {C.GREEN}✓{C.RESET} Moonraker Spoolman config already exists — skipping")
        return

    print(f"\n  {C.YELLOW}Moonraker Spoolman Integration:{C.RESET}")
    print(f"  Moonraker can automatically track filament usage during prints")
    print(f"  and sync it to Spoolman in real-time. This is required for")
    print(f"  filament tracking on UID-only, TigerTag, and OpenSpool tags.\n")

    if not ask_yesno("Add [spoolman] to moonraker.conf?", default=True):
        print(f"  Skipped. You can add it manually later.")
        return

    # sync_rate: 5 syncs filament usage every 5 seconds during prints
    spoolman_block = f"\n[spoolman]\nserver: {spoolman_url}\nsync_rate: 5\n"
    try:
        with open(MOONRAKER_CONF_PATH, "a") as f:
            f.write(spoolman_block)
        print(f"  {C.GREEN}✓{C.RESET} Added [spoolman] to {MOONRAKER_CONF_PATH}")
        print(f"\n  {C.YELLOW}Important:{C.RESET} Restart Moonraker for this change to take effect:")
        print(f"    sudo systemctl restart moonraker\n")
    except PermissionError:
        print(f"  {C.RED}✗{C.RESET} Permission denied writing to {MOONRAKER_CONF_PATH}")
        print(f"    Add this manually:")
        print(f"    [spoolman]")
        print(f"    server: {spoolman_url}")
        print(f"    sync_rate: 5")
    except Exception as e:
        print(f"  {C.RED}✗{C.RESET} Failed to write moonraker.conf: {e}")
