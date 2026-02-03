from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

from emload_downloader.cookies import load_playwright_cookies
from emload_downloader.ui import print_line

EMLOAD_LINK_RE = re.compile(r"^https?://(?:www\.)?emload\.com/v2/file/[^/]+/(\d+)-")


def _normalize_url(base_url: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base_url, href)


def collect_emload_links(page: Page, list_url: str) -> List[Tuple[int, str]]:
    page.goto(list_url, wait_until="networkidle")

    hrefs: Iterable[str] = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
    )

    by_idx: Dict[int, str] = {}
    for href in hrefs:
        url = _normalize_url(list_url, href)
        match = EMLOAD_LINK_RE.match(url)
        if not match:
            continue
        idx = int(match.group(1))
        if idx not in by_idx:
            by_idx[idx] = url

    return sorted(by_idx.items())


def _find_gaps(indices: List[int]) -> List[int]:
    if not indices:
        return []
    idx_set = set(indices)
    lo = indices[0]
    hi = indices[-1]
    return [i for i in range(lo, hi + 1) if i not in idx_set]


def _unique_out_path(out_path: Path) -> Path:
    if not out_path.exists():
        return out_path
    stem = out_path.stem
    suffix = out_path.suffix or ".json"
    for i in range(1, 1000):
        candidate = out_path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not find available output filename.")


def _write_links_json(pairs: List[Tuple[int, str]], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = _unique_out_path(out_path)
    payload = [{"idx": idx, "url": url} for idx, url in pairs]
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def run_scrape(
    list_url: str,
    cookies_path: Path,
    out_path: Path,
    headless: bool = True,
) -> List[Tuple[int, str]]:
    cookies = load_playwright_cookies(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=False)
        context.add_cookies(cookies)

        page = context.new_page()
        pairs = collect_emload_links(page, list_url)
        browser.close()

    out_path = _write_links_json(pairs, out_path)

    indices = [idx for idx, _ in pairs]
    gaps = _find_gaps(indices)
    if indices:
        print_line(
            f"Scraped {len(pairs)} links. "
            f"Min idx={indices[0]} Max idx={indices[-1]} Gaps={len(gaps)}"
        )
    else:
        print_line("No emload links found. Check LIST_URL or login status.")

    if gaps:
        print_line(f"Missing indices (first 20): {gaps[:20]}")

    print_line(f"Wrote: {out_path}")
    return pairs
