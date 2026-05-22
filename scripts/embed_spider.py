"""Embed all Spider database schemas into Qdrant.

Usage:
    python -m scripts.embed_spider
    python -m scripts.embed_spider --db-ids concert_singer pets_1
    python -m scripts.embed_spider --no-reset
"""
from __future__ import annotations

import argparse

from app.eval.spider.embedder import embed_spider_corpus
from app.eval.spider.loader import SpiderDataset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="spider_data", help="Spider data root")
    ap.add_argument(
        "--db-ids", nargs="*", default=None,
        help="Only embed these database IDs (default: all in spider_data/database/)",
    )
    ap.add_argument(
        "--no-reset", action="store_true",
        help="Don't drop the existing collection before embedding",
    )
    args = ap.parse_args()

    ds = SpiderDataset(root=args.root)
    total = embed_spider_corpus(
        dataset=ds, db_ids=args.db_ids, reset=not args.no_reset
    )
    print(f"Embedded {total} schema docs.")


if __name__ == "__main__":
    main()
