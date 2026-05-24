"""Aggregate multiple Spider eval JSON files into one summary.

Useful when you're spreading the eval across days because of the Gemini
free-tier daily quota cap. Run each day with --offset/--out for a fresh slice,
then run this to get unified metrics.

Usage:
    python -m scripts.merge_spider_runs spider_day1.json spider_day2.json ...
    python -m scripts.merge_spider_runs spider_*.json --out merged.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="spider eval JSON files to merge")
    ap.add_argument("--out", default=None, help="write merged JSON here")
    args = ap.parse_args()

    # Deduplicate by (db_id, question) so re-runs of the same item only count once.
    items_by_key: dict[tuple[str, str], dict] = {}
    for path in args.files:
        data = json.loads(Path(path).read_text())
        for it in data.get("items", []):
            key = (it["db_id"], it["question"])
            # Prefer non-errored items if we have duplicates.
            cur = items_by_key.get(key)
            if cur is None or (cur.get("error") and not it.get("error")):
                items_by_key[key] = it

    items = list(items_by_key.values())
    n = len(items)
    errored = sum(1 for i in items if i.get("error"))
    ran = [i for i in items if i.get("execution_match") is not None]
    ran_ok = [i for i in ran if i.get("execution_match")]
    val_ok = [i for i in items if i.get("validation_ok")]
    hall = [i for i in items if i.get("hallucinated")]

    print(f"\n=== Merged Spider results from {len(args.files)} file(s) ===\n")
    print(f"  unique items                : {n}")
    print(f"  errored (no SQL)            : {errored}")
    print(f"  ran end-to-end              : {len(ran)}")
    print(f"  validation_pass_rate (all)  : {len(val_ok)/n:.3f}  ({len(val_ok)}/{n})")
    if ran:
        print(f"  execution_accuracy (of ran) : {len(ran_ok)/len(ran):.3f}  ({len(ran_ok)}/{len(ran)})")
    print(f"  hallucination_rate          : {len(hall)/n:.3f}")

    by_db: dict[str, list[bool]] = {}
    for i in ran:
        by_db.setdefault(i["db_id"], []).append(bool(i["execution_match"]))
    print(f"\n  per-database accuracy ({len(by_db)} DBs):")
    for db, results in sorted(by_db.items()):
        acc = sum(results) / len(results)
        print(f"     {db:<30s} {acc:.2f}  ({sum(results)}/{len(results)})")

    if args.out:
        Path(args.out).write_text(json.dumps({"items": items}, indent=2, default=str))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
