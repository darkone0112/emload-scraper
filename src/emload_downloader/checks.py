from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from emload_downloader.links import existing_downloads, filter_range, load_links


@dataclass
class CheckResult:
    total: int
    present: int
    missing: List[int]
    extra: List[int]


def check_downloads(
    links_path: Path,
    out_dir: Path,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> CheckResult:
    links = filter_range(load_links(links_path), start, end)
    expected = {idx for idx, _ in links}
    existing = existing_downloads(out_dir)
    if start is not None or end is not None:
        existing = {
            idx: path
            for idx, path in existing.items()
            if (start is None or idx >= start) and (end is None or idx <= end)
        }
    present = sorted(idx for idx in expected if idx in existing)
    missing = sorted(idx for idx in expected if idx not in existing)
    extra = sorted(idx for idx in existing.keys() if idx not in expected)
    return CheckResult(
        total=len(expected),
        present=len(present),
        missing=missing,
        extra=extra,
    )
