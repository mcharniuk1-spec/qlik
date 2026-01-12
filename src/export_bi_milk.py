import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from .runlog import RunLog, log_df_to_sheet


CPV_DEFAULT = [
    "15500000-3",
    "15510000-6",
    "15511000-3",
    "15511100-4",
    "15511210-8",
    "15512000-0",
    "15530000-2",
    "15540000-5",
    "15550000-8",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_list_csv(s: str) -> List[str]:
    s = (s or "").strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def cpv_prefixes(codes: List[str]) -> List[str]:
    """
    CPV hierarchy trick:
    - take digits part (before '-')
    - strip trailing zeros => hierarchy prefix
      15500000 -> '155'
      15510000 -> '1551'
      15511000 -> '15511'
    """
    prefixes = []
    for c in codes:
        m = re.match(r"^\s*([0-9]{8})\s*-\s*[0-9]\s*$", c)
        if not m:
            continue
        digits = m.group(1)
        pref = digits.rstrip("0")
        if len(pref) < 3:
            pref = digits[:3]
        prefixes.append(pref)
    # longest first => more specific wins
    prefixes = sorted(set(prefixes), key=len, reverse=True)
    return prefixes


def find_cpv_column(cols: List[str]) -> Optional[str]:
    cand = []
    for c in cols:
        cl = str(c).lower()
        if "cpv" in cl or "дк" in cl or "dk" in cl or "код" in cl:
            cand.append(c)
    return cand[0] if cand else None


def find_date_column(cols: List[str]) -> Optional[str]:
    # prioritize typical names
    priority = ["datemodified", "date_modified", "date", "дата", "tenderdate", "tender_date"]
    lower_map = {str(c).lower(): c for c in cols}
    for p in priority:
        for k, v in lower_map.items():
            if p == k or p in k:
                return v
    return None


def filter_df(df: pd.DataFrame, years: List[int], cpv_codes: List[str], log: RunLog) -> pd.DataFrame:
    cols = list(df.columns)
    cpv_col = find_cpv_column(cols)
    date_col = find_date_column(cols)

    log.event("filter.detect_columns", cpv_col=str(cpv_col), date_col=str(date_col), columns=len(cols))

    out = df

    # Year filter
    if years and date_col:
        dt_series = pd.to_datetime(out[date_col], errors="coerce", utc=True)
        out = out.assign(__year=dt_series.dt.year)
        out = out[out["__year"].isin(years)].drop(columns=["__year"])
        log.event("filter.year", kept_rows=int(out.shape[0]), years=",".join(map(str, years)))
    elif years:
        log.event("filter.year_skipped", reason="date column not found")

    # CPV filter
    if cpv_codes and cpv_col:
        prefs = cpv_prefixes(cpv_codes)
        s = out[cpv_col].astype(str).str.extract(r"([0-9]{8})", expand=False)
        # match by hierarchy prefixes
        mask = False
        for p in prefs:
            mask = mask | s.str.startswith(p, na=False)
        out = out[mask]
        log.event("filter.cpv", kept_rows=int(out.shape[0]), prefixes=",".join(prefs))
    elif cpv_codes:
        log.event("filter.cpv_skipped", reason="cpv column not found")

    return out


@dataclass
class ExportConfig:
    bi_url: str
    years: List[int]
    cpv_codes: List[str]
    viz_id: str
    discover_only: bool
    out_xlsx: str
    out_csv: str
    log_jsonl: str
    headless: bool
    export_format: str = "CSV_C"  # or OOXML


INPAGE_JS = r"""
async (cfg) => {
  const result = { ok: false, logs: [], meta: {}, candidates: [], chosen: {} };

  function log(stage, details = {}) {
    result.logs.push({ ts: new Date().toISOString(), stage, ...details });
  }

  function unique(arr) {
    return Array.from(new Set(arr.filter(Boolean)));
  }

  // Prefer requirejs
  const req = window.requirejs || window.require;
  if (!req) {
    result.error = "requirejs/require not found on page";
    return result;
  }

  // Ensure baseUrl points to /sense/resources
  try {
    req.config({
      baseUrl: `${location.protocol}//${location.host}/sense/resources`
    });
  } catch (e) {
    // ignore; sometimes already configured
  }

  const qlik = await new Promise((resolve, reject) => {
    req(["js/qlik"], (q) => resolve(q), (err) => reject(err));
  }).catch((e) => {
    result.error = "failed to load js/qlik: " + String(e);
    return null;
  });

  if (!qlik) return result;

  qlik.setOnError((e) => {
    // Keep Qlik engine errors in logs
    log("qlik.error", { message: e && e.message ? e.message : String(e) });
  });

  const app = qlik.currApp ? qlik.currApp() : null;
  if (!app) {
    result.error = "qlik.currApp() returned null; this page might not be a Qlik app context";
    return result;
  }

  // app reload time for freshness
  const layout = await new Promise((resolve) => app.getAppLayout(resolve));
  result.meta.qLastReloadTime = layout?.qLastReloadTime || null;
  result.meta.qTitle = layout?.qTitle || null;
  log("app.layout", { qLastReloadTime: result.meta.qLastReloadTime, qTitle: result.meta.qTitle });

  // Discover object ids from DOM (straight table objects are usually qv-object with data-qvid)
  const domIds = unique([
    ...Array.from(document.querySelectorAll("[data-qvid]")).map(el => el.getAttribute("data-qvid")),
    ...Array.from(document.querySelectorAll("[data-objectid]")).map(el => el.getAttribute("data-objectid")),
  ]);

  log("discover.dom_ids", { count: domIds.length });

  async function describeViz(id) {
    try {
      const vis = await app.visualization.get(id);
      const l = await vis.model.getLayout();
      const hc = l?.qHyperCube;
      const size = hc?.qSize || null;
      const title = l?.title || l?.qMeta?.title || l?.qInfo?.qId || null;
      const qType = l?.qInfo?.qType || null;
      const dims = hc?.qDimensionInfo?.map(d => ({
        title: d?.qFallbackTitle,
        fieldDefs: d?.qFieldDefs || d?.qGroupFieldDefs || []
      })) || [];
      const meas = hc?.qMeasureInfo?.map(m => ({ title: m?.qFallbackTitle })) || [];
      return { id, qType, title, size, dims, meas, hasHyperCube: !!hc };
    } catch (e) {
      return { id, error: String(e) };
    }
  }

  // If viz_id explicitly provided — use it; else score candidates
  let chosenId = cfg.viz_id && cfg.viz_id.trim() ? cfg.viz_id.trim() : null;

  if (!chosenId) {
    const descs = [];
    // limit scan to avoid timeouts
    const sample = domIds.slice(0, 80);
    for (const id of sample) {
      const d = await describeViz(id);
      descs.push(d);
    }
    result.candidates = descs;

    // score: prefer hypercube with largest row count
    let best = null;
    for (const d of descs) {
      const rows = d?.size?.qcy || 0;
      const cols = d?.size?.qcx || 0;
      const score = rows * 1000 + cols;
      if (d.hasHyperCube && (!best || score > best.score)) {
        best = { id: d.id, score, rows, cols, title: d.title, qType: d.qType, dims: d.dims };
      }
    }
    if (best) {
      chosenId = best.id;
      result.chosen = best;
      log("discover.chosen", best);
    } else {
      result.error = "Could not auto-detect a hypercube visualization on this sheet. Provide VIZ_ID.";
      return result;
    }
  } else {
    log("discover.chosen_explicit", { id: chosenId });
  }

  // Optionally stop after discovery
  if (cfg.discover_only) {
    result.ok = true;
    result.onlyDiscovery = true;
    return result;
  }

  // Clear selections to avoid “stuck on 2015–2016” states
  try {
    if (app.clearAll) {
      await app.clearAll();
      log("select.clearAll", { ok: true });
    }
  } catch (e) {
    log("select.clearAll", { ok: false, error: String(e) });
  }

  // Try to infer CPV/year fields from chosen viz layout (dims field defs)
  let cpvField = cfg.field_cpv && cfg.field_cpv.trim() ? cfg.field_cpv.trim() : null;
  let yearField = cfg.field_year && cfg.field_year.trim() ? cfg.field_year.trim() : null;

  try {
    const vis = await app.visualization.get(chosenId);
    const l = await vis.model.getLayout();
    const dims = l?.qHyperCube?.qDimensionInfo || [];

    if (!cpvField) {
      for (const d of dims) {
        const defs = (d.qFieldDefs || d.qGroupFieldDefs || []).map(String);
        const title = String(d.qFallbackTitle || "");
        const hay = (defs.join(" ") + " " + title).toLowerCase();
        if (hay.includes("cpv") || hay.includes("дк") || hay.includes("dk") || hay.includes("код")) {
          cpvField = defs[0] || null;
          break;
        }
      }
    }

    if (!yearField) {
      for (const d of dims) {
        const defs = (d.qFieldDefs || d.qGroupFieldDefs || []).map(String);
        const title = String(d.qFallbackTitle || "");
        const hay = (defs.join(" ") + " " + title).toLowerCase();
        if (hay.includes("year") || hay.includes("рік") || hay.includes("год") || hay.includes("y")) {
          // heuristic: if field def is numeric year dimension
          yearField = defs[0] || null;
          // don't break too early if it's clearly not a year field
          break;
        }
      }
    }

    log("select.detect_fields", { cpvField, yearField });
  } catch (e) {
    log("select.detect_fields", { error: String(e) });
  }

  async function selectValues(fieldName, values) {
    if (!fieldName || !values || !values.length) return { skipped: true };
    const field = app.field(fieldName);
    const qValues = values.map(v => ({ qText: String(v) }));
    await field.selectValues(qValues, false, true);
    return { ok: true, fieldName, count: values.length };
  }

  // Apply selections (best effort). If fails — Python side will post-filter by date/cpv column if present.
  try {
    if (yearField) {
      const r = await selectValues(yearField, cfg.years || []);
      log("select.years", r);
    } else {
      log("select.years_skipped", { reason: "yearField not detected" });
    }
  } catch (e) {
    log("select.years_error", { error: String(e) });
  }

  try {
    if (cpvField) {
      const r = await selectValues(cpvField, cfg.cpv_codes || []);
      log("select.cpv", r);
    } else {
      log("select.cpv_skipped", { reason: "cpvField not detected" });
    }
  } catch (e) {
    log("select.cpv_error", { error: String(e) });
  }

  // Export (entire hypercube) — returns a URL. (Capability API exportData)
  // Docs: exportData exports underlying hypercube and returns download link.
  try {
    const vis = await app.visualization.get(chosenId);
    const link = await vis.exportData({ format: cfg.export_format || "CSV_C" });
    result.exportLink = link;
    log("export.link", { link, format: cfg.export_format || "CSV_C" });
    result.ok = true;
    return result;
  } catch (e) {
    result.error = "exportData failed: " + String(e);
    log("export.error", { error: String(e) });
    return result;
  }
}
"""


async def download_with_playwright(page, url: str, out_path: str, log: RunLog) -> None:
    log.event("download.start", url=url, out_path=out_path)
    resp = await page.request.get(url, timeout=180_000)
    if not resp.ok:
        raise RuntimeError(f"Download failed: {resp.status} {resp.status_text}")
    body = await resp.body()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(body)
    log.event("download.done", bytes=len(body), content_type=resp.headers.get("content-type", ""))


def absolute_url(bi_url: str, maybe_relative: str) -> str:
    if maybe_relative.startswith("http://") or maybe_relative.startswith("https://"):
        return maybe_relative
    u = urlparse(bi_url)
    origin = f"{u.scheme}://{u.netloc}"
    if maybe_relative.startswith("/"):
        return origin + maybe_relative
    return origin + "/" + maybe_relative


def read_export_to_df(export_path: str, export_format: str, log: RunLog) -> pd.DataFrame:
    log.event("parse.start", path=export_path, format=export_format)
    if export_format.upper() == "OOXML" or export_path.lower().endswith(".xlsx"):
        df = pd.read_excel(export_path)
    else:
        # Qlik CSV_C => comma; but sometimes delimiter differs; try robust
        try:
            df = pd.read_csv(export_path)
        except Exception:
            df = pd.read_csv(export_path, sep=";")
    log.event("parse.done", rows=int(df.shape[0]), cols=int(df.shape[1]))
    return df


def write_outputs(df: pd.DataFrame, cfg: ExportConfig, meta: Dict[str, Any], log: RunLog) -> None:
    os.makedirs(os.path.dirname(cfg.out_xlsx), exist_ok=True)

    # Always write CSV
    df.to_csv(cfg.out_csv, index=False)
    log.event("write.csv", path=cfg.out_csv, rows=int(df.shape[0]))

    # XLSX row limit safety
    max_rows = 1_048_000
    with pd.ExcelWriter(cfg.out_xlsx, engine="openpyxl") as xw:
        if len(df) <= max_rows:
            df.to_excel(xw, sheet_name="data", index=False)
        else:
            # split by year if possible
            date_col = find_date_column(list(df.columns))
            if date_col:
                dt_series = pd.to_datetime(df[date_col], errors="coerce", utc=True)
                tmp = df.assign(__year=dt_series.dt.year)
                for y in sorted(tmp["__year"].dropna().unique()):
                    part = tmp[tmp["__year"] == y].drop(columns=["__year"])
                    part.to_excel(xw, sheet_name=f"data_{int(y)}", index=False)
            else:
                # last resort: first chunk
                df.head(max_rows).to_excel(xw, sheet_name="data_part1", index=False)

        # meta sheet
        meta_df = pd.DataFrame([{"key": k, "value": json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v} for k, v in meta.items()])
        meta_df.to_excel(xw, sheet_name="meta", index=False)

        # logs sheet
        log_df_to_sheet(xw, log)

    log.event("write.xlsx", path=cfg.out_xlsx)


async def main_async() -> int:
    load_dotenv()

    bi_url = os.getenv("BI_URL", "").strip()
    if not bi_url:
        raise SystemExit("BI_URL is required")

    years = [int(x) for x in parse_list_csv(os.getenv("YEARS", "2024,2025,2026"))]
    cpv_codes = parse_list_csv(os.getenv("CPV_CODES", ",".join(CPV_DEFAULT))) or CPV_DEFAULT
    viz_id = os.getenv("VIZ_ID", "").strip()
    discover_only = os.getenv("DISCOVER_ONLY", "false").lower() == "true"

    out_xlsx = os.getenv("OUT_XLSX", "data/prozorro_bi_milk_2024_2026.xlsx")
    out_csv = os.getenv("OUT_CSV", "data/prozorro_bi_milk_2024_2026.csv")
    log_jsonl = os.getenv("LOG_JSONL", "data/prozorro_bi_milk_2024_2026.logs.jsonl")
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # Use CSV export by default, then we re-pack to XLSX with logs/meta
    export_format = os.getenv("EXPORT_FORMAT", "CSV_C").strip() or "CSV_C"

    cfg = ExportConfig(
        bi_url=bi_url,
        years=years,
        cpv_codes=cpv_codes,
        viz_id=viz_id,
        discover_only=discover_only,
        out_xlsx=out_xlsx,
        out_csv=out_csv,
        log_jsonl=log_jsonl,
        headless=headless,
        export_format=export_format,
    )

    log = RunLog(jsonl_path=cfg.log_jsonl)
    log.event("run.start", bi_url=cfg.bi_url, years=",".join(map(str, cfg.years)), cpv_codes=",".join(cfg.cpv_codes), utc=utc_now_iso())

    meta: Dict[str, Any] = {
        "bi_url": cfg.bi_url,
        "years": cfg.years,
        "cpv_codes": cfg.cpv_codes,
        "export_format": cfg.export_format,
        "discover_only": cfg.discover_only,
        "requested_viz_id": cfg.viz_id,
        "run_utc": utc_now_iso(),
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=cfg.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        log.event("browser.goto", url=cfg.bi_url)
        await page.goto(cfg.bi_url, wait_until="networkidle", timeout=180_000)

        # Run in-page JS (Capability API)
        log.event("qlik.inpage.start")
        inpage_cfg = {
            "viz_id": cfg.viz_id,
            "field_cpv": os.getenv("FIELD_CPV", "").strip(),
            "field_year": os.getenv("FIELD_YEAR", "").strip(),
            "years": cfg.years,
            "cpv_codes": cfg.cpv_codes,
            "discover_only": cfg.discover_only,
            "export_format": cfg.export_format,
        }

        res = await page.evaluate(INPAGE_JS, inpage_cfg)
        log.event("qlik.inpage.done", ok=bool(res.get("ok")), error=str(res.get("error", "")))

        # persist candidates/meta
        meta["qlik_meta"] = res.get("meta", {})
        meta["candidates"] = res.get("candidates", [])
        meta["chosen"] = res.get("chosen", {})
        meta["inpage_logs"] = res.get("logs", [])

        if not res.get("ok"):
            log.event("run.fail", reason="inpage failed", error=str(res.get("error", "")))
            log.flush()
            raise RuntimeError(res.get("error", "Unknown inpage error"))

        # If discover-only: write XLSX with logs/meta but no data
        if cfg.discover_only:
            df_empty = pd.DataFrame([])
            write_outputs(df_empty, cfg, meta, log)
            log.event("run.done_discover_only")
            log.flush()
            await browser.close()
            return 0

        link = res.get("exportLink")
        if not link:
            raise RuntimeError("No exportLink returned by exportData()")

        dl_url = absolute_url(cfg.bi_url, link)
        meta["export_url"] = dl_url

        # Decide temp export filename
        tmp_path = "data/_tmp_export.xlsx" if cfg.export_format.upper() == "OOXML" else "data/_tmp_export.csv"
        await download_with_playwright(page, dl_url, tmp_path, log)

        await browser.close()

    # Parse + post-filter (safety if selections failed)
    df = read_export_to_df(tmp_path, cfg.export_format, log)
    df2 = filter_df(df, cfg.years, cfg.cpv_codes, log)

    meta["rows_raw"] = int(df.shape[0])
    meta["rows_filtered"] = int(df2.shape[0])

    write_outputs(df2, cfg, meta, log)
    log.event("run.done", rows=int(df2.shape[0]))
    log.flush()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
