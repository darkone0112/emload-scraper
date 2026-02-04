from __future__ import annotations

import signal
import sys
import termios
import threading
from collections import deque
import math
import time
from typing import Deque, Optional

try:
    from rich.console import Console, RenderableType
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _HAS_RICH = True
except Exception:  # pragma: no cover - optional UI dependency
    _HAS_RICH = False
    Console = None  # type: ignore[assignment,misc]
    RenderableType = object  # type: ignore[assignment,misc]
    Layout = None  # type: ignore[assignment,misc]
    Live = None  # type: ignore[assignment,misc]
    Panel = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]
    Text = None  # type: ignore[assignment,misc]

from emload_downloader.ui import set_answer_handler, set_input_handler, set_output_handler


class Dashboard:
    def __init__(self, menu_items: list[str]) -> None:
        self.menu_items = menu_items
        self.console = Console() if _HAS_RICH else None
        self.layout = Layout() if _HAS_RICH else None
        if self.layout is not None:
            self.layout.split_row(
                Layout(name="menu", size=34),
                Layout(name="content"),
            )
        self.history_lines: Deque[str] = deque(maxlen=400)
        self.config_values: dict[str, str] = {}
        self.download_renderable: Optional[RenderableType] = None
        self.download_title = "Download"
        self.live: Optional[Live] = None
        self.lock = threading.Lock()
        self.active = False
        self.in_prompt = False
        self.prompt_text = ""
        self.prompt_key = ""
        self.prompt_default = ""
        self.input_buffer = ""
        self.refresh_stop = threading.Event()
        self.refresh_pause = threading.Event()
        self.refresh_thread: Optional[threading.Thread] = None
        self.resize_pending = threading.Event()
        self._prev_sigwinch = None
        self.menu_width = 36
        self.top_height = 10
        self.emload_height = 16
        self.downloads_height = 16
        self.downloads_width = 80
        self.last_size: Optional[tuple[int, int]] = None
        self.last_layout_key: Optional[tuple[int, int, int, int]] = None
        self.last_run_config: dict[str, str] = {}
        self.run_start_ts: Optional[float] = None
        self.settings_order = [
            "Links path",
            "Cookies path",
            "Output dir",
            "State path",
            "Range",
            "Workers",
            "Delay seconds",
            "Retries",
            "Daily limit GB",
            "Headless browser",
        ]
        self.settings_lookup = {key.lower(): key for key in self.settings_order}

    def start(self) -> None:
        if not _HAS_RICH or self.layout is None or self.console is None:
            return
        self.console.clear()
        self._ensure_layout()
        self.refresh_stop.clear()
        self.refresh_pause.clear()
        self.live = Live(
            self.layout,
            console=self.console,
            refresh_per_second=6,
            screen=True,
            auto_refresh=False,
        )
        self.live.__enter__()
        self.active = True
        self._refresh()
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        self._prev_sigwinch = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self._handle_resize)
        set_output_handler(self.log)
        set_input_handler(self.prompt)
        set_answer_handler(self.set_config)

    def stop(self) -> None:
        set_output_handler(None)
        set_input_handler(None)
        set_answer_handler(None)
        self.refresh_stop.set()
        if self.refresh_thread:
            self.refresh_thread.join(timeout=1)
            self.refresh_thread = None
        if self.live:
            self.live.__exit__(None, None, None)
            self.live = None
        self.active = False
        self.refresh_pause.clear()
        if self._prev_sigwinch is not None:
            signal.signal(signal.SIGWINCH, self._prev_sigwinch)
            self._prev_sigwinch = None

    def prompt(self, prompt_text: str) -> str:
        with self.lock:
            if not self.active or self.console is None:
                return input(prompt_text)
            if not sys.stdin.isatty():
                return input(prompt_text)
            self.refresh_pause.set()
            self.in_prompt = True
            self.prompt_text = prompt_text
            key, default = self._parse_prompt(prompt_text)
            self.prompt_key = key or ""
            self.prompt_default = default or ""
            self.input_buffer = ""
            self._update_emload()
            self._refresh()

        try:
            value = self._readline_raw()
        finally:
            with self.lock:
                self.in_prompt = False
                self.prompt_text = ""
                self.prompt_key = ""
                self.prompt_default = ""
                self.input_buffer = ""
                self._update_emload()
                self.refresh_pause.clear()
                self._refresh()
        return value

    def log(self, text: str) -> None:
        with self.lock:
            if text == "":
                self.history_lines.append("")
            else:
                for line in text.splitlines():
                    if self.run_start_ts is not None:
                        elapsed = time.time() - self.run_start_ts
                        prefix = f"[+{elapsed:06.1f}s] "
                        self.history_lines.append(f"{prefix}{line}")
                    else:
                        self.history_lines.append(line)
            self._refresh()

    def set_right(self, renderable: Optional[RenderableType], title: str = "Download") -> None:
        with self.lock:
            if self.config_values:
                self.last_run_config = dict(self.config_values)
            self.download_renderable = renderable
            self.download_title = title
            self.run_start_ts = time.time()
            self._refresh()

    def set_config(self, key: str, value: str) -> None:
        with self.lock:
            if value.strip() == "":
                return
            normalized = self._normalize_key(key)
            if not normalized:
                return
            if normalized == "Range":
                if value.strip().lower() in {"b", "s"}:
                    return
                self._set_range_value(key, value)
                self._refresh()
                return
            self.config_values[normalized] = value
            self._refresh()

    def clear_config(self) -> None:
        with self.lock:
            self.config_values.clear()
            self._refresh()

    def _render_menu_table(self) -> Table:
        table = Table(show_header=True, header_style="bold", title="Menu", expand=True)
        table.add_column("#", no_wrap=True, justify="right")
        table.add_column("Action", overflow="fold")
        for i, item in enumerate(self.menu_items, 1):
            table.add_row(str(i), item)
        table.add_row("0", "Exit")
        return table

    def _render_settings_table(self) -> RenderableType:
        table = Table(show_header=True, header_style="bold", title="Run Settings", expand=True)
        table.add_column("Setting", no_wrap=True)
        table.add_column("Value", overflow="fold")
        settings = self.config_values or self.last_run_config
        for key in self.settings_order:
            value = settings.get(key, "—")
            table.add_row(key, value)
        return table

    def _render_input_panel(self) -> RenderableType:
        if self.in_prompt:
            label = (self.prompt_key or self.prompt_text).rstrip(":").strip()
            value = self.input_buffer or self.prompt_default
            prompt_line = f"{label}:"
            input_line = f"> {value}"
            text = Text(f"{prompt_line}\n{input_line}")
        else:
            text = Text("Waiting for input.", style="dim")
        return Panel(text, title="Input", expand=True)

    def _render_emload_panel(self) -> RenderableType:
        menu_table = self._render_menu_table()
        settings_table = self._render_settings_table()
        input_panel = self._render_input_panel()

        menu_width = self.menu_width
        top_height = self.top_height

        top = Layout()
        top.split_row(
            Layout(name="menu", size=menu_width),
            Layout(name="settings"),
        )
        top["menu"].update(menu_table)
        top["settings"].update(settings_table)

        body = Layout()
        controls_panel = Panel(top, title="Controls", expand=True)
        body.split_column(
            Layout(controls_panel, size=top_height),
            Layout(input_panel, ratio=1),
        )

        return Panel(body, title="Emload Downloader", expand=True)

    def _render_history(self) -> RenderableType:
        if not self.history_lines:
            return Text("No activity yet.", style="dim")
        table = Table(show_header=False, expand=True)
        table.add_column("History", overflow="fold")
        for line in list(self.history_lines)[-80:][::-1]:
            table.add_row(line)
        return table

    def _render_downloads(self) -> RenderableType:
        download = self.download_renderable or Text("No download yet.", style="dim")
        history_panel = Panel(self._render_history(), title="History", expand=True)
        total_height = max(self.downloads_height, 12)
        download_height = 8
        if self.console:
            try:
                options = self.console.options.update(width=max(20, self.downloads_width - 4))
                lines = self.console.render_lines(download, options, style=None, pad=False)
                download_height = max(3, len(lines))
            except Exception:
                download_height = 8
        available = max(10, total_height - 2)
        download_height = min(download_height, max(3, available - 5))
        layout = Layout()
        layout.split_column(
            Layout(download, name="download", size=download_height),
            Layout(history_panel, name="history", ratio=1),
        )
        return layout

    def show_test_layout(self) -> dict:
        previous = {
            "download_renderable": self.download_renderable,
            "download_title": self.download_title,
            "history_lines": list(self.history_lines),
            "config_values": dict(self.config_values),
            "last_run_config": dict(self.last_run_config),
        }
        sample_settings = {
            "Links path": "data/links.json",
            "Cookies path": "data/emload_cookies.json",
            "Output dir": "downloads",
            "State path": "data/state.json",
            "Range": "100 - 500",
            "Workers": "5",
            "Retries": "3",
            "Delay seconds": "0.50",
            "Daily limit GB": "35.00",
            "Headless browser": "yes",
        }
        self.config_values = sample_settings
        self.last_run_config = dict(sample_settings)

        self.history_lines.clear()
        self.history_lines.extend(
            [
                "Queue size: 12 | workers: 5",
                "[W1] done idx=0100 size=250.12 MB speed=8.42 MB/s",
                "[W2] done idx=0101 size=180.44 MB speed=7.91 MB/s",
                "[W3] skip existing idx=0102 size=200.00 MB",
                "[W4] done idx=0103 size=320.10 MB speed=9.14 MB/s",
                "[W5] bandwidth limit detected; sleeping until next day",
            ]
        )

        try:
            from emload_downloader.bulk import ProgressUI, RunCounters, WorkerStatus
            from emload_downloader.state import StateManager
            from pathlib import Path
            import threading as _threading
            import time as _time

            statuses = {
                "W1": WorkerStatus(idx=104, state="downloading", attempt=1, start_ts=_time.time() - 12, last_speed_mbps=7.4, last_result="downloading 120.00 MB"),
                "W2": WorkerStatus(idx=105, state="connecting", attempt=1, start_ts=_time.time() - 4, last_speed_mbps=0.0, last_result="opening page"),
                "W3": WorkerStatus(idx=106, state="idle", attempt=0),
                "W4": WorkerStatus(idx=107, state="done", attempt=1, last_speed_mbps=9.2, last_result="done 300.00 MB"),
                "W5": WorkerStatus(idx=108, state="failed", attempt=2, last_speed_mbps=0.0, last_result="failed"),
            }
            counters = RunCounters(total=200, completed=120, failed=2, skipped=5)
            state = StateManager(Path("/tmp/emload_test_state.json"), download_dir=Path("/tmp"))
            ui = ProgressUI(counters, statuses, _threading.Lock(), state, config_rows=None, screen=False)
            self.download_renderable = ui
            self.download_title = "Bulk Download (Test)"
        except Exception:
            self.download_renderable = Text("Download preview unavailable", style="dim")
            self.download_title = "Bulk Download (Test)"

        self._refresh()
        return previous

    def restore_layout(self, previous: dict) -> None:
        self.download_renderable = previous.get("download_renderable")
        self.download_title = previous.get("download_title", "Download")
        self.history_lines.clear()
        self.history_lines.extend(previous.get("history_lines", []))
        self.config_values = previous.get("config_values", {})
        self.last_run_config = previous.get("last_run_config", {})
        self._refresh()

    def _update_emload(self) -> None:
        self.layout["emload"].update(self._render_emload_panel())

    def _update_downloads(self) -> None:
        self.layout["downloads"].update(Panel(self._render_downloads(), title=self.download_title))

    def _ensure_layout(self, force: bool = False) -> None:
        if self.console is None:
            return
        if self.console:
            width = self.console.size.width
            height = self.console.size.height
        else:
            width, height = 100, 40
        size_key = (width, height)
        settings_len = len(self.settings_order)
        layout_key = (width, height, settings_len, len(self.menu_items))
        if not force and layout_key == self.last_layout_key and self.layout is not None:
            self._update_emload()
            self._update_downloads()
            return
        self.last_size = size_key
        self.last_layout_key = layout_key
        self.layout = Layout()
        menu_width = max((len(item) for item in self.menu_items), default=20) + 10
        menu_width = min(max(menu_width, 36), max(36, width // 3))
        action_width = max(10, menu_width - 14)
        menu_rows = sum(max(1, math.ceil(len(item) / action_width)) for item in self.menu_items)
        downloads_min = 60
        left_width = min(
            max(menu_width + 20, width // 2),
            max(menu_width + 20, width - downloads_min),
        )
        menu_height = min(max(menu_rows + 8, 14), max(14, height - 6))
        min_history_height = 5
        settings_height = min(max(max(settings_len, 3), 1), 12) + 4
        top_height = max(menu_height, settings_height) + 2
        min_input_height = 4
        min_download_height = 12
        min_emload = top_height + min_input_height
        emload_height = min(
            height - 2,
            max(min_emload, height - min_history_height),
        )
        if width < 110:
            emload_height = min(emload_height, max(min_emload, height - min_download_height))

        self.menu_width = menu_width
        self.top_height = top_height

        if width >= 110:
            emload_height = max(emload_height, height - 2)
            self.layout.split_row(
                Layout(name="left", size=left_width),
                Layout(name="downloads", ratio=1),
            )
            self.layout["left"].split_column(
                Layout(name="emload", ratio=1),
            )
            self.downloads_height = max(10, height - 2)
            self.downloads_width = max(20, width - left_width - 2)
        else:
            self.layout.split_column(
                Layout(name="emload", size=emload_height),
                Layout(name="downloads", ratio=1),
            )
            self.downloads_height = max(10, height - emload_height - 1)
            self.downloads_width = max(20, width - 2)
        self.emload_height = emload_height
        self._update_emload()
        self._update_downloads()
        if self.live:
            self.live.update(self.layout)

    def _refresh(self) -> None:
        if self.live:
            if self.resize_pending.is_set():
                self.resize_pending.clear()
                if self.console:
                    self.console.clear()
                self._ensure_layout(force=True)
            else:
                self._ensure_layout()
            self.live.refresh()

    def _refresh_loop(self) -> None:
        while not self.refresh_stop.wait(0.2):
            if self.refresh_pause.is_set():
                if self.resize_pending.is_set():
                    self._refresh()
                continue
            self._refresh()

    def _handle_resize(self, *_args) -> None:
        self.resize_pending.set()

    def _readline_raw(self) -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        raw = termios.tcgetattr(fd)
        raw[3] &= ~(termios.ECHO | termios.ICANON)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, raw)
            while True:
                ch = sys.stdin.read(1)
                if ch in ("\n", "\r"):
                    return self.input_buffer
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x7f", "\b"):
                    with self.lock:
                        self.input_buffer = self.input_buffer[:-1]
                        self._update_emload()
                        self._refresh()
                    continue
                if ch and ch.isprintable():
                    with self.lock:
                        self.input_buffer += ch
                        self._update_emload()
                        self._refresh()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _parse_prompt(self, prompt_text: str) -> tuple[Optional[str], Optional[str]]:
        text = prompt_text.strip()
        if not text:
            return None, None
        if "[" in text and "]" in text:
            before, rest = text.split("[", 1)
            default, _ = rest.split("]", 1)
            key = before.strip().rstrip(":")
            return key, default
        key = text.rstrip(":")
        return key, None

    def _normalize_key(self, key: str) -> Optional[str]:
        normalized = key.strip().rstrip(":")
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered in {"choose an option", "test layout: enter q to exit"}:
            return None
        if lowered.startswith("choose ") or lowered.startswith("select "):
            return None
        if " (" in normalized and normalized.endswith(")"):
            normalized = normalized.rsplit("(", 1)[0].strip()
            lowered = normalized.lower()
        if normalized.endswith("?"):
            normalized = normalized[:-1].strip()
            lowered = normalized.lower()
        if lowered.startswith("start from beginning or specific idx"):
            return "Range"
        if lowered.startswith("start index"):
            return "Range"
        if lowered.startswith("end index"):
            return "Range"
        return self.settings_lookup.get(lowered)

    def _set_range_value(self, key: str, value: str) -> None:
        normalized_key = key.strip().lower()
        current = self.config_values.get("Range", "—")
        if current == "—":
            current = ""
        parts = [part.strip() for part in current.split("-", 1)]
        start_val = parts[0] if parts else ""
        end_val = parts[1] if len(parts) > 1 else ""
        if normalized_key.startswith("end index"):
            end_val = value.strip()
        else:
            start_val = value.strip()
        if start_val or end_val:
            self.config_values["Range"] = f"{start_val or '—'} - {end_val or '—'}"
        else:
            self.config_values["Range"] = "—"
