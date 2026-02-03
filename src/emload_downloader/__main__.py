from __future__ import annotations

import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path


def _find_requirements_file(start_dir: Path) -> Path | None:
    for parent in (start_dir, *start_dir.parents):
        candidate = parent / "requirements.txt"
        if candidate.is_file():
            return candidate
    return None


def _parse_requirements(path: Path) -> list[str]:
    requirements: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            target = line.split(None, 1)[1].strip()
            include_path = (path.parent / target).resolve()
            if include_path.is_file():
                requirements.extend(_parse_requirements(include_path))
            else:
                requirements.append(line)
            continue
        requirements.append(line)
    return requirements


def _base_requirement_name(req: str) -> str | None:
    if req.startswith(("-", "--")):
        return None
    name = re.split(r"[<>=!~;\[]", req, maxsplit=1)[0].strip()
    return name or None


def _module_available(name: str) -> bool:
    if importlib.util.find_spec(name) is not None:
        return True
    alt = name.replace("-", "_")
    if alt != name and importlib.util.find_spec(alt) is not None:
        return True
    return False


def _needs_install(requirements_path: Path) -> tuple[bool, list[str]]:
    missing: list[str] = []
    unresolved = False
    for req in _parse_requirements(requirements_path):
        name = _base_requirement_name(req)
        if name is None:
            unresolved = True
            continue
        if not _module_available(name):
            missing.append(name)
    return (bool(missing) or unresolved), missing


def _ensure_requirements() -> None:
    req_path = _find_requirements_file(Path(__file__).resolve().parent)
    if req_path is None:
        return
    needs_install, missing = _needs_install(req_path)
    if not needs_install:
        return
    if missing:
        print(f"Missing requirements: {', '.join(sorted(set(missing)))}. Installing...")
    else:
        print("Installing requirements...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_path)],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Failed to install requirements from {req_path}.")
        raise SystemExit(exc.returncode)
    importlib.invalidate_caches()


def main() -> None:
    _ensure_requirements()
    from emload_downloader.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
