"""Which documents use a given view, field, or topic?

Thin wrapper around Omni's content-validator find API - the blast-radius
report to run before editing or deleting any view (query views included).

Usage:
    OMNI_BASE_URL=... OMNI_TOKEN=... \
    python find_view_usage.py --model-id <uuid> --find users_facts --type VIEW
    python find_view_usage.py --model-id <uuid> --find orders.status --type FIELD
"""
from __future__ import annotations

import argparse
import os
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--find", required=True)
    parser.add_argument("--type", required=True, choices=["VIEW", "FIELD", "TOPIC"])
    parser.add_argument("--branch-id", default=None)
    parser.add_argument("--include-personal", action="store_true", default=True)
    args = parser.parse_args()

    base = os.environ.get("OMNI_BASE_URL", "").rstrip("/")
    token = os.environ.get("OMNI_TOKEN", "")
    if not base or not token:
        sys.exit("Set OMNI_BASE_URL and OMNI_TOKEN environment variables.")

    params = {
        "find": args.find,
        "find_type": args.type,
        "include_personal_folders": str(args.include_personal).lower(),
    }
    if args.branch_id:
        params["branch_id"] = args.branch_id

    resp = requests.get(
        f"{base}/api/v1/models/{args.model_id}/content-validator",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json().get("content", [])

    if not content:
        print(f"No documents reference {args.type} '{args.find}'.")
        return

    print(f"{len(content)} document(s) reference {args.type} '{args.find}':\n")
    for doc in content:
        folder = (doc.get("folder") or {}).get("path", "(personal)")
        owner = (doc.get("owner") or {}).get("name", "?")
        print(f"  {doc.get('name')}  [{folder}]  owner: {owner}")
        for qi in doc.get("queries_and_issues", []):
            print(f"      tile: {qi.get('query_name')}")


if __name__ == "__main__":
    main()
