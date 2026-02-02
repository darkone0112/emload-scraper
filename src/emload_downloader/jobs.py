from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


def jobs_root() -> Path:
    return Path("data") / "jobs"


def list_jobs() -> List[str]:
    root = jobs_root()
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir()])


def sanitize_job_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "job"


def default_job_name(prefix: str = "emload") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}"


def job_paths(job_name: str) -> Tuple[Path, Path, Path, Path]:
    root = jobs_root()
    job_dir = root / job_name
    links = job_dir / "links.json"
    state = job_dir / "state.json"
    out_dir = Path("downloads") / job_name
    return job_dir, links, state, out_dir


def latest_download_idx(download_dir: Path) -> Optional[int]:
    if not download_dir.exists():
        return None
    latest = None
    for entry in download_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if name == "downloaded.txt":
            continue
        if "_" not in name:
            continue
        prefix = name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        idx = int(prefix)
        if latest is None or idx > latest:
            latest = idx
    return latest
