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


PACE_SECONDS = float(os.environ.get("PACE_SECONDS", "1.1"))  # stay under 60 req/min
MAX_DOCS = int(os.environ.get("MAX_DOCS", "0"))              # 0 = crawl everything
MODEL_FILTER = os.environ.get("MODEL_FILTER", "").strip()    # comma-separated model UUIDs: crawl only their documents


def get(path: str, params: dict | None = None, retries: int = 10) -> dict:
    """GET with paced 429 backoff (document-queries is ~60 req/min)."""
    url = f"{BASE_URL}/api/v1{path}"
    for attempt in range(retries):
        resp = SESSION.get(url, params=params, timeout=60)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "")
            wait = int(retry_after) if retry_after.isdigit() else min(2 ** attempt, 60)
            time.sleep(max(wait, 5))
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

    if MODEL_FILTER:
        model_doc_ids: set = set()
        for mid in [m.strip() for m in MODEL_FILTER.split(",") if m.strip()]:
            body = get(f"/models/{mid}/content-validator",
                       {"include_personal_folders": "true"})
            found = {d.get("identifier") or d.get("document_id")
                     for d in body.get("content", [])}
            print(f"Model {mid}: {len(found)} documents")
            model_doc_ids |= found
        docs = [d for d in docs if d["identifier"] in model_doc_ids]
        print(f"Model filter: {len(docs)} documents across filtered models")

    if MAX_DOCS:
        docs = docs[:MAX_DOCS]
        print(f"Capped to {len(docs)} documents (MAX_DOCS={MAX_DOCS})")

    skipped = 0
    for i, doc in enumerate(docs, 1):
        doc_id = doc["identifier"]
        time.sleep(PACE_SECONDS)
        try:
            body = get(f"/documents/{doc_id}/queries")
        except requests.HTTPError:
            skipped += 1  # typically 404: workbook without a dashboard
            continue

        count = doc.get("_count") or {}
        for q in body.get("queries", []):
            query = q.get("query") or {}
            # No per-query modelId check: workbook queries carry the workbook
            # model's id, which extends the shared model. The content-validator
            # document filter above already scopes the crawl to MODEL_FILTER.
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
    print(f"Done: {len(docs)} documents, {skipped} skipped (no dashboard queries)")
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
