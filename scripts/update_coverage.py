#!/usr/bin/env python3
"""Fetch the live Geizhals catalogue counts and write ``coverage.json``.

The README's shields.io badges read that file, and a scheduled GitHub Action
runs this script to keep the numbers fresh. Geizhals has no JSON stats API, but
its homepage renders a "Zahlen & Fakten" block server-side, so we parse the
``facts__value`` / ``facts__label`` spans out of the HTML.
"""

import datetime
import gzip
import html
import json
import re
import urllib.request
from pathlib import Path

HOME_URL = "https://geizhals.at/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# facts__label text (matched case-insensitively as a substring) -> coverage key
LABELS = {
    "gelistete artikel": "products",
    "preise": "prices",
    "ndler": "merchants",  # "aktive Händler", matched umlaut-free
}


def fetch_counts() -> dict[str, int]:
    request = urllib.request.Request(HOME_URL, headers={
        "User-Agent": UA,
        "Accept-Language": "de-AT,de;q=0.9",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    page = body.decode("utf-8", "replace")

    pairs = re.findall(
        r'facts__value">([\d.]+)</span>\s*<span class="facts__label">(.*?)</span>',
        page,
    )
    counts: dict[str, int] = {}
    for value, label in pairs:
        label = html.unescape(re.sub("<.*?>", "", label)).strip().lower()
        for needle, key in LABELS.items():
            if needle in label:
                counts[key] = int(value.replace(".", ""))
    missing = set(LABELS.values()) - set(counts)
    if missing:
        raise SystemExit(f"could not parse {sorted(missing)} from {HOME_URL} "
                         "(page layout changed or the request was blocked)")
    return counts


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def main() -> None:
    counts = fetch_counts()

    coverage = {"updated": datetime.date.today().isoformat()}
    for key in ("products", "prices", "merchants"):
        coverage[key] = human(counts[key])
        coverage[f"{key}_count"] = counts[key]

    out = Path(__file__).resolve().parent.parent / "coverage.json"
    out.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
