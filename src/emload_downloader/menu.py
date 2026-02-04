from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from emload_downloader.bulk import run_bulk_download
from emload_downloader.checks import check_downloads
from emload_downloader.dashboard import Dashboard
from emload_downloader.download import run_download_one
from emload_downloader.jobs import list_jobs
from emload_downloader.links import infer_out_dir, infer_state_path
from emload_downloader.paths import (
    choose_cookie_path,
    choose_links_output_path,
    choose_output_dir,
    choose_state_path,
)
from emload_downloader.scrape import run_scrape
from emload_downloader.state import StateManager
from emload_downloader.ui import prompt, prompt_bool, prompt_float, prompt_int, print_line
from emload_downloader.verify_login import verify_login
from emload_downloader.wizard import run_wizard


def _choose_job() -> Optional[str]:
    jobs = list_jobs()
    if not jobs:
        print_line("No jobs found.")
        return None
    while True:
        for i, name in enumerate(jobs, 1):
            print_line(f"{i}. {name}")
        choice = prompt("Select job by number or name")
        if choice == "":
            return None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(jobs):
                return jobs[idx - 1]
        if choice in jobs:
            return choice
        print_line("Invalid selection.")


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
    if len(files) == 1:
        only = files[0]
        print_line(f"Using links: {only.relative_to(data_dir)}")
        return only
    while True:
        for i, path in enumerate(files, 1):
            rel = path.relative_to(data_dir)
            print_line(f"{i}. {rel}")
        choice = prompt("Select file by number or name")
        if choice == "":
            return None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(files):
                return files[idx - 1]
        for path in files:
            rel = str(path.relative_to(data_dir))
            if choice == path.name or choice == rel:
                return path
        candidate = Path(choice)
        if candidate.exists():
            return candidate
        print_line("Invalid selection.")


def _menu_verify_login() -> None:
    cookies = choose_cookie_path()
    url = prompt("URL", "https://www.emload.com/")
    headless = prompt_bool("Headless browser?", False)
    verify_login(cookies, url, headless=headless)


def _menu_scrape() -> None:
    list_url = prompt("Listing URL")
    if not list_url:
        print_line("Listing URL required.")
        return
    cookies = choose_cookie_path()
    out_path = choose_links_output_path()
    headless = prompt_bool("Headless browser?", True)
    run_scrape(list_url, cookies, out_path, headless=headless)


def _menu_download_one() -> None:
    from_links = prompt_bool("Use links.json?", True)
    if from_links:
        links_path = _choose_links_json()
        if not links_path:
            return
        idx = prompt_int("Index (blank for first)", None)
        cookies = choose_cookie_path()
        out_dir = choose_output_dir()
        headless = prompt_bool("Headless browser?", True)
        run_download_one(
            url=None,
            links_path=links_path,
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
        cookies = choose_cookie_path()
        out_dir = choose_output_dir()
        headless = prompt_bool("Headless browser?", True)
        run_download_one(
            url=url,
            idx=idx,
            cookies_path=cookies,
            download_dir=out_dir,
            headless=headless,
        )


def _menu_bulk_run(dashboard: Optional[Dashboard]) -> None:
    use_dashboard = dashboard if dashboard and dashboard.active else None
    links_path = _choose_links_json()
    if not links_path:
        return
    if use_dashboard:
        use_dashboard.set_config("Links path", str(links_path))
    default_state = infer_state_path(links_path)
    default_out_dir = infer_out_dir(links_path)
    state_path = choose_state_path(default=default_state)
    if use_dashboard:
        use_dashboard.set_config("State path", str(state_path))
    out_dir = choose_output_dir(default=default_out_dir)
    if use_dashboard:
        use_dashboard.set_config("Output dir", str(out_dir))

    cookies = choose_cookie_path()
    if use_dashboard:
        use_dashboard.set_config("Cookies path", str(cookies))
    start = None
    while True:
        mode = prompt("Start from beginning or specific idx? (b/s or number)", "b").strip().lower()
        if mode == "" or mode.startswith("b"):
            start = None
            break
        if mode.isdigit():
            start = int(mode)
            break
        if mode.startswith("s"):
            start = prompt_int("Start index", None)
            if start is None:
                print_line("Start index required for 's' mode.")
                continue
            break
        print_line("Invalid choice. Enter b, s, or a number.")
    while True:
        end = prompt_int("End index (blank for none)", None)
        if start is not None and end is not None and end < start:
            print_line("End index must be greater than or equal to start index.")
            continue
        break
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
        screen=False,
        render_target=use_dashboard.set_right if use_dashboard else None,
        log_sink=use_dashboard.log if use_dashboard else None,
    )


def _menu_check_downloads(dashboard: Optional[Dashboard]) -> None:
    use_dashboard = dashboard if dashboard and dashboard.active else None
    links_path = _choose_links_json()
    if not links_path:
        return
    if use_dashboard:
        use_dashboard.set_config("Links path", str(links_path))
    default_out_dir = infer_out_dir(links_path)
    out_dir = choose_output_dir(default=default_out_dir)
    if use_dashboard:
        use_dashboard.set_config("Output dir", str(out_dir))
    while True:
        start = prompt_int("Start index (blank for none)", None)
        end = prompt_int("End index (blank for none)", None)
        if start is not None and end is not None and end < start:
            print_line("End index must be greater than or equal to start index.")
            continue
        break

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
        preview = ", ".join(str(idx) for idx in result.missing[:20])
        suffix = f" ... (+{len(result.missing) - 20} more)" if len(result.missing) > 20 else ""
        print_line(f"Missing indices: {preview}{suffix}")

    if result.extra:
        preview = ", ".join(str(idx) for idx in result.extra[:20])
        suffix = f" ... (+{len(result.extra) - 20} more)" if len(result.extra) > 20 else ""
        print_line(f"Extra files not in links: {preview}{suffix}")

    if result.missing and prompt_bool("Download missing files now?", False):
        state_path = choose_state_path(default=infer_state_path(links_path))
        if use_dashboard:
            use_dashboard.set_config("State path", str(state_path))
        cookies = choose_cookie_path()
        if use_dashboard:
            use_dashboard.set_config("Cookies path", str(cookies))
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
            screen=False,
            render_target=use_dashboard.set_right if use_dashboard else None,
            log_sink=use_dashboard.log if use_dashboard else None,
        )


def run_menu() -> None:
    menu_items = [
        "Verify login",
        "Scrape listing page",
        "Download one file",
        "Bulk download",
        "Check downloads",
        "Wizard (scrape + bulk)",
        "List jobs",
    ]
    dashboard = Dashboard(menu_items)
    dashboard.start()
    try:
        while True:
            if not dashboard.active:
                print_line("\nEmload Downloader Menu")
                for i, item in enumerate(menu_items, 1):
                    print_line(f"{i}) {item}")
                print_line("0) Exit")
            choice = prompt("Choose an option", "0").strip()
            if choice.lower() == "test layout":
                if dashboard.active:
                    state = dashboard.show_test_layout()
                    try:
                        while True:
                            exit_choice = prompt("Test layout: enter q to exit", "")
                            if exit_choice.strip().lower() == "q":
                                break
                    finally:
                        dashboard.restore_layout(state)
                else:
                    print_line("Test layout requires Rich dashboard.")
                continue
            if choice not in {"0", "1", "2", "3", "4", "5", "6", "7"}:
                print_line("Invalid option. Choose 0-7.")
                continue
            if choice == "1":
                _menu_verify_login()
            elif choice == "2":
                _menu_scrape()
            elif choice == "3":
                _menu_download_one()
            elif choice == "4":
                _menu_bulk_run(dashboard)
            elif choice == "5":
                _menu_check_downloads(dashboard)
            elif choice == "6":
                use_dashboard = dashboard if dashboard.active else None
                run_wizard(
                    render_target=use_dashboard.set_right if use_dashboard else None,
                    log_sink=use_dashboard.log if use_dashboard else None,
                )
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
    finally:
        dashboard.stop()
