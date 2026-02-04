from __future__ import annotations

from typing import Callable, Optional

from emload_downloader.bulk import run_bulk_download
from emload_downloader.jobs import (
    default_job_name,
    job_paths,
    jobs_root,
    latest_download_idx,
    list_jobs,
    sanitize_job_name,
)
from emload_downloader.paths import choose_cookie_path
from emload_downloader.scrape import run_scrape
from emload_downloader.ui import prompt, prompt_bool, print_line


def _choose_job(jobs: list[str]) -> Optional[str]:
    if not jobs:
        return None
    while True:
        for i, name in enumerate(jobs, 1):
            print_line(f"{i}. {name}")
        choice = prompt("Select job by number or name")
        if not choice:
            return None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(jobs):
                return jobs[idx - 1]
        if choice in jobs:
            return choice
        print_line("Invalid selection.")


def run_wizard(
    render_target: Optional[Callable[[object, str], None]] = None,
    log_sink: Optional[Callable[[str], None]] = None,
) -> None:
    root = jobs_root()
    root.mkdir(parents=True, exist_ok=True)
    jobs = list_jobs()

    print_line("Wizard: scrape + bulk download")
    print_line("1) New scrape and download")
    print_line("2) Download existing job")
    while True:
        mode = prompt("Choose mode", "1").strip()
        if mode in {"1", "2"}:
            break
        print_line("Invalid option. Choose 1 or 2.")

    if mode.strip() == "2":
        if not jobs:
            print_line("No existing jobs found in data/jobs.")
            return
        job_name = _choose_job(jobs)
        if not job_name:
            return
        _, links_path, state_path, out_dir = job_paths(job_name)
        if not links_path.exists():
            print_line(f"Missing links file: {links_path}")
            return
        cookies_path = choose_cookie_path()
        headless = prompt_bool("Headless browser?", True)
        last_idx = latest_download_idx(out_dir)
        if last_idx is not None:
            print_line(f"Detected latest downloaded idx: {last_idx}")
        default_start = str(last_idx + 1) if last_idx is not None else ""
        start_raw = prompt("Start index (blank for none)", default_start)
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
            screen=False,
            render_target=render_target,
            log_sink=log_sink,
        )
        return

    list_url = prompt("Listing URL")
    if not list_url:
        print_line("Listing URL is required.")
        return

    suggested = default_job_name("emload")
    job_name = sanitize_job_name(prompt("Job name", suggested))
    job_dir, links_path, state_path, out_dir = job_paths(job_name)
    if job_dir.exists():
        print_line(f"Job already exists: {job_dir}")
        return
    job_dir.mkdir(parents=True, exist_ok=True)

    cookies_path = choose_cookie_path()
    headless = prompt_bool("Headless browser?", True)
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
        screen=False,
        render_target=render_target,
        log_sink=log_sink,
    )
