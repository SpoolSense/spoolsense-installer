# Spoolman extra-field creation robustness — design

Date: 2026-07-01
Issue: #17 — Spoolman extra field creation can silently fail or be skipped

## Problem

`setup_extra_fields()` in `spoolsense_installer/spoolman.py` can silently skip
creating the `nfc_id` extra field (and the others) in several ways:

1. **Spoolman unreachable during install** — the GET existence check throws, the
   code prints a warning and `continue`s past the field without creating it.
   Spoolman is often not fully started at the moment the installer runs, so this
   is the root cause of the reported failure.
2. **POST creation fails** — a warning is printed but there is no retry.
3. **No way to re-run just this step** — a user who hit the bug must manually
   `curl` the Spoolman API or run a full reinstall.
4. **Warnings scroll past** — the failure is easy to miss in busy install output.

Latent bug: `setup_extra_fields()` only prints a success line when
`resp.status == 200`, so a `201 Created` response looks like nothing happened.

Out of scope (these live in the separate scanner / middleware repos): having the
scanner or middleware verify required fields exist on startup.

## Goals

- Do not silently skip field creation. Every field either succeeds or is reported
  as failed.
- Tolerate a Spoolman that is still starting up (retry / wait).
- Make any failure impossible to miss (prominent end-of-run summary with manual
  remediation steps).
- Provide a standalone way to re-run field creation without a full reinstall.

## Design

### 1. Retry + readiness wait (`spoolman.py`)

- `_urlopen_with_retry(req, *, attempts, base_delay)` — helper that calls
  `urllib.request.urlopen`, retrying on any exception with exponential-ish
  backoff. Re-raises the last exception if all attempts fail.
- `_wait_for_spoolman(url)` — preflight that polls a light endpoint
  (`/api/v1/field/spool`) until reachable or a budget (~45s, 6 attempts with
  growing delay) is exhausted. Returns `bool`. Handles the "Spoolman not fully
  started during install" case.
- Per-field GET and POST use `_urlopen_with_retry` (a couple of attempts) to
  absorb transient blips.

### 2. Track failures instead of swallowing them

- `setup_extra_fields(spoolman_url) -> list[tuple[str, str]]` returns the list of
  `(entity_type, key)` pairs that could **not** be created (empty list = success).
- If `_wait_for_spoolman` fails, all fields are marked failed (not silently
  skipped) and returned.
- Fix the success gate: treat any 2xx (i.e. any response `urlopen` returns
  without raising) as success, not only `200`.
- Existing-field detection is unchanged: if the field already exists, it is a
  success, not a failure.

### 3. Loud end-of-run summary (`install.py`)

- `main()` captures the failed-fields list from `setup_extra_fields`.
- If non-empty, after the normal completion message print a prominent red boxed
  warning as the **last** thing the user sees, containing:
  - which fields failed,
  - the exact `curl` command(s) to create each field manually,
  - a note to re-run with `python3 install.py --setup-fields`.
- A shared helper builds this summary so the `--setup-fields` path reuses it.

### 4. Standalone `--setup-fields` flag (`install.py`)

- Add `argparse`.
- `install.py --setup-fields` runs only field creation:
  - URL comes from `--spoolman-url URL` if provided, otherwise prompt via
    `ui.ask(..., validate=validate_url)`.
  - Runs `setup_extra_fields`, prints the same summary, exits with status 0 on
    full success or 1 if any field failed.
- `install.sh` already forwards `"$@"`, so
  `curl -sL … | bash -s -- --setup-fields` works.

## Testing

`tests/` is currently empty. Add `tests/test_spoolman.py` using stdlib
`unittest` (repo has no test deps) with `urllib.request.urlopen` stubbed via
`unittest.mock` — no real network. Cases:

- retry succeeds after N transient failures,
- readiness-wait timeout marks **all** fields as failed,
- a 2xx-but-not-200 response counts as success,
- an already-existing field is skipped (counts as success, not failure),
- a persistent POST failure is reported in the returned failed list.

## Files touched

- `spoolsense_installer/spoolman.py` — retry helper, readiness wait, failure
  tracking, 2xx fix.
- `install.py` — argparse, `--setup-fields` mode, loud summary, capture failures.
- `tests/test_spoolman.py` — new.
