from __future__ import annotations

from pathlib import Path
from typing import Union

from playwright.sync_api import sync_playwright

from emload_downloader.cookies import load_playwright_cookies


def verify_login(
    cookies_path: Union[str, Path],
    test_url: str = "https://www.emload.com/",
    headless: bool = False,
) -> None:
    cookies = load_playwright_cookies(cookies_path)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        context.add_cookies(cookies)

        page = context.new_page()
        page.goto(test_url, wait_until="networkidle")

        print("Check the browser: if you are logged in, cookies injection works.")
        input("Press Enter to close...")

        browser.close()


def main() -> None:
    verify_login(Path("data/emload_cookies.json"))


if __name__ == "__main__":
    main()
