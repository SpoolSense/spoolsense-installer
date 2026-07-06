# files.py — small filesystem helpers

import os
import shutil
from typing import Optional


def backup_file(path: str) -> Optional[str]:
    """Copy an existing file to <path>.bak before modifying it.

    Returns the backup path, or None if the file doesn't exist. A prior .bak
    is overwritten — one level of undo is the contract.
    """
    if not os.path.exists(path):
        return None
    bak = path + ".bak"
    shutil.copy2(path, bak)
    return bak
