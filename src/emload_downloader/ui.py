from __future__ import annotations

from typing import Callable, Optional

try:
    from rich.console import Console

    _HAS_RICH = True
except Exception:  # pragma: no cover - optional UI dependency
    _HAS_RICH = False
    Console = None  # type: ignore[assignment,misc]


_CONSOLE = Console() if _HAS_RICH else None
_OUTPUT_HANDLER: Optional[Callable[[str], None]] = None
_INPUT_HANDLER: Optional[Callable[[str], str]] = None
_ANSWER_HANDLER: Optional[Callable[[str, str], None]] = None


def has_rich() -> bool:
    return _HAS_RICH and _CONSOLE is not None and _CONSOLE.is_terminal


def console() -> Optional[Console]:
    return _CONSOLE


def set_output_handler(handler: Optional[Callable[[str], None]]) -> None:
    global _OUTPUT_HANDLER
    _OUTPUT_HANDLER = handler


def set_input_handler(handler: Optional[Callable[[str], str]]) -> None:
    global _INPUT_HANDLER
    _INPUT_HANDLER = handler


def set_answer_handler(handler: Optional[Callable[[str, str], None]]) -> None:
    global _ANSWER_HANDLER
    _ANSWER_HANDLER = handler


def print_line(text: str = "") -> None:
    if _OUTPUT_HANDLER is not None:
        _OUTPUT_HANDLER(text)
        return
    if _CONSOLE is not None:
        _CONSOLE.print(text)
        return
    print(text)


def input_line(prompt: str) -> str:
    if _INPUT_HANDLER is not None:
        return _INPUT_HANDLER(prompt)
    if _CONSOLE is not None:
        return _CONSOLE.input(prompt)
    return input(prompt)


def prompt(text: str, default: Optional[str] = None) -> str:
    if default:
        prompt_text = f"{text} [{default}]: "
    else:
        prompt_text = f"{text}: "
    value = input_line(prompt_text).strip()
    result = value or (default or "")
    if _ANSWER_HANDLER is not None:
        _ANSWER_HANDLER(text, result)
    return result


def prompt_bool(text: str, default: bool = True) -> bool:
    default_str = "y" if default else "n"
    while True:
        value = prompt(text, default_str).lower()
        if value in ("y", "yes", "true", "1"):
            return True
        if value in ("n", "no", "false", "0"):
            return False
        print_line("Invalid choice. Enter y or n.")


def prompt_int(text: str, default: Optional[int] = None) -> Optional[int]:
    default_str = "" if default is None else str(default)
    while True:
        value = prompt(text, default_str)
        if value == "":
            return None
        try:
            return int(value)
        except ValueError:
            print_line("Invalid number.")


def prompt_float(text: str, default: Optional[float] = None) -> Optional[float]:
    default_str = "" if default is None else str(default)
    while True:
        value = prompt(text, default_str)
        if value == "":
            return None
        try:
            return float(value)
        except ValueError:
            print_line("Invalid number.")
