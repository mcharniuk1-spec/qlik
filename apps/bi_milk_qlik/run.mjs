import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const DATA_DIR = "data";
const LOG_PATH = path.join(DATA_DIR, "bi_milk_export.log");
const DISCOVER_JSON = path.join(DATA_DIR, "bi_milk_discover.json");
const RAW_XLSX = path.join(DATA_DIR, "bi_milk_raw.xlsx");

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function log(stage, message, extra = null) {
  const row = {
    ts: new Date().toISOString(),
    stage,
    message,
    ...(extra ? { extra } : {})
  };
  fs.appendFileSync(LOG_PATH, JSON.stringify(row) + "\n", "utf8");
}

function envCsv(name, fallback = "") {
  const v = process.env[name] ?? fallback;
  return v.split(",").map(s => s.trim()).filter(Boolean);
}

function mustEnv(name) {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env ${name}`);
  return v;
}

async function withTimeout(promise, ms, label) {
  let t;
  const timeout = new Promise((_, rej) => {
    t = setTimeout(() => rej(new Error(`Timeout: ${label} (${ms}ms)`)), ms);
  });
  const res = await Promise.race([promise, timeout]);
  clearTimeout(t);
  return res;
}

async function discover(page) {
  log("discover", "Scanning DOM for possible Qlik objects (data-qvid).");
  const qvids = await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll("[data-qvid]"));
    const ids = Array.from(new Set(nodes.map(n => n.getAttribute("data-qvid")).filter(Boolean)));
    return ids;
  });

  const result = { bi_url: page.url(), found_qvids: qvids, hint: "Pick the main table VIZ_ID (qvid) and re-run mode=export." };
  fs.writeFileSync(DISCOVER_JSON, JSON.stringify(result, null, 2), "utf8");
  log("discover", `Found ${qvids.length} ids. Saved ${DISCOVER_JSON}`);
}

async function exportViaQlik(page, { vizId, fieldYear, years, fieldCpv, cpvCodes }) {
  log("export", "Trying Qlik exportData(OOXML) first.");

  const res = await page.evaluate(async (args) => {
    const { vizId, fieldYear, years, fieldCpv, cpvCodes } = args;

    function loadQlik() {
      return new Promise((resolve, reject) => {
        if (!window.require) return reject(new Error("window.require not found"));
        window.require(["js/qlik"], resolve, reject);
      });
    }

    function appIdFromPath() {
      const parts = window.location.pathname.split("/");
      const i = parts.indexOf("app");
      if (i === -1 || !parts[i + 1]) throw new Error("Cannot parse app id from url path");
      return parts[i + 1];
    }

    const qlik = await loadQlik();
    const appId = appIdFromPath();

    const app = qlik.openApp(appId, {
      host: window.location.hostname,
      prefix: "/sense/",
      port: 443,
      isSecure: true
    });

    async function selectValues(fieldName, values) {
      if (!fieldName || !values || values.length === 0) return;
      const f = app.field(fieldName);
      const qVals = values.map(v => ({ qText: String(v) }));
      await f.selectValues(qVals, true, true);
    }

    await selectValues(fieldYear, years);
    await selectValues(fieldCpv, cpvCodes);

    const viz = await app.visualization.get(vizId);

    // exportData per Qlik Capability API: exports the entire hypercube (not just current page)
    const exp = await viz.exportData({ format: "OOXML" });
    // Some environments return { qUrl: "..." }, others { url: "..." }
    const url = exp?.qUrl ?? exp?.url ?? exp;

    // minimal meta
    const layout = await viz.model.getLayout();
    const size = layout?.qHyperCube?.qSize ?? null;
    return { url, size };
  }, { vizId, fieldYear, years, fieldCpv, cpvCodes });

  return res;
}

async function downloadFile(context, pageUrl, exportUrl, outPath) {
  const u = new URL(pageUrl);
  const full = exportUrl.startsWith("http")
    ? exportUrl
    : `${u.protocol}//${u.host}${exportUrl.startsWith("/") ? "" : "/"}${exportUrl}`;

  log("download", "Downloading export file.", { full });

  const resp = await context.request.get(full, { timeout: 180000 });
  if (!resp.ok()) {
    const body = await resp.text().catch(() => "");
    throw new Error(`Download failed ${resp.status()}: ${body.slice(0, 500)}`);
  }
  const buf = await resp.body();
  fs.writeFileSync(outPath, buf);
  log("download", `Saved ${outPath} (${buf.length} bytes)`);
}

async function main() {
  ensureDir(DATA_DIR);
  fs.writeFileSync(LOG_PATH, "", "utf8");

  const MODE = process.env.MODE || "export";
  const BI_URL = mustEnv("BI_URL");
  const VIZ_ID = process.env.VIZ_ID || "";
  const YEARS = envCsv("YEARS", "2024,2025,2026");
  const CPV_CODES = envCsv("CPV_CODES", "");
  const FIELD_YEAR = process.env.QLIK_FIELD_YEAR || "";
  const FIELD_CPV = process.env.QLIK_FIELD_CPV || "";

  log("start", `Mode=${MODE}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    log("nav", `Opening ${BI_URL}`);
    await withTimeout(page.goto(BI_URL, { waitUntil: "domcontentloaded" }), 180000, "goto");
    await withTimeout(page.waitForFunction("window.require && window.requirejs"), 180000, "wait requirejs");

    if (MODE === "discover") {
      await discover(page);
      return;
    }

    if (!VIZ_ID) {
      throw new Error("VIZ_ID is empty. Run mode=discover first, pick a qvid, then re-run export.");
    }

    const exp = await exportViaQlik(page, {
      vizId: VIZ_ID,
      fieldYear: FIELD_YEAR,
      years: YEARS,
      fieldCpv: FIELD_CPV,
      cpvCodes: CPV_CODES
    });

    log("export", "exportData returned.", exp);

    if (!exp?.url || typeof exp.url !== "string") {
      throw new Error(`exportData did not return a usable url. Got: ${JSON.stringify(exp)}`);
    }

    await downloadFile(context, page.url(), exp.url, RAW_XLSX);

    // Also save a tiny json summary for postprocess
    fs.writeFileSync(
      path.join(DATA_DIR, "bi_milk_meta.json"),
      JSON.stringify({ bi_url: page.url(), viz_id: VIZ_ID, years: YEARS, cpv_codes: CPV_CODES, qlik_field_year: FIELD_YEAR, qlik_field_cpv: FIELD_CPV, hypercube_size: exp.size }, null, 2)
    );
    log("done", "Raw export finished.");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((e) => {
  log("fatal", e.message, { stack: e.stack });
  console.error(e);
  process.exit(1);
});
