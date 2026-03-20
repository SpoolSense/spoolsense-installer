# TODO

## Bugs

- [P1] **Piped curl breaks interactive input** — `curl ... | bash` sends script to stdin, so `input()` gets EOF. Users get `EOFError`. Need to either fix `install.sh` to download then run, or document the two-step approach (download script, then run).
- [P1] **Config written to wrong path** — installer writes `config.yaml` to `~/SpoolSense/middleware/config.yaml` but the middleware expects `~/SpoolSense/config.yaml`. Users hit "Config file not found" on first start.
- [P1] **Missing watchdog dependency** — `watchdog` module not in `requirements.txt`. Middleware fails with `ModuleNotFoundError: No module named 'watchdog'` on first start.

## Improvements

- [P2] **No output during dependency install** — pip runs silently. Users don't know what's happening. Add progress messages for each install step.
- [P2] **Moonraker URL label is confusing** — users may not know what "Moonraker URL" means. Change to "Printer address" or add hint: "usually http://localhost if running on the printer, or http://<printer-ip> if running elsewhere". Default should be `http://localhost:7125`.
- [P2] **Scanner device ID discovery** — installer should ask "Do you have a SpoolSense Scanner?" and guide users to find their device ID. Currently `scanner_lane_map` must be manually added to config after install.
- [P2] **Moonraker default port** — default should be `http://localhost:7125` not `http://localhost` (Moonraker runs on port 7125).
