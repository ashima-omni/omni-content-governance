"""Crawl an Omni instance and build the content lineage dataset.

Walks documents -> tile queries via the Omni REST API and emits one row per
(document, tile, field) with a stable tile hash for duplicate detection.

Usage:
    OMNI_BASE_URL=https://your-org.omniapp.co OMNI_TOKEN=... python crawl.py
    # writes lineage.csv (and lineage.json) to --out-dir (default: ./out)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

BASE_URL = os.environ.get("OMNI_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("OMNI_TOKEN", "")

SESSION = requests.Session()
SESSION.headers["Authorization"] = f"Bearer {TOKEN}"

LINEAGE_COLUMNS = [
    "snapshot_date", "doc_id", "document", "folder_path", "owner_name",
    "doc_views", "doc_favorites", "updated_at", "tile", "tile_url",
    "tile_hash", "topic", "view_name", "field_name", "model_id",
]


def get(path: str, params: dict | None = None, retries: int = 5) -> dict:
    """GET with basic 429 backoff (document-queries is ~60 req/min)."""
    url = f"{BASE_URL}/api/v1{path}"
    for attempt in range(retries):
        resp = SESSION.get(url, params=params, timeout=60)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** attempt))
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Rate limited after {retries} retries: {path}")


def paged(path: str, params: dict | None = None):
    params = dict(params or {}, pageSize=100)
    while True:
        body = get(path, params)
        yield from body.get("records", [])
        info = body.get("pageInfo", {})
        if not info.get("hasNextPage"):
            return
        params["cursor"] = info["nextCursor"]


def tile_hash(query: dict) -> str:
    """Stable hash of a query's analytical core, ignoring presentation."""
    core = {
        "table": query.get("table"),
        "fields": sorted(query.get("fields", [])),
        "filters": query.get("filters", {}),
        "topic": query.get("join_paths_from_topic_name"),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def crawl() -> list[dict]:
    rows: list[dict] = []
    today = date.today().isoformat()
    docs = list(paged("/documents", {"include": "_count"}))
    print(f"Found {len(docs)} documents")

    for i, doc in enumerate(docs, 1):
        doc_id = doc["identifier"]
        try:
            body = get(f"/documents/{doc_id}/queries")
        except requests.HTTPError as exc:
            print(f"  skip {doc_id} ({doc.get('name')}): {exc}", file=sys.stderr)
            continue

        count = doc.get("_count") or {}
        for q in body.get("queries", []):
            query = q.get("query") or {}
            fields = sorted(query.get("fields", [])) or [None]
            for field in fields:
                rows.append({
                    "snapshot_date": today,
                    "doc_id": doc_id,
                    "document": doc.get("name"),
                    "folder_path": (doc.get("folder") or {}).get("path"),
                    "owner_name": (doc.get("owner") or {}).get("name"),
                    "doc_views": count.get("views"),
                    "doc_favorites": count.get("favorites"),
                    "updated_at": doc.get("updatedAt"),
                    "tile": q.get("name"),
                    "tile_url": q.get("url"),
                    "tile_hash": tile_hash(query),
                    "topic": query.get("join_paths_from_topic_name"),
                    "view_name": query.get("table"),
                    "field_name": field,
                    "model_id": query.get("modelId"),
                })
        if i % 25 == 0:
            print(f"  {i}/{len(docs)} documents crawled")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()

    if not BASE_URL or not TOKEN:
        sys.exit("Set OMNI_BASE_URL and OMNI_TOKEN environment variables.")

    rows = crawl()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "lineage.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LINEAGE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "lineage.json").write_text(json.dumps(rows, indent=2))
    print(f"Wrote {len(rows)} lineage rows to {out}/lineage.csv")


if __name__ == "__main__":
    main()
