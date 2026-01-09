# src/normalize_milk.py
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class LogRow:
    ts: str
    stage: str
    level: str
    message: str
    details: str = ""


class RunLogger:
    """
    Простий логер:
    - друкує в stdout (видно в GitHub Actions logs)
    - пише jsonl у файл (потім вшиваємо в XLSX -> sheet 'logs')
    """
    def __init__(self, jsonl_path: Path):
        self.jsonl_path = jsonl_path
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.rows: List[LogRow] = []

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def log(self, stage: str, message: str, level: str = "INFO", **kwargs: Any) -> None:
        details = ""
        if kwargs:
            try:
                details = json.dumps(kwargs, ensure_ascii=False)
            except Exception:
                details = str(kwargs)

        row = LogRow(ts=self._now(), stage=stage, level=level, message=message, details=details)
        self.rows.append(row)

        # stdout for Actions
        print(f"[{row.ts}] {row.level:<5} {row.stage}: {row.message} {row.details}".rstrip())

        # jsonl for persistence
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row.__dict__, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["ts", "stage", "level", "message", "details"])
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                # fallback: raw line as message
                rows.append({"ts": "", "stage": "unknown", "level": "INFO", "message": line, "details": ""})
    return pd.DataFrame(rows)


def safe_sheet_name(name: str, used: set) -> str:
    # Excel sheet name: max 31 chars, cannot contain: : \ / ? * [ ]
    bad = [":", "\\", "/", "?", "*", "[", "]"]
    for ch in bad:
        name = name.replace(ch, "_")
    name = name.strip() or "sheet"
    name = name[:31]

    base = name
    i = 2
    while name in used:
        suffix = f"_{i}"
        name = (base[: 31 - len(suffix)] + suffix)[:31]
        i += 1
    used.add(name)
    return name


def list_tables(conn: sqlite3.Connection) -> List[str]:
    q = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    return [r[0] for r in conn.execute(q).fetchall()]


def table_to_df(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    # robust for arbitrary schemas
    return pd.read_sql_query(f'SELECT * FROM "{table}"', conn)


def write_meta_sheet(writer: pd.ExcelWriter, meta: Dict[str, Any]) -> None:
    df = pd.DataFrame([{"key": k, "value": v} for k, v in meta.items()])
    df.to_excel(writer, sheet_name="meta", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize/export Prozorro milk dataset to XLSX (with logs sheet).")
    parser.add_argument("--data-dir", default=os.getenv("DATA_DIR", "data"))
    parser.add_argument("--db-path", default=os.getenv("DB_PATH", ""), help="Path to sqlite DB (default: data/prozorro_milk.sqlite)")
    parser.add_argument("--state-path", default=os.getenv("STATE_PATH", ""), help="Path to state.json (default: data/state.json)")
    parser.add_argument("--xlsx-path", default=os.getenv("XLSX_PATH", ""), help="Output XLSX path (default: data/prozorro-milk.xlsx)")
    parser.add_argument("--run-log-jsonl", default=os.getenv("RUN_LOG_JSONL", ""), help="JSONL logs path (default: data/run_logs.jsonl)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path) if args.db_path else data_dir / "prozorro_milk.sqlite"
    state_path = Path(args.state_path) if args.state_path else data_dir / "state.json"
    xlsx_path = Path(args.xlsx_path) if args.xlsx_path else data_dir / "prozorro-milk.xlsx"
    run_log_jsonl = Path(args.run_log_jsonl) if args.run_log_jsonl else data_dir / "run_logs.jsonl"

    logger = RunLogger(run_log_jsonl)
    logger.log("normalize", "Start XLSX export", db=str(db_path), xlsx=str(xlsx_path))

    if not db_path.exists():
        logger.log("normalize", "DB not found, nothing to export", level="ERROR", db=str(db_path))
        raise SystemExit(2)

    # Load logs collected so far (includes this step too)
    # We'll re-read at the end (so this step messages also included)
    conn = sqlite3.connect(str(db_path))
    try:
        tables = list_tables(conn)
        logger.log("normalize", "Discovered tables", tables=tables)

        used_sheets: set = set()
        xlsx_path.parent.mkdir(parents=True, exist_ok=True)

        meta: Dict[str, Any] = {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "db_path": str(db_path),
            "state_path": str(state_path),
            "tables": ", ".join(tables),
        }

        # include state.json content (if exists) into meta
        if state_path.exists():
            try:
                meta["state_json"] = state_path.read_text(encoding="utf-8")
            except Exception as e:
                meta["state_json"] = f"<failed to read state.json: {e}>"
        else:
            meta["state_json"] = "<missing>"

        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            # meta first
            write_meta_sheet(writer, meta)
            used_sheets.add("meta")

            # export each sqlite table to its own sheet
            for t in tables:
                logger.log("normalize", "Export table", table=t)
                df = table_to_df(conn, t)

                # Optional: stabilize order if common columns exist
                for col in ["dateModified", "tender_id", "tenderID", "id"]:
                    if col in df.columns:
                        try:
                            df = df.sort_values(col, ascending=True, kind="mergesort")
                        except Exception:
                            pass
                        break

                sheet = safe_sheet_name(t, used_sheets)
                df.to_excel(writer, sheet_name=sheet, index=False)

            # logs sheet (jsonl)
            logger.log("normalize", "Attach logs sheet")
            logs_df = read_jsonl(run_log_jsonl)
            sheet_logs = safe_sheet_name("logs", used_sheets)
            logs_df.to_excel(writer, sheet_name=sheet_logs, index=False)

        logger.log("normalize", "XLSX export done", bytes=xlsx_path.stat().st_size)

    finally:
        conn.close()

    # Re-ensure logs file contains final messages too
    # (No extra action needed: logger already writes jsonl)


if __name__ == "__main__":
    main()
