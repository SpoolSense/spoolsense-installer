# errors.py — typed installer failures

class InstallerError(Exception):
    """A fatal install failure.

    Raise sites print their user guidance first, then raise (optionally with a
    short summary message). The CLI entry point catches this and exits 1 —
    library modules must never call sys.exit themselves, so callers and tests
    can handle failures and cleanup can run.
    """
