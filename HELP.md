# Emload Downloader — Command Help

This file will document all CLI commands and examples.

## Quick start

Activate venv:
```
source venv/bin/activate
```

Create venv and install deps (first time):
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install
```

Verify login:
```
python -m emload_downloader verify-login --cookies data/emload_cookies.json
```

Scrape listing page:
```
python -m emload_downloader scrape --list-url "<LIST_URL>" --out data/links.json
```

Download one by URL:
```
python -m emload_downloader download-one --url "<V2_FILE_URL>"
```

Download one from links.json:
```
python -m emload_downloader download-one --from-links data/links.json
```

Download one from links.json by index:
```
python -m emload_downloader download-one --from-links data/links.json --idx 12
```

Bulk download (5 workers, 35 GB/day limit by default):
```
python -m emload_downloader run --links data/links.json --headless
```

Bulk download with range and custom options:
```
python -m emload_downloader run --links data/links.json --start 201 --workers 5 --daily-limit-gb 35 --headless
```

Wizard (interactive scrape + bulk download):
```
python -m emload_downloader wizard
```

Menu (all options):
```
python -m emload_downloader
```

Job layout (per listing page):
- Links: `data/jobs/<job>/links.json`
- State: `data/jobs/<job>/state.json`
- Downloads: `downloads/<job>/`

Run a specific job directly:
```
python -m emload_downloader run --job <job-name> --headless
```
