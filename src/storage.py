import os
import sqlite3
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS milk_tenders (
  tender_id TEXT PRIMARY KEY,
  tenderID TEXT,
  dateModified TEXT,
  status TEXT,
  procurementMethodType TEXT,
  procuringEntity_name TEXT,
  procuringEntity_id TEXT,
  value_amount REAL,
  value_currency TEXT,
  value_vatIncluded INTEGER,
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS milk_items (
  tender_id TEXT NOT NULL,
  item_key TEXT NOT NULL,
  description TEXT,
  classification_id TEXT,
  classification_scheme TEXT,
  quantity REAL,
  unit_name TEXT,
  unit_code TEXT,
  delivery_start TEXT,
  delivery_end TEXT,
  region TEXT,
  locality TEXT,
  dateModified TEXT,
  PRIMARY KEY (tender_id, item_key)
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    return conn

def upsert_tender(conn: sqlite3.Connection, t: dict[str, Any], fetched_at: str) -> None:
    pe = t.get("procuringEntity") or {}
    pe_id = (pe.get("identifier") or {}).get("id")
    val = t.get("value") or {}
    conn.execute(
        """
        INSERT INTO milk_tenders (
          tender_id, tenderID, dateModified, status, procurementMethodType,
          procuringEntity_name, procuringEntity_id,
          value_amount, value_currency, value_vatIncluded, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tender_id) DO UPDATE SET
          tenderID=excluded.tenderID,
          dateModified=excluded.dateModified,
          status=excluded.status,
          procurementMethodType=excluded.procurementMethodType,
          procuringEntity_name=excluded.procuringEntity_name,
          procuringEntity_id=excluded.procuringEntity_id,
          value_amount=excluded.value_amount,
          value_currency=excluded.value_currency,
          value_vatIncluded=excluded.value_vatIncluded,
          fetched_at=excluded.fetched_at
        """,
        (
            t.get("id"),
            t.get("tenderID"),
            t.get("dateModified"),
            t.get("status"),
            t.get("procurementMethodType"),
            pe.get("name"),
            pe_id,
            val.get("amount"),
            val.get("currency"),
            1 if val.get("valueAddedTaxIncluded") else 0 if val else None,
            fetched_at,
        ),
    )

def upsert_item(conn: sqlite3.Connection, tender_id: str, item_key: str, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO milk_items (
          tender_id, item_key, description,
          classification_id, classification_scheme,
          quantity, unit_name, unit_code,
          delivery_start, delivery_end,
          region, locality, dateModified
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tender_id, item_key) DO UPDATE SET
          description=excluded.description,
          classification_id=excluded.classification_id,
          classification_scheme=excluded.classification_scheme,
          quantity=excluded.quantity,
          unit_name=excluded.unit_name,
          unit_code=excluded.unit_code,
          delivery_start=excluded.delivery_start,
          delivery_end=excluded.delivery_end,
          region=excluded.region,
          locality=excluded.locality,
          dateModified=excluded.dateModified
        """,
        (
            tender_id, item_key,
            row.get("description"),
            row.get("classification_id"),
            row.get("classification_scheme"),
            row.get("quantity"),
            row.get("unit_name"),
            row.get("unit_code"),
            row.get("delivery_start"),
            row.get("delivery_end"),
            row.get("region"),
            row.get("locality"),
            row.get("dateModified"),
        ),
    )
