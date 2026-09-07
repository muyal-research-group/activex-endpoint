from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Set


def allocate_scratch_dir(scratch_root: str, job_id: str) -> str:
    """Creates a temporary folder for one job and returns its path."""
    path = os.path.join(scratch_root, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_scratch_dir(path: str) -> None:
    """Deletes a job's temporary folder. Does nothing if it's already gone."""
    shutil.rmtree(path, ignore_errors=True)


def sweep_orphaned_scratch_dirs(scratch_root: str, active_job_ids: Set[str]) -> List[str]:
    """Deletes leftover job folders under scratch_root that don't belong to a currently active job."""
    root = Path(scratch_root)
    if not root.is_dir():
        return []

    removed = []
    for entry in root.iterdir():
        if entry.is_dir() and entry.name not in active_job_ids:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
    return removed
