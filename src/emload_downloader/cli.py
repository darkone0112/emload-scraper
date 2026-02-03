from __future__ import annotations

import argparse
from pathlib import Path

from emload_downloader.bulk import run_bulk_download
from emload_downloader.download import run_download_one
from emload_downloader.jobs import job_paths
from emload_downloader.scrape import run_scrape
from emload_downloader.verify_login import verify_login
from emload_downloader.wizard import run_wizard
from emload_downloader.menu import run_menu


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emload_downloader")
    sub = parser.add_subparsers(dest="command")

    verify = sub.add_parser("verify-login", help="Open browser and confirm cookies are valid.")
    verify.add_argument(
        "--cookies",
        type=Path,
        default=Path("data/emload_cookies.json"),
        help="Path to Firefox-exported cookies JSON.",
    )
    verify.add_argument(
        "--url",
        default="https://www.emload.com/",
        help="URL to open after injecting cookies.",
    )
    verify.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended for manual check).",
    )
    verify.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Timeout for initial page load (ms).",
    )

    scrape = sub.add_parser("scrape", help="Scrape listing page for v2/file links.")
    scrape.add_argument("--list-url", required=True, help="Listing page URL.")
    scrape.add_argument(
        "--cookies",
        type=Path,
        default=Path("data/emload_cookies.json"),
        help="Path to Firefox-exported cookies JSON.",
    )
    scrape.add_argument(
        "--out",
        type=Path,
        default=Path("data/links.json"),
        help="Output JSON path.",
    )
    scrape.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )

    dl = sub.add_parser("download-one", help="Download a single file by URL.")
    src_group = dl.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--url", help="Emload v2/file URL.")
    src_group.add_argument(
        "--from-links",
        type=Path,
        help="Path to links.json (uses --idx or first entry).",
    )
    dl.add_argument(
        "--idx",
        type=int,
        help="Optional index to prefix the filename (defaults to parsed from URL).",
    )
    dl.add_argument(
        "--cookies",
        type=Path,
        default=Path("data/emload_cookies.json"),
        help="Path to Firefox-exported cookies JSON.",
    )
    dl.add_argument(
        "--out-dir",
        type=Path,
        default=Path("downloads"),
        help="Directory to save downloads.",
    )
    dl.add_argument(
        "--selector",
        help="Optional CSS selector for the download button.",
    )
    dl.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Timeout for waiting on download (ms).",
    )
    dl.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )

    run = sub.add_parser("run", help="Bulk download from links.json.")
    run_group = run.add_mutually_exclusive_group()
    run_group.add_argument(
        "--job",
        help="Job name under data/jobs (uses job paths).",
    )
    run_group.add_argument(
        "--links",
        type=Path,
        default=Path("data/links.json"),
        help="Path to links.json.",
    )
    run.add_argument(
        "--cookies",
        type=Path,
        default=Path("data/emload_cookies.json"),
        help="Path to Firefox-exported cookies JSON.",
    )
    run.add_argument(
        "--out-dir",
        type=Path,
        default=Path("downloads"),
        help="Directory to save downloads.",
    )
    run.add_argument(
        "--state",
        type=Path,
        default=Path("data/state.json"),
        help="State file path.",
    )
    run.add_argument("--start", type=int, help="Start index (inclusive).")
    run.add_argument("--end", type=int, help="End index (inclusive).")
    run.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of concurrent downloads.",
    )
    run.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per file.",
    )
    run.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between downloads per worker (seconds).",
    )
    run.add_argument(
        "--selector",
        help="Optional CSS selector for the download button.",
    )
    run.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Timeout for waiting on download (ms).",
    )
    run.add_argument(
        "--daily-limit-gb",
        type=float,
        default=35.0,
        help="Daily bandwidth limit in GB (decimal, 1 GB = 1e9 bytes).",
    )
    run.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )

    sub.add_parser("wizard", help="Interactive scrape + bulk download.")
    sub.add_parser("menu", help="Interactive menu for all commands.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        run_menu()
        return
    if args.command == "verify-login":
        verify_login(
            args.cookies,
            args.url,
            headless=args.headless,
            timeout_ms=args.timeout_ms,
        )
    elif args.command == "scrape":
        run_scrape(args.list_url, args.cookies, args.out, headless=args.headless)
    elif args.command == "download-one":
        run_download_one(
            url=args.url,
            cookies_path=args.cookies,
            download_dir=args.out_dir,
            idx=args.idx,
            links_path=args.from_links,
            selector=args.selector,
            headless=args.headless,
            timeout_ms=args.timeout_ms,
        )
    elif args.command == "run":
        if args.job:
            _, links, state, out_dir = job_paths(args.job)
            links_path = links
            state_path = state
            out_dir_path = out_dir
        else:
            links_path = args.links
            state_path = args.state
            out_dir_path = args.out_dir
        run_bulk_download(
            links_path=links_path,
            cookies_path=args.cookies,
            out_dir=out_dir_path,
            state_path=state_path,
            start=args.start,
            end=args.end,
            workers=args.workers,
            retries=args.retries,
            delay_s=args.delay,
            selector=args.selector,
            headless=args.headless,
            timeout_ms=args.timeout_ms,
            daily_limit_gb=args.daily_limit_gb,
        )
    elif args.command == "wizard":
        run_wizard()
    elif args.command == "menu":
        run_menu()


if __name__ == "__main__":
    main()
