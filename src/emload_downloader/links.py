from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def load_links(path: Path) -> List[Tuple[int, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Invalid links format in {path}")
    pairs: List[Tuple[int, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get("idx")
        url = item.get("url")
        if isinstance(idx, int) and isinstance(url, str):
            pairs.append((idx, url))
    if not pairs:
        raise ValueError(f"No links found in {path}")
    return sorted(pairs, key=lambda x: x[0])


def filter_range(
    pairs: Iterable[Tuple[int, str]],
    start: Optional[int],
    end: Optional[int],
) -> List[Tuple[int, str]]:
    out = []
    for idx, url in pairs:
        if start is not None and idx < start:
            continue
        if end is not None and idx > end:
            continue
        out.append((idx, url))
    return out


def existing_downloads(out_dir: Path) -> dict[int, Path]:
    existing: dict[int, Path] = {}
    if not out_dir.exists():
        return existing
    for entry in out_dir.iterdir():
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
        existing[int(prefix)] = entry
    return existing


def infer_job_name(links_path: Path) -> Optional[str]:
    try:
        rel = links_path.relative_to(Path("data") / "jobs")
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 2 and parts[-1] == "links.json":
        return parts[0]
    return None


def infer_out_dir(links_path: Path) -> Path:
    job_name = infer_job_name(links_path)
    if job_name:
        return Path("downloads") / job_name
    return Path("downloads")


def infer_state_path(links_path: Path) -> Path:
    job_name = infer_job_name(links_path)
    if job_name:
        return Path("data") / "jobs" / job_name / "state.json"
    return Path("data") / "state.json"
