from __future__ import annotations

import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

from emload_downloader.cookies import load_playwright_cookies
from emload_downloader.ui import print_line

EMLOAD_LINK_RE = re.compile(r"^https?://(?:www\.)?emload\.com/v2/file/[^/]+/(\d+)-")


@dataclass
class ScrapedLink:
    idx: Optional[int]
    url: str
    path: Tuple[str, ...]
    name: Optional[str] = None


def _normalize_url(base_url: str, href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base_url, href)


def _folder_fallback_name(url: str) -> str:
    stripped = url.rstrip("/").split("/")[-1]
    return stripped or "folder"


def _parse_listing_entries(page: Page) -> Iterable[Dict[str, object]]:
    return page.eval_on_selector_all(
        "a.flex.noul.anim.aic.fvfile",
        """
        els => els.map(el => {
            const href = el.getAttribute('href');
            if (!href) {
                return null;
            }
            const isFolder = (el.getAttribute('data-isd') || '').toLowerCase() === 'folder';
            const nameNode = el.querySelector('div.mta.flex.col h2.s15');
            const name = nameNode ? nameNode.textContent.trim() : '';
            return { href, isFolder, name };
        }).filter(Boolean)
        """,
    )


def _assign_missing_indices(links: Sequence[ScrapedLink]) -> List[ScrapedLink]:
    used = {link.idx for link in links if link.idx is not None}
    max_idx = max(used) if used else 0
    next_idx = max_idx + 1 if used else 1
    seen_urls: set[str] = set()
    seen_indices: set[int] = set()
    result: List[ScrapedLink] = []

    for link in links:
        if link.url in seen_urls:
            continue
        seen_urls.add(link.url)

        idx = link.idx
        if idx is None or idx in seen_indices:
            while next_idx in seen_indices:
                next_idx += 1
            idx = next_idx
            next_idx += 1

        seen_indices.add(idx)
        result.append(ScrapedLink(idx=idx, url=link.url, path=link.path, name=link.name))

    result.sort(key=lambda item: item.idx or 0)
    return result


def collect_emload_links(page: Page, list_url: str) -> List[ScrapedLink]:
    collected: List[ScrapedLink] = []
    visited_folders: set[str] = set()

    def walk(folder_url: str, path: Tuple[str, ...]) -> None:
        norm_url = _normalize_url(list_url, folder_url)
        if norm_url in visited_folders:
            return
        visited_folders.add(norm_url)

        page.goto(norm_url, wait_until="networkidle")
        entries = _parse_listing_entries(page)
        for entry in entries:
            href = entry.get("href")
            if not isinstance(href, str):
                continue
            name = entry.get("name")
            display_name = name if isinstance(name, str) and name.strip() else None
            is_folder = bool(entry.get("isFolder"))
            url = _normalize_url(norm_url, href)
            if is_folder:
                next_path = path + (display_name or _folder_fallback_name(url),)
                walk(url, next_path)
                continue
            match = EMLOAD_LINK_RE.match(url)
            idx = int(match.group(1)) if match else None
            collected.append(ScrapedLink(idx=idx, url=url, path=path, name=display_name))

    walk(list_url, ())
    return _assign_missing_indices(collected)


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


def _write_links_json(links: List[ScrapedLink], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = _unique_out_path(out_path)
    payload = []
    for link in links:
        entry: Dict[str, object] = {
            "idx": link.idx,
            "url": link.url,
        }
        if link.path:
            entry["path"] = list(link.path)
        if link.name:
            entry["name"] = link.name
        payload.append(entry)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def run_scrape(
    list_url: str,
    cookies_path: Path,
    out_path: Path,
    headless: bool = True,
) -> List[ScrapedLink]:
    cookies = load_playwright_cookies(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=False)
        context.add_cookies(cookies)

        page = context.new_page()
        pairs = collect_emload_links(page, list_url)
        browser.close()

    out_path = _write_links_json(pairs, out_path)

    indices = [link.idx for link in pairs if link.idx is not None]
    gaps = _find_gaps(indices)
    if pairs:
        print_line(
            f"Scraped {len(pairs)} links. "
            f"Min idx={pairs[0].idx} Max idx={pairs[-1].idx} Gaps={len(gaps)}"
        )
    else:
        print_line("No emload links found. Check LIST_URL or login status.")

    if gaps:
        print_line(f"Missing indices (first 20): {gaps[:20]}")

    print_line(f"Wrote: {out_path}")
    return pairs
