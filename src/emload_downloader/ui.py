from __future__ import annotations

from typing import Optional

try:
    from rich.console import Console

    _HAS_RICH = True
except Exception:  # pragma: no cover - optional UI dependency
    _HAS_RICH = False
    Console = None  # type: ignore[assignment,misc]


_CONSOLE = Console() if _HAS_RICH else None


def has_rich() -> bool:
    return _HAS_RICH and _CONSOLE is not None and _CONSOLE.is_terminal


def console() -> Optional[Console]:
    return _CONSOLE


def print_line(text: str = "") -> None:
    if _CONSOLE is not None:
        _CONSOLE.print(text)
    else:
        print(text)


def input_line(prompt: str) -> str:
    if _CONSOLE is not None:
        return _CONSOLE.input(prompt)
    return input(prompt)


def prompt(text: str, default: Optional[str] = None) -> str:
    if default:
        prompt_text = f"{text} [{default}]: "
    else:
        prompt_text = f"{text}: "
    value = input_line(prompt_text).strip()
    return value or (default or "")


def prompt_bool(text: str, default: bool = True) -> bool:
    default_str = "y" if default else "n"
    value = prompt(text, default_str).lower()
    if value in ("y", "yes", "true", "1"):
        return True
    if value in ("n", "no", "false", "0"):
        return False
    return default


def prompt_int(text: str, default: Optional[int] = None) -> Optional[int]:
    default_str = "" if default is None else str(default)
    value = prompt(text, default_str)
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        print_line("Invalid number.")
        return None


def prompt_float(text: str, default: Optional[float] = None) -> Optional[float]:
    default_str = "" if default is None else str(default)
    value = prompt(text, default_str)
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        print_line("Invalid number.")
        return None
