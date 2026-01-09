import os
import json
import sqlite3
import pandas as pd

from .config import Config
from .logging_utils import setup_stage_logger

def _safe_sort(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    cols_present = [c for c in cols if c in df.columns]
    if not cols_present:
        return df
    return df.sort_values(cols_present, ascending=[True] * len(cols_present))

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

    tenders = _safe_sort(tenders, ["dateModified", "tender_id"])
    items = _safe_sort(items, ["dateModified", "tender_id", "item_key"])  # <-- головний фікс

    items_csv = os.path.join(cfg.out_dir, "milk_items.csv")
    tenders_csv = os.path.join(cfg.out_dir, "milk_tenders.csv")
    xlsx_path = os.path.join(cfg.out_dir, "milk_export.xlsx")

    items.to_csv(items_csv, index=False, encoding="utf-8")
    tenders.to_csv(tenders_csv, index=False, encoding="utf-8")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        tenders.to_excel(writer, sheet_name="tenders", index=False)
        items.to_excel(writer, sheet_name="items", index=False)

    logger.info(f"Exported CSV/XLSX into {cfg.out_dir}")

    report = {
        "status": "ok",
        "rows": {"tenders": int(len(tenders)), "items": int(len(items))},
        "outputs": {
            "milk_items_csv": items_csv,
            "milk_tenders_csv": tenders_csv,
            "xlsx": xlsx_path
        }
    }
    with open(os.path.join(report_dir, "normalize_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
