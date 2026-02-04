from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from emload_downloader.ui import prompt, print_line


def _display_path(path: Path, base: Optional[Path]) -> str:
    if base is None:
        return str(path)
    if path == base:
        return str(base)
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _select_path(
    candidates: list[Path],
    label: str,
    default: Optional[Path],
    base: Optional[Path] = None,
) -> Path:
    while True:
        if candidates:
            for i, path in enumerate(candidates, 1):
                print_line(f"{i}. {_display_path(path, base)}")
        default_str = str(default) if default is not None else ""
        choice = prompt(f"{label} (number or path)", default_str)
        if choice == "" and default is not None:
            return default
        if choice == "":
            print_line("Value required.")
            continue
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
            print_line("Invalid selection.")
            continue
        return Path(choice)


def _is_cookie_json(path: Path) -> bool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if isinstance(raw, dict):
        raw = raw.get("cookies") or raw.get("Cookies") or raw.get("data") or raw.get("items") or []
    if not isinstance(raw, list):
        return False
    for item in raw:
        if isinstance(item, dict) and "name" in item and "value" in item:
            return True
    return False


def find_cookie_files(data_dir: Path = Path("data")) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted(
        [p for p in data_dir.rglob("*.json") if p.is_file() and _is_cookie_json(p)]
    )


def choose_cookie_path(
    default: Optional[Path] = None,
    data_dir: Path = Path("data"),
) -> Path:
    if default is None:
        default = data_dir / "emload_cookies.json"
    candidates = find_cookie_files(data_dir)
    if len(candidates) == 1:
        choice = candidates[0]
        print_line(f"Using cookies: {_display_path(choice, data_dir)}")
        return choice
    if not candidates:
        return Path(prompt("Cookies path", str(default)))
    return _select_path(candidates, "Cookies path", default, base=data_dir)


def find_state_files(data_dir: Path = Path("data")) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted([p for p in data_dir.rglob("state.json") if p.is_file()])


def choose_state_path(
    default: Optional[Path] = None,
    data_dir: Path = Path("data"),
) -> Path:
    candidates = find_state_files(data_dir)
    if default is None:
        default = data_dir / "state.json"
    if len(candidates) == 1:
        choice = candidates[0]
        print_line(f"Using state: {_display_path(choice, data_dir)}")
        return choice
    if not candidates:
        return Path(prompt("State path", str(default)))
    return _select_path(candidates, "State path", default, base=data_dir)


def choose_output_dir(
    default: Optional[Path] = None,
    root: Path = Path("downloads"),
) -> Path:
    if default is None:
        default = root
    candidates: list[Path] = []
    if root.exists():
        candidates.append(root)
        candidates.extend(sorted([p for p in root.iterdir() if p.is_dir()]))
    if len(candidates) == 1:
        choice = candidates[0]
        print_line(f"Using output dir: {choice}")
        return choice
    if not candidates:
        return Path(prompt("Output dir", str(default)))
    return _select_path(candidates, "Output dir", default, base=root)


def choose_links_output_path(
    default: Optional[Path] = None,
    data_dir: Path = Path("data"),
) -> Path:
    if default is None:
        default = data_dir / "links.json"
    candidates: list[Path] = []
    if data_dir.exists():
        candidates = sorted([p for p in data_dir.rglob("*.json") if p.is_file()])
    if not candidates:
        return Path(prompt("Output path", str(default)))
    return _select_path(candidates, "Output path", default, base=data_dir)
