import os
import sqlite3
import pandas as pd

from .config import Config
from .logging_utils import setup_logger

def main() -> None:
    cfg = Config.load()
    logger = setup_logger("normalize", cfg.out_dir)

    os.makedirs(cfg.out_dir, exist_ok=True)

    if not os.path.exists(cfg.db_path):
        logger.warning("No DB found. Nothing to export.")
        return

    conn = sqlite3.connect(cfg.db_path)

    tenders = pd.read_sql_query("SELECT * FROM milk_tenders", conn)
    items = pd.read_sql_query("SELECT * FROM milk_items", conn)

    if "dateModified" in tenders.columns:
        tenders = tenders.sort_values(["dateModified", "tender_id"], ascending=[True, True])
    if "dateModified" in items.columns:
        items = items.sort_values(["dateModified", "tender_id", "item_key"], ascending=[True, True])

    items_csv = os.path.join(cfg.out_dir, "milk_items.csv")
    tenders_csv = os.path.join(cfg.out_dir, "milk_tenders.csv")
    xlsx_path = os.path.join(cfg.out_dir, "milk_export.xlsx")

    items.to_csv(items_csv, index=False, encoding="utf-8")
    tenders.to_csv(tenders_csv, index=False, encoding="utf-8")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        tenders.to_excel(writer, sheet_name="tenders", index=False)
        items.to_excel(writer, sheet_name="items", index=False)

    logger.info(f"Exported: {items_csv}, {tenders_csv}, {xlsx_path}")

if __name__ == "__main__":
    main()
