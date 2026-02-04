from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple


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


def iter_links(path: Path) -> Iterator[Tuple[int, str]]:
    for item in _iter_json_array(path):
        if not isinstance(item, dict):
            continue
        idx = item.get("idx")
        url = item.get("url")
        if isinstance(idx, int) and isinstance(url, str):
            yield (idx, url)


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
