"""Spider dataset loader.

Expects the official Spider archive extracted to ./spider_data with structure:

    spider_data/
        dev.json
        train_spider.json   (optional)
        database/
            <db_id>/<db_id>.sqlite
            ...

Download from https://yale-lily.github.io/spider (the "spider.zip" link), or
mirror at https://drive.google.com/uc?id=1iRDVHLr4mX2wQKSgA9J8Pire73Jahh0m.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


DEFAULT_SPIDER_ROOT = Path("spider_data")


@dataclass(frozen=True)
class SpiderItem:
    question: str
    db_id: str
    gold_sql: str


@dataclass(frozen=True)
class SpiderTable:
    table: str
    columns: list[str]


@dataclass(frozen=True)
class SpiderSchema:
    db_id: str
    sqlite_path: Path
    tables: list[SpiderTable]

    def as_allowed_schema(self) -> dict[str, list[str]]:
        return {t.table: list(t.columns) for t in self.tables}


class SpiderDataset:
    def __init__(self, root: Path | str = DEFAULT_SPIDER_ROOT) -> None:
        self.root = Path(root)
        self.dev_path = self.root / "dev.json"
        self.databases_dir = self.root / "database"
        if not self.dev_path.exists():
            raise FileNotFoundError(
                f"Spider dev set not found at {self.dev_path}. "
                "Run `python -m scripts.download_spider` for instructions."
            )
        if not self.databases_dir.exists():
            raise FileNotFoundError(
                f"Spider databases directory not found at {self.databases_dir}. "
                "The official zip includes a `database/` folder."
            )

    def load_dev(self, limit: int | None = None) -> list[SpiderItem]:
        raw = json.loads(self.dev_path.read_text(encoding="utf-8"))
        items: list[SpiderItem] = []
        for row in raw:
            items.append(
                SpiderItem(
                    question=row["question"],
                    db_id=row["db_id"],
                    gold_sql=row["query"],
                )
            )
            if limit and len(items) >= limit:
                break
        return items

    def sqlite_path(self, db_id: str) -> Path:
        return self.databases_dir / db_id / f"{db_id}.sqlite"

    def engine(self, db_id: str) -> Engine:
        path = self.sqlite_path(db_id)
        if not path.exists():
            raise FileNotFoundError(f"SQLite file missing: {path}")
        # 5-second busy timeout; read-only via URI form.
        url = f"sqlite:///{path.as_posix()}"
        return create_engine(url, connect_args={"timeout": 5.0})

    def introspect(self, db_id: str) -> SpiderSchema:
        path = self.sqlite_path(db_id)
        if not path.exists():
            raise FileNotFoundError(f"SQLite file missing: {path}")
        conn = sqlite3.connect(str(path))
        try:
            tables: list[SpiderTable] = []
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            for (table_name,) in cur.fetchall():
                col_cur = conn.cursor()
                col_cur.execute(f'PRAGMA table_info("{table_name}")')
                cols = [r[1] for r in col_cur.fetchall()]
                tables.append(SpiderTable(table=table_name, columns=cols))
        finally:
            conn.close()
        return SpiderSchema(db_id=db_id, sqlite_path=path, tables=tables)

    def all_db_ids(self) -> list[str]:
        return sorted(p.name for p in self.databases_dir.iterdir() if p.is_dir())
