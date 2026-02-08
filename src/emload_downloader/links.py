from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple


@dataclass(frozen=True)
class LinkEntry:
    idx: int
    url: str
    path: Tuple[str, ...] = ()
    name: Optional[str] = None


def _parse_link_entry(item: object) -> Optional[LinkEntry]:
    if not isinstance(item, dict):
        return None
    idx = item.get("idx")
    url = item.get("url")
    if not isinstance(idx, int) or not isinstance(url, str):
        return None
    raw_path = item.get("path")
    path: Tuple[str, ...] = ()
    if isinstance(raw_path, list):
        parts = []
        for part in raw_path:
            if isinstance(part, str):
                stripped = part.strip()
                if stripped:
                    parts.append(stripped)
        path = tuple(parts)
    name = item.get("name")
    clean_name = name.strip() if isinstance(name, str) else ""
    meta_name: Optional[str] = clean_name or None
    return LinkEntry(idx=idx, url=url, path=path, name=meta_name)


def load_link_entries(path: Path) -> List[LinkEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Invalid links format in {path}")
    entries = []
    for item in data:
        entry = _parse_link_entry(item)
        if entry is not None:
            entries.append(entry)
    if not entries:
        raise ValueError(f"No links found in {path}")
    return sorted(entries, key=lambda e: e.idx)


def load_links(path: Path) -> List[Tuple[int, str]]:
    return [(entry.idx, entry.url) for entry in load_link_entries(path)]


def _iter_json_array(path: Path, chunk_size: int = 65536) -> Iterator[object]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as f:
        buffer = ""
        eof = False

        def read_more() -> None:
            nonlocal buffer, eof
            chunk = f.read(chunk_size)
            if chunk == "":
                eof = True
                return
            buffer += chunk

        read_more()
        pos = 0

        while True:
            while pos < len(buffer) and buffer[pos].isspace():
                pos += 1
            if pos < len(buffer):
                if buffer[pos] != "[":
                    raise ValueError(f"Invalid links format in {path}")
                pos += 1
                break
            if eof:
                raise ValueError(f"Invalid links format in {path}")
            read_more()

        while True:
            while True:
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if pos < len(buffer):
                    break
                if eof:
                    return
                read_more()

            if buffer[pos] == "]":
                return

            while True:
                try:
                    obj, next_pos = decoder.raw_decode(buffer, pos)
                    pos = next_pos
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError(f"Invalid links format in {path}")
                    read_more()

            yield obj

            while True:
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if pos < len(buffer):
                    break
                if eof:
                    raise ValueError(f"Invalid links format in {path}")
                read_more()

            if buffer[pos] == ",":
                pos += 1
            elif buffer[pos] == "]":
                return
            else:
                if eof:
                    raise ValueError(f"Invalid links format in {path}")

            if pos > 262144:
                buffer = buffer[pos:]
                pos = 0


def iter_link_entries(path: Path) -> Iterator[LinkEntry]:
    for item in _iter_json_array(path):
        entry = _parse_link_entry(item)
        if entry is not None:
            yield entry


def iter_links(path: Path) -> Iterator[Tuple[int, str]]:
    for entry in iter_link_entries(path):
        yield (entry.idx, entry.url)


def iter_links_range(
    path: Path,
    start: Optional[int],
    end: Optional[int],
) -> Iterator[Tuple[int, str]]:
    for idx, url in iter_links(path):
        if start is not None and idx < start:
            continue
        if end is not None and idx > end:
            continue
        yield (idx, url)


def iter_link_entries_range(
    path: Path,
    start: Optional[int],
    end: Optional[int],
) -> Iterator[LinkEntry]:
    for entry in iter_link_entries(path):
        idx = entry.idx
        if start is not None and idx < start:
            continue
        if end is not None and idx > end:
            continue
        yield entry


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
    for entry in out_dir.rglob("*"):
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
