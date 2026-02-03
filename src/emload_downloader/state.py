from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return date.today().isoformat()


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "daily": {"date": _today_str(), "bytes": 0},
            "completed": {},
            "failed": {},
            "last_run_ts": None,
        }

    data = json.loads(path.read_text(encoding="utf-8"))
    if "daily" not in data:
        data["daily"] = {"date": _today_str(), "bytes": 0}
    if "completed" not in data:
        data["completed"] = {}
    if "failed" not in data:
        data["failed"] = {}
    if "version" not in data:
        data["version"] = 1
    if "last_run_ts" not in data:
        data["last_run_ts"] = None
    return data


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


class StateManager:
    def __init__(self, path: Path, download_dir: Optional[Path] = None) -> None:
        self.path = path
        if download_dir is None:
            download_dir = path.parent.parent / "downloads"
        self.download_dir = download_dir
        self.lock = threading.Lock()
        self.state = load_state(path)

    def ensure_daily(self) -> None:
        with self.lock:
            self._ensure_daily_locked()

    def _ensure_daily_locked(self) -> None:
        today = _today_str()
        daily = self.state.get("daily", {})
        if daily.get("date") != today:
            self.state["daily"] = {"date": today, "bytes": 0}
            self._save_locked()

    def get_daily_bytes(self) -> int:
        with self.lock:
            self._ensure_daily_locked()
            return int(self.state["daily"].get("bytes", 0))

    def set_daily_bytes(self, value: int) -> None:
        with self.lock:
            self._ensure_daily_locked()
            self.state["daily"]["bytes"] = int(value)
            self._save_locked()

    def add_daily_bytes(self, delta: int) -> None:
        with self.lock:
            self._ensure_daily_locked()
            self.state["daily"]["bytes"] = int(self.state["daily"].get("bytes", 0)) + int(delta)
            self._save_locked()

    def is_done(self, idx: int) -> bool:
        with self.lock:
            return str(idx) in self.state.get("completed", {})

    def mark_done(
        self,
        idx: int,
        url: str,
        filename: str,
        byte_size: int,
        log_download: bool = True,
    ) -> None:
        with self.lock:
            self.state.setdefault("completed", {})[str(idx)] = {
                "url": url,
                "filename": filename,
                "bytes": int(byte_size),
                "ts": _now_ts(),
            }
            if str(idx) in self.state.get("failed", {}):
                self.state["failed"].pop(str(idx), None)
            self.state["last_run_ts"] = _now_ts()
            self._save_locked()
        if log_download:
            self._append_download_log(idx, filename)

    def mark_failed(self, idx: int, url: str, error: str, attempt: int) -> None:
        with self.lock:
            entry = self.state.setdefault("failed", {}).get(str(idx), {})
            attempts = max(int(entry.get("attempts", 0)), attempt)
            self.state["failed"][str(idx)] = {
                "url": url,
                "attempts": attempts,
                "last_error": error,
                "last_ts": _now_ts(),
            }
            self.state["last_run_ts"] = _now_ts()
            self._save_locked()

    def clear_completed(self, indices: Iterable[int]) -> int:
        removed = 0
        with self.lock:
            completed = self.state.setdefault("completed", {})
            for idx in indices:
                if completed.pop(str(idx), None) is not None:
                    removed += 1
            if removed:
                self._save_locked()
        return removed

    def completed_count(self) -> int:
        with self.lock:
            return len(self.state.get("completed", {}))

    def failed_count(self) -> int:
        with self.lock:
            return len(self.state.get("failed", {}))

    def _append_download_log(self, idx: int, filename: str) -> None:
        log_path = self.download_dir / "downloaded.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{idx:04d}\t{filename}\n")

    def _save_locked(self) -> None:
        save_state(self.path, self.state)
