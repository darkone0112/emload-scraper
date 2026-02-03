from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table

    _HAS_RICH = True
except Exception:  # pragma: no cover - optional UI dependency
    _HAS_RICH = False

from playwright.sync_api import sync_playwright

from emload_downloader.cookies import load_playwright_cookies
from emload_downloader.download import BandwidthLimitError, download_one
from emload_downloader.links import existing_downloads, filter_range, load_links
from emload_downloader.state import StateManager


def _seconds_until_next_midnight() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def _format_size_mb_gb(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    return f"{size_mb:.2f} MB"


@dataclass
class BulkConfig:
    links_path: Path
    cookies_path: Path
    out_dir: Path
    state_path: Path
    workers: int
    retries: int
    delay_s: float
    selector: Optional[str]
    headless: bool
    timeout_ms: int
    daily_limit_bytes: int


class BandwidthLimiter:
    def __init__(
        self,
        state: StateManager,
        limit_bytes: int,
        print_lock: threading.Lock,
        log_fn: Optional[callable] = None,
    ) -> None:
        self.state = state
        self.limit_bytes = limit_bytes
        self.print_lock = print_lock
        self.log_fn = log_fn
        self.lock = threading.Lock()
        self.pause_until_ts = 0.0

    def wait_for_budget(self) -> None:
        while True:
            with self.lock:
                self.state.ensure_daily()
                now = time.time()
                if now < self.pause_until_ts:
                    sleep_s = int(self.pause_until_ts - now)
                else:
                    used = self.state.get_daily_bytes()
                    if used < self.limit_bytes:
                        return
                    sleep_s = _seconds_until_next_midnight()
                    self.pause_until_ts = now + sleep_s
                    msg = (
                        f"Daily limit reached ({used / 1_000_000_000:.2f} GB). "
                        f"Sleeping {sleep_s}s until next day."
                    )
                    if self.log_fn:
                        self.log_fn(msg)
                    else:
                        with self.print_lock:
                            print(msg)
            time.sleep(sleep_s)

    def trigger_pause(self, reason: str) -> None:
        with self.lock:
            now = time.time()
            sleep_s = _seconds_until_next_midnight()
            self.pause_until_ts = max(self.pause_until_ts, now + sleep_s)
            self.state.set_daily_bytes(self.limit_bytes)
            msg = f"Bandwidth limit detected ({reason}). Sleeping {sleep_s}s."
            if self.log_fn:
                self.log_fn(msg)
            else:
                with self.print_lock:
                    print(msg)


@dataclass
class WorkerStatus:
    idx: Optional[int] = None
    state: str = "idle"
    attempt: int = 0
    updated_ts: float = 0.0
    start_ts: float = 0.0
    last_result: str = ""
    last_speed_mbps: float = 0.0
    last_error: str = ""


def _update_status(
    statuses: dict[str, WorkerStatus],
    status_lock: threading.Lock,
    name: str,
    *,
    idx: Optional[int] = None,
    state: Optional[str] = None,
    attempt: Optional[int] = None,
    start_ts: Optional[float] = None,
    last_result: Optional[str] = None,
    last_speed_mbps: Optional[float] = None,
    last_error: Optional[str] = None,
) -> None:
    with status_lock:
        st = statuses[name]
        if idx is not None:
            st.idx = idx
        if state is not None:
            st.state = state
        if attempt is not None:
            st.attempt = attempt
        if start_ts is not None:
            st.start_ts = start_ts
        if last_result is not None:
            st.last_result = last_result
        if last_speed_mbps is not None:
            st.last_speed_mbps = last_speed_mbps
        if last_error is not None:
            st.last_error = last_error
        st.updated_ts = time.time()


@dataclass
class RunCounters:
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0


class ProgressUI:
    def __init__(
        self,
        counters: RunCounters,
        statuses: dict[str, WorkerStatus],
        status_lock: threading.Lock,
        state: StateManager,
    ) -> None:
        self.counters = counters
        self.statuses = statuses
        self.status_lock = status_lock
        self.state = state
        self.console = Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]Overall[/bold]"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )
        self.task_id = self.progress.add_task("overall", total=counters.total, completed=counters.completed)
        self.live: Optional[Live] = None
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.live = Live(self._render(), console=self.console, refresh_per_second=4)
        self.live.__enter__()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)
        if self.live:
            self.live.__exit__(None, None, None)

    def log(self, msg: str) -> None:
        if self.live:
            self.console.log(msg)
        else:
            print(msg)

    def update_counters(self) -> None:
        self.progress.update(self.task_id, completed=self.counters.completed, total=self.counters.total)

    def _loop(self) -> None:
        while not self.stop_event.wait(0.5):
            if self.live:
                self.update_counters()
                self.live.update(self._render())

    def _render(self) -> Group:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Worker", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Idx", no_wrap=True)
        table.add_column("Attempt", no_wrap=True)
        table.add_column("Elapsed", no_wrap=True)
        table.add_column("Last Speed", no_wrap=True)
        table.add_column("Last Result", no_wrap=True)

        now = time.time()
        with self.status_lock:
            items = list(self.statuses.items())
        for name, st in items:
            idx = f"{st.idx:04d}" if st.idx is not None else "-"
            elapsed = "-"
            if st.start_ts:
                elapsed = f"{int(now - st.start_ts)}s"
            speed = "-" if st.last_speed_mbps <= 0 else f"{st.last_speed_mbps:.2f} MB/s"
            result = st.last_result or "-"
            table.add_row(name, st.state, idx, str(st.attempt or "-"), elapsed, speed, result)

        used = self.state.get_daily_bytes()
        summary = (
            f"pending={self.counters.total - self.counters.completed} "
            f"completed={self.counters.completed} failed={self.counters.failed} "
            f"skipped={self.counters.skipped} daily={used / 1_000_000_000:.2f} GB"
        )

        summary_grid = Table.grid()
        summary_grid.add_row(summary)
        return Group(self.progress, summary_grid, table)


def _progress_loop(
    stop_event: threading.Event,
    q: "queue.Queue[Optional[Tuple[int, str]]]",
    state: StateManager,
    limiter: BandwidthLimiter,
    statuses: dict[str, WorkerStatus],
    status_lock: threading.Lock,
    print_lock: threading.Lock,
    counters: RunCounters,
    counters_lock: threading.Lock,
    interval_s: int = 10,
) -> None:
    while not stop_event.wait(interval_s):
        with status_lock:
            items = [
                f"{name}:{st.state}"
                + (f":{st.idx:04d}" if st.idx is not None else "")
                + (f":a{st.attempt}" if st.attempt else "")
                for name, st in statuses.items()
            ]
        with print_lock:
            used = state.get_daily_bytes()
            with counters_lock:
                completed = counters.completed
                failed = counters.failed
                pending = counters.total - counters.completed
            print(
                "Status | "
                f"pending={pending} completed={completed} failed={failed} "
                f"daily={used / 1_000_000_000:.2f} GB | "
                + " ".join(items)
            )


def _worker_loop(
    name: str,
    task_queue: "queue.Queue[Optional[Tuple[int, str]]]",
    cookies: list,
    state: StateManager,
    limiter: BandwidthLimiter,
    cfg: BulkConfig,
    print_lock: threading.Lock,
    existing: dict[int, Path],
    statuses: dict[str, WorkerStatus],
    status_lock: threading.Lock,
    counters: RunCounters,
    counters_lock: threading.Lock,
    ui: Optional[ProgressUI],
) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context(accept_downloads=True)
        context.add_cookies(cookies)
        page = context.new_page()

        while True:
            item = task_queue.get()
            if item is None:
                _update_status(statuses, status_lock, name, state="stopped", idx=None, attempt=0)
                task_queue.task_done()
                break

            idx, url = item
            _update_status(
                statuses,
                status_lock,
                name,
                state="start",
                idx=idx,
                attempt=0,
                start_ts=time.time(),
                last_error="",
            )
            if state.is_done(idx):
                _update_status(statuses, status_lock, name, state="skip-done", idx=idx)
                with counters_lock:
                    counters.completed += 1
                    counters.skipped += 1
                task_queue.task_done()
                continue
            if idx in existing:
                existing_path = existing[idx]
                try:
                    size = existing_path.stat().st_size
                except OSError:
                    size = 0
                size_label = _format_size_mb_gb(size)
                state.mark_done(idx, url, existing_path.name, size, log_download=False)
                msg = f"[{name}] skip existing idx={idx:04d} file={existing_path.name}"
                if ui:
                    ui.log(msg)
                else:
                    with print_lock:
                        print(msg)
                _update_status(
                    statuses,
                    status_lock,
                    name,
                    state="skip-existing",
                    idx=idx,
                    last_result=f"skip-existing {size_label}",
                )
                with counters_lock:
                    counters.completed += 1
                    counters.skipped += 1
                task_queue.task_done()
                continue

            attempt = 0
            success = False
            while attempt < cfg.retries:
                _update_status(statuses, status_lock, name, state="waiting-budget", idx=idx, attempt=attempt + 1)
                limiter.wait_for_budget()
                try:
                    _update_status(statuses, status_lock, name, state="downloading", idx=idx, attempt=attempt + 1)
                    path = download_one(
                        page,
                        url=url,
                        download_dir=cfg.out_dir,
                        idx=idx,
                        selector=cfg.selector,
                        timeout_ms=cfg.timeout_ms,
                    )
                    size = path.stat().st_size
                    size_label = _format_size_mb_gb(size)
                    state.mark_done(idx, url, path.name, size)
                    state.add_daily_bytes(size)
                    duration = max(0.1, time.time() - statuses[name].start_ts)
                    speed_mbps = (size / 1_000_000) / duration
                    msg = (
                        f"[{name}] done idx={idx:04d} size={size_label} "
                        f"speed={speed_mbps:.2f} MB/s"
                    )
                    if ui:
                        ui.log(msg)
                    else:
                        with print_lock:
                            used = state.get_daily_bytes()
                            print(f"{msg} daily={used / 1_000_000_000:.2f} GB")
                    _update_status(
                        statuses,
                        status_lock,
                        name,
                        state="done",
                        idx=idx,
                        attempt=attempt + 1,
                        last_result=f"done {size_label}",
                        last_speed_mbps=speed_mbps,
                    )
                    with counters_lock:
                        counters.completed += 1
                    success = True
                    if cfg.delay_s:
                        time.sleep(cfg.delay_s)
                    break
                except BandwidthLimitError as exc:
                    limiter.trigger_pause(str(exc))
                    _update_status(statuses, status_lock, name, state="bandwidth-limit", idx=idx, attempt=attempt + 1)
                    continue
                except Exception as exc:  # pragma: no cover - runtime errors
                    attempt += 1
                    state.mark_failed(idx, url, str(exc), attempt)
                    msg = f"[{name}] failed idx={idx:04d} attempt={attempt} err={exc}"
                    if ui:
                        ui.log(msg)
                    else:
                        with print_lock:
                            print(msg)
                    _update_status(
                        statuses,
                        status_lock,
                        name,
                        state="failed",
                        idx=idx,
                        attempt=attempt,
                        last_result="failed",
                        last_error=str(exc),
                    )
                    if attempt < cfg.retries:
                        time.sleep(min(10, 2 * attempt))

            if not success:
                with counters_lock:
                    counters.completed += 1
                    counters.failed += 1
                _update_status(
                    statuses,
                    status_lock,
                    name,
                    state="failed-final",
                    idx=idx,
                    attempt=attempt,
                    last_result="failed",
                    last_error="exceeded retries",
                )
            _update_status(statuses, status_lock, name, state="idle", idx=None, attempt=0)
            task_queue.task_done()

        browser.close()


def run_bulk_download(
    links_path: Path,
    cookies_path: Path,
    out_dir: Path,
    state_path: Path,
    start: Optional[int],
    end: Optional[int],
    workers: int,
    retries: int,
    delay_s: float,
    selector: Optional[str],
    headless: bool,
    timeout_ms: int,
    daily_limit_gb: float,
) -> None:
    links = load_links(links_path)
    links = filter_range(links, start, end)
    if not links:
        print("No links to process after filtering.")
        return

    cookies = load_playwright_cookies(cookies_path)
    state = StateManager(state_path, download_dir=out_dir)
    state.ensure_daily()

    limit_bytes = int(daily_limit_gb * 1_000_000_000)
    cfg = BulkConfig(
        links_path=links_path,
        cookies_path=cookies_path,
        out_dir=out_dir,
        state_path=state_path,
        workers=workers,
        retries=retries,
        delay_s=delay_s,
        selector=selector,
        headless=headless,
        timeout_ms=timeout_ms,
        daily_limit_bytes=limit_bytes,
    )

    print_lock = threading.Lock()

    existing = existing_downloads(out_dir)
    q: "queue.Queue[Optional[Tuple[int, str]]]" = queue.Queue()
    pending = 0
    for idx, url in links:
        if state.is_done(idx):
            continue
        q.put((idx, url))
        pending += 1

    if pending == 0:
        print("All items already completed.")
        return

    with print_lock:
        print(f"Queue size: {pending} | workers: {workers}")

    status_lock = threading.Lock()
    statuses = {f"W{i+1}": WorkerStatus(updated_ts=time.time()) for i in range(workers)}
    counters_lock = threading.Lock()
    already_done = sum(1 for idx, _ in links if state.is_done(idx))
    total = pending + already_done
    counters = RunCounters(total=total, completed=already_done)

    use_rich = _HAS_RICH and Console().is_terminal
    ui = ProgressUI(counters, statuses, status_lock, state) if use_rich else None
    if ui:
        ui.start()

    limiter = BandwidthLimiter(state, limit_bytes, print_lock, log_fn=ui.log if ui else None)

    stop_event = threading.Event()
    progress_thread = threading.Thread(
        target=_progress_loop,
        args=(
            stop_event,
            q,
            state,
            limiter,
            statuses,
            status_lock,
            print_lock,
            counters,
            counters_lock,
        ),
        daemon=True,
    )
    if not ui:
        progress_thread.start()

    threads = []
    for i in range(workers):
        t = threading.Thread(
            target=_worker_loop,
            args=(
                f"W{i+1}",
                q,
                cookies,
                state,
                limiter,
                cfg,
                print_lock,
                existing,
                statuses,
                status_lock,
                counters,
                counters_lock,
                ui,
            ),
            daemon=True,
        )
        t.start()
        threads.append(t)

    q.join()
    for _ in threads:
        q.put(None)
    for t in threads:
        t.join()
    stop_event.set()
    if not ui:
        progress_thread.join(timeout=1)
    if ui:
        ui.stop()

    with print_lock:
        print("Bulk download finished.")
