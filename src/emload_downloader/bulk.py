from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from playwright.sync_api import sync_playwright

from emload_downloader.cookies import load_playwright_cookies
from emload_downloader.download import BandwidthLimitError, download_one
from emload_downloader.state import StateManager


def _load_links(path: Path) -> List[Tuple[int, str]]:
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


def _existing_downloads(out_dir: Path) -> dict[int, Path]:
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


def _filter_range(
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


def _seconds_until_next_midnight() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


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
    def __init__(self, state: StateManager, limit_bytes: int, print_lock: threading.Lock) -> None:
        self.state = state
        self.limit_bytes = limit_bytes
        self.print_lock = print_lock
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
                    with self.print_lock:
                        print(
                            f"Daily limit reached ({used / 1_000_000_000:.2f} GB). "
                            f"Sleeping {sleep_s}s until next day."
                        )
            time.sleep(sleep_s)

    def trigger_pause(self, reason: str) -> None:
        with self.lock:
            now = time.time()
            sleep_s = _seconds_until_next_midnight()
            self.pause_until_ts = max(self.pause_until_ts, now + sleep_s)
            self.state.set_daily_bytes(self.limit_bytes)
            with self.print_lock:
                print(f"Bandwidth limit detected ({reason}). Sleeping {sleep_s}s.")


def _worker_loop(
    name: str,
    task_queue: "queue.Queue[Optional[Tuple[int, str]]]",
    cookies: list,
    state: StateManager,
    limiter: BandwidthLimiter,
    cfg: BulkConfig,
    print_lock: threading.Lock,
    existing: dict[int, Path],
) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        context = browser.new_context(accept_downloads=True)
        context.add_cookies(cookies)
        page = context.new_page()

        while True:
            item = task_queue.get()
            if item is None:
                task_queue.task_done()
                break

            idx, url = item
            if state.is_done(idx):
                task_queue.task_done()
                continue
            if idx in existing:
                existing_path = existing[idx]
                try:
                    size = existing_path.stat().st_size
                except OSError:
                    size = 0
                state.mark_done(idx, url, existing_path.name, size, log_download=False)
                with print_lock:
                    print(f"[{name}] skip existing idx={idx:04d} file={existing_path.name}")
                task_queue.task_done()
                continue

            attempt = 0
            while attempt < cfg.retries:
                limiter.wait_for_budget()
                try:
                    path = download_one(
                        page,
                        url=url,
                        download_dir=cfg.out_dir,
                        idx=idx,
                        selector=cfg.selector,
                        timeout_ms=cfg.timeout_ms,
                    )
                    size = path.stat().st_size
                    state.mark_done(idx, url, path.name, size)
                    state.add_daily_bytes(size)
                    with print_lock:
                        used = state.get_daily_bytes()
                        print(
                            f"[{name}] done idx={idx:04d} size={size}B "
                            f"daily={used / 1_000_000_000:.2f} GB"
                        )
                    if cfg.delay_s:
                        time.sleep(cfg.delay_s)
                    break
                except BandwidthLimitError as exc:
                    limiter.trigger_pause(str(exc))
                    continue
                except Exception as exc:  # pragma: no cover - runtime errors
                    attempt += 1
                    state.mark_failed(idx, url, str(exc), attempt)
                    with print_lock:
                        print(f"[{name}] failed idx={idx:04d} attempt={attempt} err={exc}")
                    if attempt < cfg.retries:
                        time.sleep(min(10, 2 * attempt))

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
    links = _load_links(links_path)
    links = _filter_range(links, start, end)
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
    limiter = BandwidthLimiter(state, limit_bytes, print_lock)

    existing = _existing_downloads(out_dir)
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

    threads = []
    for i in range(workers):
        t = threading.Thread(
            target=_worker_loop,
            args=(f"W{i+1}", q, cookies, state, limiter, cfg, print_lock, existing),
            daemon=True,
        )
        t.start()
        threads.append(t)

    q.join()
    for _ in threads:
        q.put(None)
    for t in threads:
        t.join()

    with print_lock:
        print("Bulk download finished.")
