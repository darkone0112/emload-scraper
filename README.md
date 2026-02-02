# Emload Scraper/Downloader

This project automates scraping Emload listing pages and downloading all files with resume support and a daily bandwidth cap.

## Requirements

- Python 3.10+
- Playwright (installed via pip)
- A Firefox-exported cookies JSON file for emload.com

## Setup

Create and activate a virtual environment, then install dependencies:
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m playwright install
```

On Arch-based systems (EndeavourOS), `playwright install-deps` is not supported. If you hit missing-library errors, install the required system packages and re-run:
```
python -m playwright install
```

Common Arch packages you may need:
```
sudo pacman -S --needed \
  libicu \
  libxml2 \
  libflite \
  libx11 \
  libxcomposite \
  libxdamage \
  libxrandr \
  libxkbcommon \
  libxext \
  libxcb \
  libxfixes \
  libxi \
  libxrender \
  libxshmfence \
  libdrm \
  mesa \
  alsa-lib \
  atk \
  cairo \
  cups \
  dbus \
  expat \
  fontconfig \
  freetype2 \
  gdk-pixbuf2 \
  glib2 \
  gtk3 \
  nspr \
  nss \
  pango \
  zlib
```

If `sudo playwright install-deps` fails with "command not found", run it via the venv python:
```
sudo ./venv/bin/python -m playwright install-deps
```

## Quick Start

1) Export cookies from Firefox and place them at:
```
data/emload_cookies.json
```

2) Verify login:
```
python -m emload_downloader verify-login --cookies data/emload_cookies.json
```

3) Scrape a listing page:
```
python -m emload_downloader scrape --list-url "<LIST_URL>" --out data/links.json
```

4) Download all files in bulk (defaults: 5 workers, 35 GB/day limit):
```
python -m emload_downloader run --links data/links.json --headless
```

## Interactive Menu

Run without arguments to use the interactive menu:
```
python -m emload_downloader
```

## Wizard

Interactive scrape + bulk download:
```
python -m emload_downloader wizard
```

## Commands

- Verify login:
```
python -m emload_downloader verify-login --cookies data/emload_cookies.json
```

- Scrape listing page:
```
python -m emload_downloader scrape --list-url "<LIST_URL>" --out data/links.json
```

- Download one file:
```
python -m emload_downloader download-one --url "<V2_FILE_URL>"
```

- Download one file from links.json:
```
python -m emload_downloader download-one --from-links data/links.json --idx 12
```

- Bulk download:
```
python -m emload_downloader run --links data/links.json --headless
```

## Jobs and Output Layout

You can run multiple scrapes and keep them separate with job folders:

- Links: `data/jobs/<job>/links.json`
- State: `data/jobs/<job>/state.json`
- Downloads: `downloads/<job>/`

Run a specific job:
```
python -m emload_downloader run --job <job-name> --headless
```

## Resume and Bandwidth Limits

- Downloads are tracked in `data/state.json` (or job-specific state files).
- The downloader skips files that already exist in the download folder using the `NNNN_` filename prefix.
- The daily bandwidth cap is enforced locally. If the site indicates a bandwidth limit, the downloader pauses until the next day.

## Notes

- `data/` and `downloads/` are gitignored (only folder placeholders are tracked).
- Scraping writes `links.json`. If the file already exists, a new file is created as `links_1.json`, `links_2.json`, etc.
