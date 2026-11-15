"""Extract source data for the pipeline."""
"""Extract generation mix and carbon intensity for a month from the NESO API."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import API_BASE

RAW_DIR = Path("data/raw")
TIMEOUT = 60
MAX_ATTEMPTS = 4


def fetch_json(endpoint, start, end):
    """GET {API_BASE}/{endpoint}/{start}/{end} with retries and backoff."""
    url = f"{API_BASE}/{endpoint}/{start}/{end}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()["data"]
        except requests.exceptions.RequestException as error:
            if attempt == MAX_ATTEMPTS:
                raise
            wait = 2 ** attempt            # 2, 4, 8 seconds
            print(f"  attempt {attempt} failed ({error.__class__.__name__}), retrying in {wait}s")
            time.sleep(wait)


def extract_month(month):
    """month like '2026-09'. Returns dict of raw payloads and saves snapshots."""
    year, mon = (int(x) for x in month.split("-"))
    start = f"{month}-01T00:00Z"
    end = f"{year + (mon == 12)}-{1 if mon == 12 else mon + 1:02d}-01T00:00Z"

    payload = {
        "generation": fetch_json("generation", start, end),
        "intensity": fetch_json("intensity", start, end),
    }

    snapshot_dir = RAW_DIR / month
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name, data in payload.items():
        path = snapshot_dir / f"{name}_{stamp}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        print(f"  saved {path}  ({len(data)} records)")

    return payload


if __name__ == "__main__":
    print("Extracting 2026-09 ...")
    payload = extract_month("2026-09")
    print(f"generation records: {len(payload['generation'])}")
    print(f"intensity records : {len(payload['intensity'])}")