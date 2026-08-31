"""Compute pairwise dashboard similarity from a lineage crawl.

Jaccard similarity over each document's set of tile hashes. Pairs with zero
overlap are skipped so the output stays small on large instances.

Usage:
    python similarity.py --lineage out/lineage.csv --out-dir out
    # writes dashboard_similarity.csv
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from itertools import combinations
from pathlib import Path

EXACT_THRESHOLD = 1.0
MERGE_THRESHOLD = 0.7

COLUMNS = [
    "snapshot_date", "doc_id_a", "doc_name_a", "doc_id_b", "doc_name_b",
    "shared_tiles", "tiles_a", "tiles_b", "similarity", "verdict",
]


def load_hashes(lineage_csv: str) -> tuple[dict, dict]:
    hashes: dict[str, set] = {}
    names: dict[str, str] = {}
    with open(lineage_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            hashes.setdefault(row["doc_id"], set()).add(row["tile_hash"])
            names[row["doc_id"]] = row["document"]
    return hashes, names


def score(hashes: dict, names: dict) -> list[dict]:
    today = date.today().isoformat()
    pairs = []
    for (a, ha), (b, hb) in combinations(sorted(hashes.items()), 2):
        shared = len(ha & hb)
        if shared == 0:
            continue
        sim = shared / len(ha | hb)
        verdict = ("exact_duplicate" if sim >= EXACT_THRESHOLD
                   else "merge_candidate" if sim >= MERGE_THRESHOLD else "ok")
        pairs.append({
            "snapshot_date": today,
            "doc_id_a": a, "doc_name_a": names[a],
            "doc_id_b": b, "doc_name_b": names[b],
            "shared_tiles": shared,
            "tiles_a": len(ha), "tiles_b": len(hb),
            "similarity": round(sim, 2),
            "verdict": verdict,
        })
    pairs.sort(key=lambda p: -p["similarity"])
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", default="out/lineage.csv")
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()

    hashes, names = load_hashes(args.lineage)
    pairs = score(hashes, names)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "dashboard_similarity.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(pairs)

    flagged = [p for p in pairs if p["verdict"] != "ok"]
    print(f"{len(pairs)} overlapping pairs; {len(flagged)} flagged:")
    for p in flagged[:20]:
        print(f"  {p['similarity']:.2f}  {p['doc_name_a']}  <->  {p['doc_name_b']}  ({p['verdict']})")


if __name__ == "__main__":
    main()
