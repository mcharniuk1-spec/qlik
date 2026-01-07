import os
import json
from pathlib import Path
import pandas as pd

"""
Reads data/tenders_raw.jsonl (full tender JSON per line),
filters only tenders/items related to milk,
exports:
- out/milk_items.csv
- out/milk_tenders.csv
- out/milk_export.xlsx (2 sheets)
"""

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
OUT_DIR = Path(os.getenv("OUT_DIR", "out"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

IN_JSONL = DATA_DIR / "tenders_raw.jsonl"

# Milk CPV examples (you can extend)
MILK_CPV = {
    x.strip()
    for x in os.getenv("MILK_CPV", "15510000-6,15511000-3").split(",")
    if x.strip()
}
KEYWORDS = [
    x.strip().lower()
    for x in os.getenv("MILK_KEYWORDS", "молоко,milk").split(",")
    if x.strip()
]

def is_milk_item(item: dict) -> bool:
    cls = item.get("classification") or {}
    cpv = (cls.get("id") or "").strip()
    if cpv in MILK_CPV:
        return True

    desc = (item.get("description") or "").lower()
    if any(k in desc for k in KEYWORDS):
        return True

    return False

def main() -> None:
    if not IN_JSONL.exists():
        raise FileNotFoundError(f"Missing input file: {IN_JSONL}")

    tenders_rows: list[dict] = []
    items_rows: list[dict] = []

    with IN_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            t = json.loads(line)

            tender_id = t.get("id")
            tender_title = t.get("title")
            tender_status = t.get("status")
            tender_date = t.get("dateModified") or t.get("dateCreated")

            procuring = t.get("procuringEntity") or {}
            buyer_name = procuring.get("name")

            method = t.get("procurementMethod")
            method_type = t.get("procurementMethodType")

            value = t.get("value") or {}
            value_amount = value.get("amount")
            value_currency = value.get("currency")

            items = t.get("items") or []
            milk_items = [it for it in items if is_milk_item(it)]

            if not milk_items:
                continue

            # tender-level record
            tenders_rows.append({
                "tender_id": tender_id,
                "tender_title": tender_title,
                "tender_status": tender_status,
                "tender_dateModified": tender_date,
                "buyer_name": buyer_name,
                "procurement_method": method,
                "procurement_method_type": method_type,
                "value_amount": value_amount,
                "value_currency": value_currency,
            })

            # items-level records
            for it in milk_items:
                cls = it.get("classification") or {}
                delivery = it.get("deliveryDate") or {}
                unit = it.get("unit") or {}

                items_rows.append({
                    "tender_id": tender_id,
                    "tender_title": tender_title,
                    "tender_status": tender_status,
                    "tender_dateModified": tender_date,
                    "buyer_name": buyer_name,
                    "item_id": it.get("id"),
                    "item_description": it.get("description"),
                    "cpv": cls.get("id"),
                    "cpv_desc": cls.get("description"),
                    "quantity": it.get("quantity"),
                    "unit": unit.get("name"),
                    "delivery_start": delivery.get("startDate"),
                    "delivery_end": delivery.get("endDate"),
                })

    df_items = pd.DataFrame(items_rows)
    df_tenders = pd.DataFrame(tenders_rows)

    # Output
    df_items.to_csv(OUT_DIR / "milk_items.csv", index=False)
    df_tenders.to_csv(OUT_DIR / "milk_tenders.csv", index=False)

    with pd.ExcelWriter(OUT_DIR / "milk_export.xlsx", engine="openpyxl") as writer:
        df_tenders.to_excel(writer, sheet_name="milk_tenders", index=False)
        df_items.to_excel(writer, sheet_name="milk_items", index=False)

    print("Saved:")
    print(" - out/milk_items.csv")
    print(" - out/milk_tenders.csv")
    print(" - out/milk_export.xlsx")

if __name__ == "__main__":
    main()
