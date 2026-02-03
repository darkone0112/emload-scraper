from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from emload_downloader.bulk import run_bulk_download
from emload_downloader.checks import check_downloads
from emload_downloader.download import run_download_one
from emload_downloader.jobs import list_jobs
from emload_downloader.links import infer_out_dir, infer_state_path
from emload_downloader.scrape import run_scrape
from emload_downloader.state import StateManager
from emload_downloader.ui import console, has_rich, prompt, prompt_bool, prompt_float, prompt_int, print_line
from emload_downloader.verify_login import verify_login
from emload_downloader.wizard import run_wizard


def _choose_job() -> Optional[str]:
    jobs = list_jobs()
    if not jobs:
        print_line("No jobs found.")
        return None
    for i, name in enumerate(jobs, 1):
        print_line(f"{i}. {name}")
    choice = prompt("Select job by number or name")
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(jobs):
            return jobs[idx - 1]
    if choice in jobs:
        return choice
    print_line("Invalid selection.")
    return None


def _choose_links_json() -> Optional[Path]:
    data_dir = Path("data")
    if not data_dir.exists():
        print_line("Missing data/ directory.")
        return None
    files = sorted([p for p in data_dir.rglob("*.json") if p.is_file()])
    candidates: list[Path] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "url" in first and "idx" in first:
                candidates.append(path)
    files = candidates
    if not files:
        print_line("No links JSON files found in data/.")
        return None
    for i, path in enumerate(files, 1):
        rel = path.relative_to(data_dir)
        print_line(f"{i}. {rel}")
    choice = prompt("Select file by number or name")
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(files):
            return files[idx - 1]
    for path in files:
        rel = str(path.relative_to(data_dir))
        if choice == path.name or choice == rel:
            return path
    print_line("Invalid selection.")
    return None


def _menu_verify_login() -> None:
    cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
    url = prompt("URL", "https://www.emload.com/")
    headless = prompt_bool("Headless browser?", False)
    verify_login(cookies, url, headless=headless)


def _menu_scrape() -> None:
    list_url = prompt("Listing URL")
    if not list_url:
        print_line("Listing URL required.")
        return
    cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
    out_path = Path(prompt("Output path", "data/links.json"))
    headless = prompt_bool("Headless browser?", True)
    run_scrape(list_url, cookies, out_path, headless=headless)


def _menu_download_one() -> None:
    from_links = prompt_bool("Use links.json?", True)
    if from_links:
        links = Path(prompt("Links path", "data/links.json"))
        idx = prompt_int("Index (blank for first)", None)
        cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
        out_dir = Path(prompt("Output dir", "downloads"))
        headless = prompt_bool("Headless browser?", True)
        run_download_one(
            url=None,
            links_path=links,
            idx=idx,
            cookies_path=cookies,
            download_dir=out_dir,
            headless=headless,
        )
    else:
        url = prompt("V2 file URL")
        if not url:
            print_line("URL required.")
            return
        idx = prompt_int("Index (optional)", None)
        cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
        out_dir = Path(prompt("Output dir", "downloads"))
        headless = prompt_bool("Headless browser?", True)
        run_download_one(
            url=url,
            idx=idx,
            cookies_path=cookies,
            download_dir=out_dir,
            headless=headless,
        )


def _menu_bulk_run() -> None:
    links_path = _choose_links_json()
    if not links_path:
        return
    default_state = infer_state_path(links_path)
    default_out_dir = infer_out_dir(links_path)
    state_path = Path(prompt("State path", str(default_state)))
    out_dir = Path(prompt("Output dir", str(default_out_dir)))

    cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
    mode = prompt("Start from beginning or specific idx? (b/s or number)", "b").lower()
    start = None
    if mode.isdigit():
        start = int(mode)
    elif mode.startswith("s"):
        start = prompt_int("Start index", None)
    end = prompt_int("End index (blank for none)", None)
    workers = prompt_int("Workers", 5) or 5
    delay = prompt_float("Delay seconds", 0.5) or 0.5
    retries = prompt_int("Retries", 3) or 3
    daily_limit = prompt_float("Daily limit GB", 35.0) or 35.0
    headless = prompt_bool("Headless browser?", True)

    run_bulk_download(
        links_path=links_path,
        cookies_path=cookies,
        out_dir=out_dir,
        state_path=state_path,
        start=start,
        end=end,
        workers=workers,
        retries=retries,
        delay_s=delay,
        selector=None,
        headless=headless,
        timeout_ms=30000,
        daily_limit_gb=daily_limit,
    )


def _menu_check_downloads() -> None:
    links_path = _choose_links_json()
    if not links_path:
        return
    default_out_dir = infer_out_dir(links_path)
    out_dir = Path(prompt("Output dir", str(default_out_dir)))
    start = prompt_int("Start index (blank for none)", None)
    end = prompt_int("End index (blank for none)", None)
    if start is not None and end is not None and end < start:
        print_line("End index must be greater than or equal to start index.")
        return

    try:
        result = check_downloads(links_path, out_dir, start=start, end=end)
    except Exception as exc:
        print_line(f"Check failed: {exc}")
        return

    if result.total == 0:
        print_line("No links to check in selected range.")
        return

    print_line(
        f"Checked {result.total} links. "
        f"Present={result.present} Missing={len(result.missing)} Extra={len(result.extra)}"
    )

    if result.missing:
        if has_rich():
            from rich.table import Table

            table = Table(title="Missing indices")
            table.add_column("Idx", justify="right", no_wrap=True)
            for idx in result.missing[:50]:
                table.add_row(f"{idx:04d}")
            if len(result.missing) > 50:
                table.add_row(f"... +{len(result.missing) - 50} more")
            console().print(table)
        else:
            preview = ", ".join(str(idx) for idx in result.missing[:20])
            suffix = f" ... (+{len(result.missing) - 20} more)" if len(result.missing) > 20 else ""
            print_line(f"Missing indices: {preview}{suffix}")

    if result.extra:
        preview = ", ".join(str(idx) for idx in result.extra[:20])
        suffix = f" ... (+{len(result.extra) - 20} more)" if len(result.extra) > 20 else ""
        print_line(f"Extra files not in links: {preview}{suffix}")

    if result.missing and prompt_bool("Download missing files now?", False):
        state_path = Path(prompt("State path", str(infer_state_path(links_path))))
        cookies = Path(prompt("Cookies path", "data/emload_cookies.json"))
        workers = prompt_int("Workers", 5) or 5
        delay = prompt_float("Delay seconds", 0.5) or 0.5
        retries = prompt_int("Retries", 3) or 3
        daily_limit = prompt_float("Daily limit GB", 35.0) or 35.0
        headless = prompt_bool("Headless browser?", True)

        state = StateManager(state_path, download_dir=out_dir)
        removed = state.clear_completed(result.missing)
        if removed:
            print_line(f"Cleared {removed} completed entries from state.")

        run_bulk_download(
            links_path=links_path,
            cookies_path=cookies,
            out_dir=out_dir,
            state_path=state_path,
            start=start,
            end=end,
            workers=workers,
            retries=retries,
            delay_s=delay,
            selector=None,
            headless=headless,
            timeout_ms=30000,
            daily_limit_gb=daily_limit,
        )


def run_menu() -> None:
    while True:
        print_line("\nEmload Downloader Menu")
        print_line("1) Verify login")
        print_line("2) Scrape listing page")
        print_line("3) Download one file")
        print_line("4) Bulk download")
        print_line("5) Check downloads")
        print_line("6) Wizard (scrape + bulk)")
        print_line("7) List jobs")
        print_line("0) Exit")
        choice = prompt("Choose an option", "0")
        if choice == "1":
            _menu_verify_login()
        elif choice == "2":
            _menu_scrape()
        elif choice == "3":
            _menu_download_one()
        elif choice == "4":
            _menu_bulk_run()
        elif choice == "5":
            _menu_check_downloads()
        elif choice == "6":
            run_wizard()
        elif choice == "7":
            jobs = list_jobs()
            if not jobs:
                print_line("No jobs found.")
            else:
                for name in jobs:
                    print_line(f"- {name}")
        elif choice == "0":
            return
        else:
            print_line("Invalid option.")
