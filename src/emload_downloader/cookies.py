from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Union


def load_raw_cookies(path: Union[str, Path]) -> Any:
    """
    Loads a cookie export from Firefox/extensions.
    Expected: a JSON list of cookies, or a dict containing a cookies list.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Cookie file not found: {p}")

    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return raw


def normalize_for_playwright(raw: Any) -> List[Dict[str, Any]]:
    """
    Convert common browser-exported cookie JSON formats into Playwright-compatible cookies.

    Playwright expects a list of dicts like:
      {name, value, domain, path, secure, httpOnly, sameSite?, expires?}

    Notes:
    - If expires is omitted, cookie becomes a session cookie in the context.
    - We DO NOT print cookie values anywhere.
    """
    # Some exporters wrap cookies in an object
    if isinstance(raw, dict):
        raw = raw.get("cookies") or raw.get("Cookies") or raw.get("data") or raw.get("items") or []

    if not isinstance(raw, list):
        raise ValueError("Cookie JSON must be a list (or a dict containing a list). Re-export as JSON.")

    now = int(time.time())
    out: List[Dict[str, Any]] = []

    for c in raw:
        if not isinstance(c, dict):
            continue

        name = c.get("name")
        value = c.get("value")

        if not name or value is None:
            continue

        cookie: Dict[str, Any] = {
            "name": str(name),
            "value": str(value),
            "domain": c.get("domain") or ".emload.com",
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", c.get("httponly", False))),
        }

        # SameSite mapping: Playwright accepts "Strict" | "Lax" | "None"
        ss = c.get("sameSite") or c.get("samesite")
        if isinstance(ss, str):
            s = ss.strip().lower()
            if s in ("lax", "strict", "none"):
                cookie["sameSite"] = s.capitalize() if s != "none" else "None"

        # Expiration mapping (if present and in the future)
        exp = c.get("expirationDate") or c.get("expiry") or c.get("expires")
        if isinstance(exp, (int, float)):
            exp_i = int(exp)
            if exp_i > now:
                cookie["expires"] = exp_i

        out.append(cookie)

    if not out:
        raise ValueError("No cookies parsed. Ensure you exported cookies for emload.com while logged in.")

    return out


def load_playwright_cookies(path: Union[str, Path]) -> List[Dict[str, Any]]:
    raw = load_raw_cookies(path)
    return normalize_for_playwright(raw)
