import json
import os
from datetime import datetime
import pandas as pd

DATA_DIR = "data"
RAW_XLSX = os.path.join(DATA_DIR, "bi_milk_raw.xlsx")
LOG_JSONL = os.path.join(DATA_DIR, "bi_milk_export.log")
META_JSON = os.path.join(DATA_DIR, "bi_milk_meta.json")
OUT_XLSX = os.path.join(DATA_DIR, "bi-milk-2024-2026.xlsx")

CPV_CODES_DEFAULT = [
    "15500000-3","15510000-6","15511000-3","15511100-4","15511210-8",
    "15512000-0","15530000-2","15540000-5","15550000-8"
]
YEARS_DEFAULT = {2024, 2025, 2026}

def read_logs():
    rows = []
    if not os.path.exists(LOG_JSONL):
        return pd.DataFrame(columns=["ts","stage","message","extra"])
    with open(LOG_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.append({
                "ts": obj.get("ts"),
                "stage": obj.get("stage"),
                "message": obj.get("message"),
                "extra": json.dumps(obj.get("extra"), ensure_ascii=False) if obj.get("extra") is not None else ""
            })
    return pd.DataFrame(rows)

def load_meta():
    if not os.path.exists(META_JSON):
        return {}
    with open(META_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_col(df, candidates):
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for lc, orig in cols.items():
            if cand in lc:
                return orig
    return None

def cpv_match(series: pd.Series, cpv_codes):
    # match by 8-digit prefix (ignoring check digit after '-')
    prefixes = {c.split("-")[0] for c in cpv_codes}
    s = series.astype(str).fillna("")
    return s.apply(lambda x: x.split("-")[0].strip() in prefixes)

def filter_year(df, date_col=None, year_col=None, years=YEARS_DEFAULT):
    out = df
    if year_col and year_col in out.columns:
        y = pd.to_numeric(out[year_col], errors="coerce")
        out = out[y.isin(list(years))]
        return out

    if date_col and date_col in out.columns:
        dt = pd.to_datetime(out[date_col], errors="coerce", utc=True)
        out = out[dt.dt.year.isin(list(years))]
        return out

    return out

def main():
    meta = load_meta()
    cpv_codes = meta.get("cpv_codes") or CPV_CODES_DEFAULT
    years = set(int(y) for y in (meta.get("years") or [2024, 2025, 2026]))

    if not os.path.exists(RAW_XLSX):
        raise SystemExit(f"Missing raw xlsx: {RAW_XLSX}")

    # Read the first sheet of the raw export (Qlik export typically produces a single sheet)
    raw = pd.read_excel(RAW_XLSX, sheet_name=0)
    raw = normalize_cols(raw)

    # Try to locate CPV/date columns heuristically (works even if field names differ)
    cpv_col = find_col(raw, ["cpv", "дк 021", "dk 021", "classification", "код"])
    date_col = find_col(raw, ["date", "дата", "modified", "created", "publication"])
    year_col = find_col(raw, ["year", "рік"])

    # Strict CPV filtering (required)
    if cpv_col:
        raw = raw[cpv_match(raw[cpv_col], cpv_codes)]
    # Year filtering (required)
    raw = filter_year(raw, date_col=date_col, year_col=year_col, years=years)

    # Build meta sheet
    meta_rows = [
        ("generated_at_utc", datetime.utcnow().isoformat()),
        ("bi_url", meta.get("bi_url", "")),
        ("viz_id", meta.get("viz_id", "")),
        ("years", ",".join(map(str, sorted(years)))),
        ("cpv_codes", ",".join(cpv_codes)),
        ("raw_rows_after_filters", int(len(raw))),
        ("cpv_col_detected", cpv_col or ""),
        ("date_col_detected", date_col or ""),
        ("year_col_detected", year_col or ""),
        ("hypercube_size", json.dumps(meta.get("hypercube_size", None))),
    ]
    meta_df = pd.DataFrame(meta_rows, columns=["key", "value"])

    logs_df = read_logs()

    # Save final XLSX
    os.makedirs(DATA_DIR, exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
        meta_df.to_excel(w, index=False, sheet_name="meta")
        raw.to_excel(w, index=False, sheet_name="milk_prices")
        logs_df.to_excel(w, index=False, sheet_name="logs")

    print(f"Saved: {OUT_XLSX} rows={len(raw)}")

if __name__ == "__main__":
    main()
