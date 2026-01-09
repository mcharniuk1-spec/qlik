import os
import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from .config import Config
from .logging_utils import setup_stage_logger


def _safe_sort(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    cols_present = [c for c in cols if c in df.columns]
    if not cols_present:
        return df
    return df.sort_values(cols_present, ascending=[True] * len(cols_present))


def _read_text_lines(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in f]
    except FileNotFoundError:
        return []


def _build_logs_df(cfg: Config) -> pd.DataFrame:
    """
    Collect stage logs and put them into a single dataframe.
    We take the *_latest.log files (these represent the current run).
    """
    fetch_latest = os.path.join(cfg.log_dir, "fetch_latest.log")
    normalize_latest = os.path.join(cfg.log_dir, "normalize_latest.log")

    rows = []

    for stage, path in [("fetch", fetch_latest), ("normalize", normalize_latest)]:
        lines = _read_text_lines(path)
        for i, line in enumerate(lines, start=1):
            rows.append({"stage": stage, "line_no": i, "text": line})

    return pd.DataFrame(rows, columns=["stage", "line_no", "text"])


def _build_progress_df(cfg: Config) -> pd.DataFrame:
    """
    Merge state + fetch_report/normalize_report + github run metadata into a compact sheet.
    """
    # State
    state = {}
    if os.path.exists(cfg.state_path):
        try:
            with open(cfg.state_path, "r", encoding="utf-8") as f:
                state = json.load(f) or {}
        except Exception:
            state = {}

    # Reports
    fetch_report_path = os.path.join(cfg.out_dir, "reports", "fetch_report.json")
    normalize_report_path = os.path.join(cfg.out_dir, "reports", "normalize_report.json")

    fetch_report = {}
    normalize_report = {}

    for p, target in [(fetch_report_path, "fetch"), (normalize_report_path, "normalize")]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    if target == "fetch":
                        fetch_report = json.load(f) or {}
                    else:
                        normalize_report = json.load(f) or {}
            except Exception:
                pass

    # GitHub run metadata (available in Actions)
    meta = {
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "github_run_number": os.getenv("GITHUB_RUN_NUMBER"),
        "github_workflow": os.getenv("GITHUB_WORKFLOW"),
        "github_job": os.getenv("GITHUB_JOB"),
        "github_ref": os.getenv("GITHUB_REF"),
        "github_ref_name": os.getenv("GITHUB_REF_NAME"),
        "github_sha": os.getenv("GITHUB_SHA"),
        "github_repository": os.getenv("GITHUB_REPOSITORY"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }

    # Flatten into key/value rows for readability in Excel
    rows = []

    def add_block(title: str, obj: dict):
        rows.append({"section": title, "key": "", "value": ""})
        for k in sorted(obj.keys()):
            v = obj.get(k)
            rows.append({"section": title, "key": str(k), "value": "" if v is None else str(v)})

    add_block("meta", meta)
    add_block("config", {
        "op_api_base": cfg.op_api_base,
        "page_size(limit)": cfg.page_size,
        "max_pages": cfg.max_pages,
        "max_runtime_seconds": cfg.max_runtime_seconds,
        "concurrency": cfg.concurrency,
        "milk_cpv_prefixes": ",".join(cfg.milk_cpv_prefixes),
        "milk_keywords": ",".join(cfg.milk_keywords),
        "start_offset": cfg.start_offset,
        "db_path": cfg.db_path,
        "state_path": cfg.state_path,
        "log_dir": cfg.log_dir,
    })
    add_block("state", state if isinstance(state, dict) else {})
    add_block("fetch_report", fetch_report if isinstance(fetch_report, dict) else {})
    add_block("normalize_report", normalize_report if isinstance(normalize_report, dict) else {})

    return pd.DataFrame(rows, columns=["section", "key", "value"])


def main() -> None:
    cfg = Config.load()
    logger = setup_stage_logger("normalize", cfg.log_dir, cfg.keep_log_files)

    os.makedirs(cfg.out_dir, exist_ok=True)
    report_dir = os.path.join(cfg.out_dir, "reports")
    os.makedirs(report_dir, exist_ok=True)

    if not os.path.exists(cfg.db_path):
        logger.warning(f"No DB found at {cfg.db_path}. Nothing to export.")
        with open(os.path.join(report_dir, "normalize_report.json"), "w", encoding="utf-8") as f:
            json.dump({"status": "no_db", "db_path": cfg.db_path}, f, ensure_ascii=False, indent=2)
        return

    conn = sqlite3.connect(cfg.db_path)

    tenders = pd.read_sql_query("SELECT * FROM milk_tenders", conn)
    items = pd.read_sql_query("SELECT * FROM milk_items", conn)

    logger.info(f"Loaded: tenders={len(tenders)}, items={len(items)}")

    # Stable sort (fixes your previous pandas ascending mismatch and avoids crashes)
    tenders = _safe_sort(tenders, ["dateModified", "tender_id"])
    items = _safe_sort(items, ["dateModified", "tender_id", "item_key"])

    # Build progress + logs sheets
    progress_df = _build_progress_df(cfg)
    logs_df = _build_logs_df(cfg)

    xlsx_path = os.path.join(cfg.out_dir, "milk_export.xlsx")

    # Write XLSX with multiple sheets:
    # - tenders
    # - items
    # - progress (state + reports + run meta)
    # - logs (fetch_latest + normalize_latest)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        tenders.to_excel(writer, sheet_name="tenders", index=False)
        items.to_excel(writer, sheet_name="items", index=False)
        progress_df.to_excel(writer, sheet_name="progress", index=False)
        logs_df.to_excel(writer, sheet_name="logs", index=False)

    # also keep CSV outputs (optional but useful)
    items_csv = os.path.join(cfg.out_dir, "milk_items.csv")
    tenders_csv = os.path.join(cfg.out_dir, "milk_tenders.csv")
    items.to_csv(items_csv, index=False, encoding="utf-8")
    tenders.to_csv(tenders_csv, index=False, encoding="utf-8")

    report = {
        "status": "ok",
        "rows": {"tenders": int(len(tenders)), "items": int(len(items)), "log_lines": int(len(logs_df))},
        "outputs": {
            "xlsx": xlsx_path,
            "milk_items_csv": items_csv,
            "milk_tenders_csv": tenders_csv,
        }
    }
    with open(os.path.join(report_dir, "normalize_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"Exported XLSX with logs: {xlsx_path}")


if __name__ == "__main__":
    main()
