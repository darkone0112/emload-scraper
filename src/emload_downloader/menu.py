from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from emload_downloader.bulk import run_bulk_download
from emload_downloader.download import run_download_one
from emload_downloader.jobs import list_jobs
from emload_downloader.scrape import run_scrape
from emload_downloader.verify_login import verify_login
from emload_downloader.wizard import run_wizard


def _prompt(text: str, default: Optional[str] = None) -> str:
    if default:
        prompt = f"{text} [{default}]: "
    else:
        prompt = f"{text}: "
    value = input(prompt).strip()
    return value or (default or "")


def _prompt_bool(text: str, default: bool = True) -> bool:
    default_str = "y" if default else "n"
    value = _prompt(text, default_str).lower()
    if value in ("y", "yes", "true", "1"):
        return True
    if value in ("n", "no", "false", "0"):
        return False
    return default


def _prompt_int(text: str, default: Optional[int] = None) -> Optional[int]:
    default_str = "" if default is None else str(default)
    value = _prompt(text, default_str)
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        print("Invalid number.")
        return None


def _prompt_float(text: str, default: Optional[float] = None) -> Optional[float]:
    default_str = "" if default is None else str(default)
    value = _prompt(text, default_str)
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        print("Invalid number.")
        return None


def _choose_job() -> Optional[str]:
    jobs = list_jobs()
    if not jobs:
        print("No jobs found.")
        return None
    for i, name in enumerate(jobs, 1):
        print(f"{i}. {name}")
    choice = _prompt("Select job by number or name")
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(jobs):
            return jobs[idx - 1]
    if choice in jobs:
        return choice
    print("Invalid selection.")
    return None


def _choose_links_json() -> Optional[Path]:
    data_dir = Path("data")
    if not data_dir.exists():
        print("Missing data/ directory.")
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
        print("No links JSON files found in data/.")
        return None
    for i, path in enumerate(files, 1):
        rel = path.relative_to(data_dir)
        print(f"{i}. {rel}")
    choice = _prompt("Select file by number or name")
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(files):
            return files[idx - 1]
    for path in files:
        rel = str(path.relative_to(data_dir))
        if choice == path.name or choice == rel:
            return path
    print("Invalid selection.")
    return None


def _menu_verify_login() -> None:
    cookies = Path(_prompt("Cookies path", "data/emload_cookies.json"))
    url = _prompt("URL", "https://www.emload.com/")
    headless = _prompt_bool("Headless browser?", False)
    verify_login(cookies, url, headless=headless)


def _menu_scrape() -> None:
    list_url = _prompt("Listing URL")
    if not list_url:
        print("Listing URL required.")
        return
    cookies = Path(_prompt("Cookies path", "data/emload_cookies.json"))
    out_path = Path(_prompt("Output path", "data/links.json"))
    headless = _prompt_bool("Headless browser?", True)
    run_scrape(list_url, cookies, out_path, headless=headless)


def _menu_download_one() -> None:
    from_links = _prompt_bool("Use links.json?", True)
    if from_links:
        links = Path(_prompt("Links path", "data/links.json"))
        idx = _prompt_int("Index (blank for first)", None)
        cookies = Path(_prompt("Cookies path", "data/emload_cookies.json"))
        out_dir = Path(_prompt("Output dir", "downloads"))
        headless = _prompt_bool("Headless browser?", True)
        run_download_one(
            url=None,
            links_path=links,
            idx=idx,
            cookies_path=cookies,
            download_dir=out_dir,
            headless=headless,
        )
    else:
        url = _prompt("V2 file URL")
        if not url:
            print("URL required.")
            return
        idx = _prompt_int("Index (optional)", None)
        cookies = Path(_prompt("Cookies path", "data/emload_cookies.json"))
        out_dir = Path(_prompt("Output dir", "downloads"))
        headless = _prompt_bool("Headless browser?", True)
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
    state_path = Path(_prompt("State path", "data/state.json"))
    out_dir = Path(_prompt("Output dir", "downloads"))

    cookies = Path(_prompt("Cookies path", "data/emload_cookies.json"))
    mode = _prompt("Start from beginning or specific idx? (b/s or number)", "b").lower()
    start = None
    if mode.isdigit():
        start = int(mode)
    elif mode.startswith("s"):
        start = _prompt_int("Start index", None)
    end = _prompt_int("End index (blank for none)", None)
    workers = _prompt_int("Workers", 5) or 5
    delay = _prompt_float("Delay seconds", 0.5) or 0.5
    retries = _prompt_int("Retries", 3) or 3
    daily_limit = _prompt_float("Daily limit GB", 35.0) or 35.0
    headless = _prompt_bool("Headless browser?", True)

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
        print("\nEmload Downloader Menu")
        print("1) Verify login")
        print("2) Scrape listing page")
        print("3) Download one file")
        print("4) Bulk download")
        print("5) Wizard (scrape + bulk)")
        print("6) List jobs")
        print("0) Exit")
        choice = _prompt("Choose an option", "0")
        if choice == "1":
            _menu_verify_login()
        elif choice == "2":
            _menu_scrape()
        elif choice == "3":
            _menu_download_one()
        elif choice == "4":
            _menu_bulk_run()
        elif choice == "5":
            run_wizard()
        elif choice == "6":
            jobs = list_jobs()
            if not jobs:
                print("No jobs found.")
            else:
                for name in jobs:
                    print(f"- {name}")
        elif choice == "0":
            return
        else:
            print("Invalid option.")
