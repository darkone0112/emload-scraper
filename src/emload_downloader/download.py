from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple, Union

from playwright.sync_api import Page, TimeoutError, sync_playwright

from emload_downloader.cookies import load_playwright_cookies
from emload_downloader.ui import print_line

EMLOAD_LINK_RE = re.compile(r"^https?://(?:www\.)?emload\.com/v2/file/[^/]+/(\d+)-")


class BandwidthLimitError(RuntimeError):
    pass


def _safe_filename(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_")


def _extract_idx(url: str) -> Optional[int]:
    match = EMLOAD_LINK_RE.match(url)
    if not match:
        return None
    return int(match.group(1))


def _pick_download_selector(
    custom_selector: Optional[str] = None,
) -> Sequence[str]:
    if custom_selector:
        return [custom_selector]
    return [
        'a:has-text("Download Now")',
        'a:has-text("Download")',
        'button:has-text("Download Now")',
        'button:has-text("Download")',
        "a.init-prodl",
        "a#download",
        "button#download",
        '[class*="download"]',
    ]


def _find_clickable(page: Page, selectors: Sequence[str], timeout_ms: int) -> str:
    last_error = None
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout_ms, state="visible")
            return sel
        except Exception as exc:  # pragma: no cover - best-effort probing
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("No download selector matched.")


def _page_has_limit_text(page: Page) -> bool:
    try:
        text = page.inner_text("body")
    except Exception:
        return False
    lowered = text.lower()
    keywords = (
        "bandwidth",
        "download limit",
        "daily limit",
        "traffic limit",
        "quota",
        "limit reached",
    )
    return any(k in lowered for k in keywords)


def _load_link_from_json(path: Path, idx: Optional[int]) -> Tuple[Optional[int], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"No links found in {path}")
    if idx is not None:
        for item in data:
            if isinstance(item, dict) and item.get("idx") == idx:
                return idx, item.get("url")
        raise ValueError(f"Index {idx} not found in {path}")
    first = data[0]
    if isinstance(first, dict):
        return first.get("idx"), first.get("url")
    raise ValueError(f"Unexpected links format in {path}")


def download_one(
    page: Page,
    url: str,
    download_dir: Path,
    idx: Optional[int] = None,
    selector: Optional[str] = None,
    timeout_ms: int = 30000,
    progress_cb: Optional[Callable[[int, float], None]] = None,
    progress_interval_s: float = 0.5,
) -> Path:
    page.goto(url, wait_until="domcontentloaded")

    if _page_has_limit_text(page):
        raise BandwidthLimitError("Page indicates bandwidth limit reached.")

    selectors = _pick_download_selector(selector)
    sel = _find_clickable(page, selectors, timeout_ms)

    try:
        with page.expect_download(timeout=timeout_ms) as dl_info:
            page.click(sel)
    except TimeoutError as exc:
        if _page_has_limit_text(page):
            raise BandwidthLimitError("Download limit message after click.") from exc
        raise

    download = dl_info.value
    suggested = _safe_filename(download.suggested_filename)
    if idx is None:
        idx = _extract_idx(url)

    if idx is None:
        filename = suggested
    else:
        filename = f"{idx:04d}_{suggested}"

    download_dir.mkdir(parents=True, exist_ok=True)
    temp_path = download_dir / f"{filename}.part"
    final_path = download_dir / filename

    stop_event = threading.Event()
    monitor_thread: Optional[threading.Thread] = None
    if progress_cb is not None and progress_interval_s > 0:
        def _monitor() -> None:
            last_size = 0
            last_ts = time.time()
            while not stop_event.wait(progress_interval_s):
                try:
                    size = temp_path.stat().st_size
                except OSError:
                    size = 0
                now = time.time()
                elapsed = now - last_ts
                if elapsed > 0:
                    speed_mbps = ((size - last_size) / 1_000_000) / elapsed
                    try:
                        progress_cb(size, max(0.0, speed_mbps))
                    except Exception:
                        pass
                last_size = size
                last_ts = now

        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()

    try:
        download.save_as(temp_path)
        failure = download.failure()
    finally:
        stop_event.set()
        if monitor_thread:
            monitor_thread.join(timeout=1)

    if failure:
        raise RuntimeError(f"Download failed: {failure}")
    temp_path.rename(final_path)
    return final_path


def run_download_one(
    url: Optional[str],
    cookies_path: Union[str, Path],
    download_dir: Union[str, Path] = Path("downloads"),
    idx: Optional[int] = None,
    links_path: Optional[Union[str, Path]] = None,
    selector: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> Path:
    cookies = load_playwright_cookies(cookies_path)
    download_dir = Path(download_dir)
    if not url and links_path:
        idx, url = _load_link_from_json(Path(links_path), idx)
    if not url:
        raise ValueError("Provide --url or --from-links.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        context.add_cookies(cookies)
        page = context.new_page()

        path = download_one(
            page,
            url=url,
            download_dir=download_dir,
            idx=idx,
            selector=selector,
            timeout_ms=timeout_ms,
        )

        browser.close()

    print_line(f"Downloaded: {path}")
    return path
