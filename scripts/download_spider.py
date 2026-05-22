"""Helper to verify Spider dataset is present and print download instructions.

Spider does not have a clean automated download path (the official archive is
on Google Drive, and reliable HuggingFace mirrors come and go). This script
just *checks* whether spider_data/ is populated and tells the user what to do
if not.

Usage:
    python -m scripts.download_spider
    python -m scripts.download_spider --check
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_ROOT = Path("spider_data")

INSTRUCTIONS = """\
Spider dataset is not present in {root}.

To install:
  1. Download the official Spider archive (~95 MB):
       https://yale-lily.github.io/spider
     (Click the "Spider Dataset" download link. Mirror:
      https://drive.google.com/uc?id=1iRDVHLr4mX2wQKSgA9J8Pire73Jahh0m)
  2. Extract it so the layout matches:
       {root}/dev.json
       {root}/train_spider.json   (optional)
       {root}/database/<db_id>/<db_id>.sqlite
  3. Re-run this script to verify.

Alternative: many HuggingFace mirrors exist (e.g. `xlangai/spider`) for the
questions only -- you still need the SQLite databases from the official zip.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="Spider data root")
    ap.parse_args()  # accept --check etc. as no-ops for friendliness
    root = Path(ap.parse_args().root)

    dev = root / "dev.json"
    db_dir = root / "database"

    if not dev.exists() or not db_dir.exists():
        print(INSTRUCTIONS.format(root=root))
        return

    items = json.loads(dev.read_text(encoding="utf-8"))
    db_ids = sorted(p.name for p in db_dir.iterdir() if p.is_dir())
    sqlite_count = sum(1 for d in db_ids if (db_dir / d / f"{d}.sqlite").exists())

    print(f"Spider dataset found at {root}.")
    print(f"  dev.json items     : {len(items)}")
    print(f"  database folders   : {len(db_ids)}")
    print(f"  sqlite files       : {sqlite_count}")
    if sqlite_count < len(db_ids):
        print(
            "  WARNING: some database folders are missing their .sqlite file. "
            "Re-extract the official zip."
        )


if __name__ == "__main__":
    main()
