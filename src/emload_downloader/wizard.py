from __future__ import annotations

from pathlib import Path
from typing import Optional

from emload_downloader.bulk import run_bulk_download
from emload_downloader.jobs import (
    default_job_name,
    job_paths,
    jobs_root,
    latest_download_idx,
    list_jobs,
    sanitize_job_name,
)
from emload_downloader.scrape import run_scrape


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


def _choose_job(jobs: list[str]) -> Optional[str]:
    if not jobs:
        return None
    for i, name in enumerate(jobs, 1):
        print(f"{i}. {name}")
    choice = _prompt("Select job by number or name")
    if not choice:
        return None
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(jobs):
            return jobs[idx - 1]
    if choice in jobs:
        return choice
    print("Invalid selection.")
    return None


def run_wizard() -> None:
    root = jobs_root()
    root.mkdir(parents=True, exist_ok=True)
    jobs = list_jobs()

    print("Wizard: scrape + bulk download")
    print("1) New scrape and download")
    print("2) Download existing job")
    mode = _prompt("Choose mode", "1")

    if mode.strip() == "2":
        if not jobs:
            print("No existing jobs found in data/jobs.")
            return
        job_name = _choose_job(jobs)
        if not job_name:
            return
        _, links_path, state_path, out_dir = job_paths(job_name)
        if not links_path.exists():
            print(f"Missing links file: {links_path}")
            return
        cookies_path = Path(_prompt("Cookies path", "data/emload_cookies.json"))
        headless = _prompt_bool("Headless browser?", True)
        last_idx = latest_download_idx(out_dir)
        if last_idx is not None:
            print(f"Detected latest downloaded idx: {last_idx}")
        default_start = str(last_idx + 1) if last_idx is not None else ""
        start_raw = _prompt("Start index (blank for none)", default_start)
        start = int(start_raw) if start_raw else None
        run_bulk_download(
            links_path=links_path,
            cookies_path=cookies_path,
            out_dir=out_dir,
            state_path=state_path,
            start=start,
            end=None,
            workers=5,
            retries=3,
            delay_s=0.5,
            selector=None,
            headless=headless,
            timeout_ms=30000,
            daily_limit_gb=35.0,
        )
        return

    list_url = _prompt("Listing URL")
    if not list_url:
        print("Listing URL is required.")
        return

    suggested = default_job_name("emload")
    job_name = sanitize_job_name(_prompt("Job name", suggested))
    job_dir, links_path, state_path, out_dir = job_paths(job_name)
    if job_dir.exists():
        print(f"Job already exists: {job_dir}")
        return
    job_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = Path(_prompt("Cookies path", "data/emload_cookies.json"))
    headless = _prompt_bool("Headless browser?", True)

    run_scrape(list_url, cookies_path, links_path, headless=headless)
    run_bulk_download(
        links_path=links_path,
        cookies_path=cookies_path,
        out_dir=out_dir,
        state_path=state_path,
        start=None,
        end=None,
        workers=5,
        retries=3,
        delay_s=0.5,
        selector=None,
        headless=headless,
        timeout_ms=30000,
        daily_limit_gb=35.0,
    )
