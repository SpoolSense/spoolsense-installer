# spoolman.py — Spoolman extra field setup and Moonraker integration config

import json
import os
import re
import time
import urllib.request

from .constants import C, MOONRAKER_CONF_PATH
from .ui import ask_yesno

# Extra fields the scanner/middleware rely on. Mirrors the scanner firmware's
# REQUIRED_EXTRA_FIELDS (SpoolmanManager.cpp, fields version 2) — keys, types,
# and display names must stay in sync so both creation paths produce identical
# fields. nfc_id enables spool lookup by tag UID; tag_format tracks the NFC
# protocol; active_toolhead tracks assignment; nfc_link stores the durable
# user-link marker (scanner #218); the filament fields carry drying metadata.
EXTRA_FIELDS = [
    ("filament", "aspect", "text", "Aspect/Finish"),
    ("filament", "dry_temp", "text", "Dry Temp (C)"),
    ("filament", "dry_time_hours", "text", "Dry Time (hrs)"),
    ("spool", "nfc_id", "text", "nfc_id"),
    ("spool", "tag_format", "text", "Tag Format"),
    ("spool", "active_toolhead", "text", "active_toolhead"),
    ("spool", "nfc_link", "text", "nfc_link"),
]

# Happy Hare binding (middleware v1.7.3+): the middleware PATCHes these onto
# spools at scan time, and Spoolman rejects writes to undeclared fields with
# HTTP 400 — so they must exist before the first bind. mmu_gate MUST be
# integer (the middleware writes the gate number).
HAPPY_HARE_FIELDS = [
    ("spool", "mmu_gate", "integer", "MMU Gate"),
    ("spool", "printer_name", "text", "Printer Name"),
]


def fields_for_setup(setup_type):
    """The Spoolman extra fields a given middleware setup type requires."""
    if setup_type == "happy_hare":
        return EXTRA_FIELDS + HAPPY_HARE_FIELDS
    return EXTRA_FIELDS


def _urlopen_with_retry(req, *, attempts: int = 3, base_delay: float = 1.0, timeout: int = 10):
    """Open a request, retrying on any error with exponential backoff.

    Returns the response body bytes and status. Re-raises the last exception if
    every attempt fails. Spoolman may still be starting during install, so a few
    retries turn a transient connection error into a success.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # urlopen only returns for 2xx; 4xx/5xx raise HTTPError.
                return resp.read(), resp.status
        except Exception as e:  # noqa: BLE001 — retry on anything (URLError, timeout, HTTPError)
            last_exc = e
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_exc


def _wait_for_spoolman(spoolman_url: str) -> bool:
    """Poll Spoolman until it responds, or a ~45s budget is exhausted.

    Returns True once reachable, False if it never comes up. Handles the common
    case where Spoolman is not fully started at the moment the installer runs.
    """
    delays = [1, 2, 4, 8, 15, 15]  # cumulative ~45s across 6 attempts
    for i, delay in enumerate(delays):
        try:
            req = urllib.request.Request(f"{spoolman_url}/api/v1/field/spool")
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception:  # noqa: BLE001
            if i < len(delays) - 1:
                print(f"  {C.DIM}… waiting for Spoolman at {spoolman_url} ({i + 1}/{len(delays)}){C.RESET}")
                time.sleep(delay)
    return False


def setup_extra_fields(spoolman_url: str, fields: list = None) -> list:
    """Create extra fields in Spoolman for tag data enrichment.

    ``fields`` defaults to the base EXTRA_FIELDS; pass fields_for_setup(...) to
    include mode-specific fields (e.g. Happy Hare's mmu_gate/printer_name).

    Returns a list of ``(entity_type, key)`` tuples that could NOT be created.
    An empty list means every field exists or was created successfully. Nothing
    is silently skipped: if Spoolman is unreachable, every field is reported as
    failed so the caller can surface a prominent warning.
    """
    if fields is None:
        fields = EXTRA_FIELDS
    if not _wait_for_spoolman(spoolman_url):
        print(f"  {C.RED}✗{C.RESET} Spoolman not reachable at {spoolman_url} — could not create fields")
        return [(entity_type, key) for entity_type, key, _, _ in fields]

    failed = []
    for entity_type, key, field_type, display_name in fields:
        try:
            req = urllib.request.Request(f"{spoolman_url}/api/v1/field/{entity_type}")
            body, _ = _urlopen_with_retry(req)
            existing = json.loads(body)
            if any(f.get("key") == key for f in existing):
                print(f"  {C.GREEN}✓{C.RESET} {entity_type}.{key} already exists")
                continue
        except Exception as e:  # noqa: BLE001
            print(f"  {C.YELLOW}!{C.RESET} Could not check {entity_type}.{key}: {e}")
            failed.append((entity_type, key))
            continue

        try:
            payload = json.dumps({"field_type": field_type, "name": display_name}).encode()
            req = urllib.request.Request(
                f"{spoolman_url}/api/v1/field/{entity_type}/{key}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Any 2xx means created; urlopen raises on 4xx/5xx so reaching here is success.
            _urlopen_with_retry(req)
            print(f"  {C.GREEN}✓{C.RESET} Created {entity_type}.{key}")
        except Exception as e:  # noqa: BLE001
            print(f"  {C.RED}✗{C.RESET} Could not create {entity_type}.{key}: {e}")
            failed.append((entity_type, key))

    return failed


def print_failed_fields_summary(spoolman_url: str, failed: list) -> None:
    """Print a prominent warning listing fields that could not be created.

    Includes copy-paste curl commands and a pointer to the --setup-fields flag so
    the failure is impossible to miss in busy install output.
    """
    if not failed:
        return

    field_meta = {(e, k): (ft, dn) for e, k, ft, dn in EXTRA_FIELDS + HAPPY_HARE_FIELDS}
    print(f"\n{C.RED}{C.BOLD}{'═' * 42}")
    print(f"  ⚠  Spoolman fields NOT created")
    print(f"{'═' * 42}{C.RESET}")
    print(f"\n  {C.YELLOW}These extra fields are missing. The scanner cannot link")
    print(f"  NFC tags to spools without them. Create them by re-running:{C.RESET}\n")
    print(f"    python3 install.py --setup-fields\n")
    print(f"  {C.YELLOW}Or create them manually with curl:{C.RESET}\n")
    for entity_type, key in failed:
        field_type, display_name = field_meta.get((entity_type, key), ("text", key))
        payload = json.dumps({"field_type": field_type, "name": display_name})
        print(f"    curl -X POST '{spoolman_url}/api/v1/field/{entity_type}/{key}' \\")
        print(f"      -H 'Content-Type: application/json' \\")
        print(f"      -d '{payload}'\n")


def setup_moonraker_spoolman(spoolman_url: str) -> str:
    """Offer to add [spoolman] section to moonraker.conf if not already present.

    Moonraker's built-in Spoolman integration tracks filament usage in real-time
    during prints. Without this, tracking won't work for UID-only tags.

    Returns one of: "added", "exists", "declined", "missing-conf", "failed".
    """
    if not os.path.exists(MOONRAKER_CONF_PATH):
        print(f"  {C.YELLOW}!{C.RESET} moonraker.conf not found at {MOONRAKER_CONF_PATH}")
        print(f"    If your moonraker.conf is in a different location, add this manually:")
        print(f"    [spoolman]")
        print(f"    server: {spoolman_url}")
        print(f"    sync_rate: 5")
        return "missing-conf"

    with open(MOONRAKER_CONF_PATH, "r") as f:
        content = f.read()

    if re.search(r'^\[spoolman\]\s*$', content, re.MULTILINE):
        print(f"  {C.GREEN}✓{C.RESET} Moonraker Spoolman config already exists — skipping")
        return "exists"

    print(f"\n  {C.YELLOW}Moonraker Spoolman Integration:{C.RESET}")
    print(f"  Moonraker can automatically track filament usage during prints")
    print(f"  and sync it to Spoolman in real-time. This is required for")
    print(f"  filament tracking on UID-only, TigerTag, and OpenSpool tags.\n")

    if not ask_yesno("Add [spoolman] to moonraker.conf?", default=True):
        print(f"  Skipped. You can add it manually later.")
        return "declined"

    # sync_rate: 5 syncs filament usage every 5 seconds during prints
    spoolman_block = f"\n[spoolman]\nserver: {spoolman_url}\nsync_rate: 5\n"
    try:
        with open(MOONRAKER_CONF_PATH, "a") as f:
            f.write(spoolman_block)
        print(f"  {C.GREEN}✓{C.RESET} Added [spoolman] to {MOONRAKER_CONF_PATH}")
        print(f"\n  {C.YELLOW}Important:{C.RESET} Restart Moonraker for this change to take effect:")
        print(f"    sudo systemctl restart moonraker\n")
        return "added"
    except PermissionError:
        print(f"  {C.RED}✗{C.RESET} Permission denied writing to {MOONRAKER_CONF_PATH}")
        print(f"    Add this manually:")
        print(f"    [spoolman]")
        print(f"    server: {spoolman_url}")
        print(f"    sync_rate: 5")
        return "failed"
    except Exception as e:
        print(f"  {C.RED}✗{C.RESET} Failed to write moonraker.conf: {e}")
        return "failed"
