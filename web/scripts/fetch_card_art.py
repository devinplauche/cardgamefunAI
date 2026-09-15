#!/usr/bin/env python3
"""Fetch official Hero Realms card scans into web/public/cards/.

The scans belong to Wise Wizard Games and are not licensed for
redistribution, so the JPEGs themselves are gitignored (see .gitignore).
Only web/public/cards/sources.json - the URL catalog - is tracked.
Run this once after cloning::

    python3 web/scripts/fetch_card_art.py

Existing files are skipped unless --force is given.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

CARDS_DIR = Path(__file__).resolve().parents[1] / "public" / "cards"
SOURCES = CARDS_DIR / "sources.json"


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "cardgamefunAI-art-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        data = resp.read()
    if len(data) < 1024:
        raise RuntimeError(f"suspiciously small payload ({len(data)} bytes) for {url}")
    dest.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="re-download even if the file already exists")
    args = parser.parse_args()

    catalog = json.loads(SOURCES.read_text())
    ok, skipped, failed = 0, 0, 0
    for name, entry in catalog.items():
        dest = CARDS_DIR / entry["file"]
        if dest.exists() and not args.force:
            skipped += 1
            continue
        try:
            fetch(entry["source"], dest)
            print(f"  fetched {dest.name} ({name})")
            ok += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAILED {dest.name} ({name}): {exc}", file=sys.stderr)
            failed += 1
    print(f"done: {ok} fetched, {skipped} already present, {failed} failed "
          f"({len(catalog)} in catalog)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
