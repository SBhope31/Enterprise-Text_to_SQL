"""Run Spider evaluation against the embedded Spider schemas.

Usage:
    python -m scripts.run_spider_eval                       # full dev set
    python -m scripts.run_spider_eval --limit 50            # quick smoke
    python -m scripts.run_spider_eval --k 5 --out spider_report.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.eval.spider.loader import SpiderDataset
from app.eval.spider.runner import evaluate_spider


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="spider_data")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None, help="evaluate only N items")
    ap.add_argument(
        "--offset", type=int, default=0,
        help="skip the first N items (useful for resuming under daily LLM quotas)",
    )
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ds = SpiderDataset(root=args.root)
    summary = evaluate_spider(
        limit=args.limit, k=args.k, dataset=ds, offset=args.offset,
    )

    print("\n=== Spider aggregate metrics ===")
    for k_, v in summary.as_dict().items():
        if isinstance(v, float):
            print(f"  {k_:28s} {v:.3f}")
        elif isinstance(v, dict):
            print(f"  {k_}: ({len(v)} databases)")
        else:
            print(f"  {k_:28s} {v}")

    if args.out:
        payload = {
            "summary": summary.as_dict(),
            "items": [asdict(i) for i in summary.items],
        }
        Path(args.out).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
