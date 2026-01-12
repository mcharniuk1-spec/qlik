# src/build_bi_milk_xlsx.py
import json
import os
import re
from datetime import datetime, timezone

import pandas as pd

OUT_DIR = os.getenv("OUT_DIR", "out/bi")
CONFIG_PATH = os.getenv("CONFIG", "config/bi_milk.json")
DEST_PATH = os.getenv("DEST_XLSX", "data/prozorro_bi_milk_2024_2026.xlsx")

def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()

def read_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"ts": utcnow_iso(), "level": "WARN", "stage": "parse", "message": "Bad JSONL line", "raw": line})
    return rows

def detect_cpv_column(df: pd.DataFrame) -> str:
    # Try common names
    candidates = list(df.columns)
    for c in candidates:
        cl = str(c).lower()
        if "cpv" in cl or "дк" in cl or "dk" in cl:
            return c
    # fallback: find a column where values look like 15500000-3
    pat = re.compile(r"\b\d{8}-\d\b")
    for c in candidates:
        sample = df[c].astype(str).head(200).tolist()
        if sum(1 for v in sample if pat.search(v)) >= 5:
            return c
    return ""

def filter_by_cpv(df: pd.DataFrame, cpv_codes: list[str]) -> tuple[pd.DataFrame, str]:
    cpv_col = detect_cpv_column(df)
    if not cpv_col:
        return df, ""
    pat = re.compile(r"\b(\d{8}-\d)\b")
    wanted = set(cpv_codes)

    def extract_code(x: str) -> str:
        m = pat.search(str(x))
        return m.group(1) if m else ""

    codes = df[cpv_col].apply(extract_code)
    mask = codes.isin(wanted)
    out = df.loc[mask].copy()
    out["_cpv_extracted"] = codes[mask].values
    return out, str(cpv_col)

def detect_date_column(df: pd.DataFrame) -> str:
    for c in df.columns:
        cl = str(c).lower()
        if "date" in cl or "дата" in cl:
            return c
    return ""

def main():
    cfg = read_config()
    years = list(range(int(cfg["year_from"]), int(cfg["year_to"]) + 1))
    export_format = cfg.get("export_format", "OOXML")
    ext = "xlsx" if export_format == "OOXML" else "csv"

    # logs
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    log_path = os.path.join(OUT_DIR, f"run_{run_id}.jsonl")
    logs = read_jsonl(log_path)
    logs_df = pd.DataFrame(logs) if logs else pd.DataFrame(columns=["ts", "level", "stage", "message"])

    # read exports
    frames = []
    per_year_counts = []
    for y in years:
        fp = os.path.join(OUT_DIR, f"bi_milk_{y}.{ext}")
        if not os.path.exists(fp):
            per_year_counts.append({"year": y, "file": fp, "rows": 0, "status": "missing"})
            continue

        if ext == "xlsx":
            df = pd.read_excel(fp)
        else:
            df = pd.read_csv(fp)

        df["_export_year"] = y
        df["_exported_at"] = utcnow_iso()
        per_year_counts.append({"year": y, "file": fp, "rows": int(len(df)), "status": "ok"})
        frames.append(df)

    all_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # CPV strict filter (always enforce here)
    cpv_codes = cfg.get("cpv_codes", [])
    filtered_df, cpv_col_used = filter_by_cpv(all_df, cpv_codes) if len(all_df) else (all_df, "")

    # meta
    meta_rows = []
    meta_rows.append(["run_at_utc", utcnow_iso()])
    meta_rows.append(["bi_url", cfg.get("bi_url", "")])
    meta_rows.append(["app_id", cfg.get("app_id", "")])
    meta_rows.append(["sheet_id", cfg.get("sheet_id", "")])
    meta_rows.append(["viz_id", cfg.get("viz_id", "")])
    meta_rows.append(["year_from", cfg.get("year_from")])
    meta_rows.append(["year_to", cfg.get("year_to")])
    meta_rows.append(["export_format", export_format])
    meta_rows.append(["cpv_filter_column_detected", cpv_col_used])
    meta_rows.append(["cpv_codes", ", ".join(cpv_codes)])
    meta_rows.append(["rows_before_cpv_filter", int(len(all_df))])
    meta_rows.append(["rows_after_cpv_filter", int(len(filtered_df))])

    date_col = detect_date_column(filtered_df)
    if date_col and len(filtered_df):
        try:
            d = pd.to_datetime(filtered_df[date_col], errors="coerce", utc=True)
            meta_rows.append(["min_date_utc", str(d.min())])
            meta_rows.append(["max_date_utc", str(d.max())])
        except Exception:
            pass

    meta_df = pd.DataFrame(meta_rows, columns=["key", "value"])
    per_year_df = pd.DataFrame(per_year_counts)

    os.makedirs(os.path.dirname(DEST_PATH), exist_ok=True)

    # Excel row limit safety: if huge, split by year sheets as well
    with pd.ExcelWriter(DEST_PATH, engine="openpyxl") as writer:
        # main data
        if len(filtered_df) > 1_000_000:
            # write per-year to avoid breaking Excel limits
            for y in years:
                chunk = filtered_df[filtered_df["_export_year"] == y]
                chunk.to_excel(writer, sheet_name=f"data_{y}", index=False)
            meta_df.to_excel(writer, sheet_name="meta", index=False)
            per_year_df.to_excel(writer, sheet_name="per_year", index=False)
        else:
            filtered_df.to_excel(writer, sheet_name="data", index=False)
            meta_df.to_excel(writer, sheet_name="meta", index=False)
            per_year_df.to_excel(writer, sheet_name="per_year", index=False)

        # logs
        logs_df.to_excel(writer, sheet_name="logs", index=False)

    print(f"[OK] Wrote {DEST_PATH}")
    print(f"[INFO] rows_before={len(all_df)} rows_after={len(filtered_df)}")

if __name__ == "__main__":
    main()
