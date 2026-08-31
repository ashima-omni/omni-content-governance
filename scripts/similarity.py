"""Compute pairwise dashboard similarity from a lineage crawl.

Two signals per pair:
- similarity: Jaccard over tile hashes. Catches copy-then-trim/extend sprawl,
  where whole tiles are shared verbatim.
- field_similarity: Jaccard over each document's set of view.field references.
  Catches copied-then-tweaked dashboards whose tiles no longer hash equal
  because a field was added or swapped.

A pair is recorded when tiles overlap or field_similarity >= FIELD_FLOOR.
Verdicts: exact_duplicate (tile sim 1.0), merge_candidate (tile sim >= 0.7),
tweaked_copy (field sim >= 0.8 without tile-level duplication), else ok.

Usage:
    python similarity.py --lineage out/lineage.csv --out-dir out
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from itertools import combinations
from pathlib import Path

EXACT_THRESHOLD = 1.0
MERGE_THRESHOLD = 0.7
FIELD_STRONG = 0.8    # field overlap that flags a tweaked copy
FIELD_FLOOR = 0.6     # minimum field overlap worth recording

COLUMNS = [
    "snapshot_date", "doc_id_a", "doc_name_a", "doc_id_b", "doc_name_b",
    "shared_tiles", "tiles_a", "tiles_b", "similarity", "field_similarity",
    "verdict",
]


def load_sets(lineage_csv: str) -> tuple[dict, dict, dict]:
    hashes: dict[str, set] = {}
    fields: dict[str, set] = {}
    names: dict[str, str] = {}
    with open(lineage_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            d = row["doc_id"]
            hashes.setdefault(d, set()).add(row["tile_hash"])
            if row.get("field_name"):
                fields.setdefault(d, set()).add(
                    f"{row.get('view_name')}.{row['field_name']}")
            names[d] = row["document"]
    return hashes, fields, names


def jaccard(a: set, b: set) -> float:
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def score(hashes: dict, fields: dict, names: dict) -> list[dict]:
    today = date.today().isoformat()
    pairs = []
    for (a, ha), (b, hb) in combinations(sorted(hashes.items()), 2):
        shared = len(ha & hb)
        fsim = jaccard(fields.get(a, set()), fields.get(b, set()))
        if shared == 0 and fsim < FIELD_FLOOR:
            continue
        sim = shared / len(ha | hb)
        if sim >= EXACT_THRESHOLD:
            verdict = "exact_duplicate"
        elif sim >= MERGE_THRESHOLD:
            verdict = "merge_candidate"
        elif fsim >= FIELD_STRONG:
            verdict = "tweaked_copy"
        else:
            verdict = "ok"
        pairs.append({
            "snapshot_date": today,
            "doc_id_a": a, "doc_name_a": names[a],
            "doc_id_b": b, "doc_name_b": names[b],
            "shared_tiles": shared,
            "tiles_a": len(ha), "tiles_b": len(hb),
            "similarity": round(sim, 2),
            "field_similarity": round(fsim, 2),
            "verdict": verdict,
        })
    pairs.sort(key=lambda p: (-p["similarity"], -p["field_similarity"]))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", default="out/lineage.csv")
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()

    hashes, fields, names = load_sets(args.lineage)
    pairs = score(hashes, fields, names)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "dashboard_similarity.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(pairs)

    flagged = [p for p in pairs if p["verdict"] != "ok"]
    print(f"{len(pairs)} recorded pairs; {len(flagged)} flagged:")
    for p in flagged[:20]:
        print(f"  tile={p['similarity']:.2f} field={p['field_similarity']:.2f}"
              f"  {p['doc_name_a']}  <->  {p['doc_name_b']}  ({p['verdict']})")


if __name__ == "__main__":
    main()
