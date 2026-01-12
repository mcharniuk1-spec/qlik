// scripts/qlik_export_bi_milk.mjs
import fs from "fs";
import path from "path";
import process from "process";
import { chromium } from "playwright";

function nowIso() {
  return new Date().toISOString();
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function logLine(logPath, level, stage, message, extra = {}) {
  const row = { ts: nowIso(), level, stage, message, ...extra };
  fs.appendFileSync(logPath, JSON.stringify(row) + "\n");
  console.log(`[${row.ts}] [${level}] [${stage}] ${message}`);
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function pickFieldName(fieldListItems, re) {
  const hit = fieldListItems.find((x) => re.test(x.qName || ""));
  return hit ? hit.qName : "";
}

async function main() {
  const configPath = process.env.CONFIG || "config/bi_milk.json";
  const outDir = process.env.OUT_DIR || "out/bi";
  const discover = process.env.DISCOVER === "1";

  const cfg = readJson(configPath);
  ensureDir(outDir);

  const runId = process.env.GITHUB_RUN_ID || "local";
  const logPath = path.join(outDir, `run_${runId}.jsonl`);
  fs.writeFileSync(logPath, ""); // reset

  logLine(logPath, "INFO", "boot", "Starting Qlik BI export", {
    configPath,
    outDir,
    discover
  });

  const browser = await chromium.launch({
    headless: cfg.headless !== false
  });

  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 }
  });

  const page = await context.newPage();

  // Load the BI sheet (public)
  logLine(logPath, "INFO", "nav", "Opening BI URL", { bi_url: cfg.bi_url });
  await page.goto(cfg.bi_url, { waitUntil: "domcontentloaded", timeout: cfg.timeout_ms || 180000 });

  // Give Qlik time to bootstrap
  await page.waitForTimeout(6000);

  // We execute inside the page to access requirejs + qlik capability API
  const result = await page.evaluate(async (params) => {
    function sleep(ms) {
      return new Promise((r) => setTimeout(r, ms));
    }

    function abs(u) {
      try {
        return new URL(u, window.location.href).toString();
      } catch {
        return u;
      }
    }

    async function withQlik() {
      // Ensure requirejs exists
      if (!window.require) {
        throw new Error("window.require is not available. Qlik page did not bootstrap.");
      }

      // Force baseUrl for Qlik resources
      window.require.config({
        baseUrl: `${window.location.protocol}//${window.location.host}/resources`
      });

      const qlik = await new Promise((resolve, reject) => {
        window.require(["js/qlik"], (q) => resolve(q), (err) => reject(err));
      });

      const config = {
        host: window.location.host,
        prefix: "/",
        port: window.location.protocol === "https:" ? 443 : 80,
        isSecure: window.location.protocol === "https:"
      };

      const app = qlik.openApp(params.app_id, config);

      // Field discovery (best-effort)
      const fieldList = await new Promise((resolve) => {
        app.getList("FieldList", (reply) => resolve(reply));
      });

      const fields = (fieldList?.qFieldList?.qItems || []).map((x) => ({
        qName: x.qName,
        qTags: x.qTags
      }));

      // Try to auto-pick year/cpv fields if not provided
      const autoYear =
        params.field_year ||
        (fields.find((f) => /year|рік/i.test(f.qName))?.qName ?? "");
      const autoCpv =
        params.field_cpv ||
        (fields.find((f) => /cpv|дк|dk/i.test(f.qName))?.qName ?? "");

      // Try to list sheet objects (best-effort; may vary by Qlik version)
      let sheetObjects = [];
      try {
        const sheetsReply = await new Promise((resolve) => {
          app.getAppObjectList("sheet", (reply) => resolve(reply));
        });
        const items = sheetsReply?.qAppObjectList?.qItems || [];
        for (const it of items) {
          if (it?.qInfo?.qId === params.sheet_id) {
            // Some Qlik versions expose children differently; keep raw
            sheetObjects.push(it);
          }
        }
      } catch (e) {
        // ignore
      }

      if (params.discover) {
        return {
          mode: "discover",
          fields,
          autoYear,
          autoCpv,
          sheetObjects
        };
      }

      if (!params.viz_id) {
        throw new Error("viz_id is empty. Run DISCOVER=1 and set config/bi_milk.json:viz_id");
      }

      // Apply selections (best-effort; selection APIs can vary by field typing)
      // We keep this tolerant: if selection fails, export still proceeds and filtering happens in Python.
      try {
        if (autoYear) {
          await new Promise((resolve) => app.field(autoYear).selectMatch(String(params.year), true).then(resolve));
          await sleep(800);
        }
      } catch (e) {
        // ignore
      }

      try {
        if (autoCpv && params.cpv_codes?.length) {
          // Use selectMatch per code (tolerant); allows wildcards if field includes descriptions
          const fld = app.field(autoCpv);
          for (const code of params.cpv_codes) {
            try {
              await new Promise((resolve) => fld.selectMatch(`${code}*`, true).then(resolve));
              await sleep(150);
            } catch {
              // ignore
            }
          }
          await sleep(800);
        }
      } catch (e) {
        // ignore
      }

      // Export visualization data
      const vis = await app.visualization.get(params.viz_id);
      const link = await vis.exportData({
        format: params.export_format || "OOXML",
        state: "P"
      });

      return {
        mode: "export",
        year: params.year,
        export_url: abs(link),
        used_field_year: autoYear,
        used_field_cpv: autoCpv
      };
    }

    return withQlik();
  }, {
    app_id: cfg.app_id,
    sheet_id: cfg.sheet_id,
    viz_id: cfg.viz_id,
    field_year: cfg.field_year || "",
    field_cpv: cfg.field_cpv || "",
    year: cfg.year_from,
    cpv_codes: cfg.cpv_codes || [],
    export_format: cfg.export_format || "OOXML",
    discover
  });

  if (discover) {
    logLine(logPath, "INFO", "discover", "Discovery output (set viz_id/field names based on this)", {
      fields_count: result.fields?.length ?? 0
    });
    fs.writeFileSync(path.join(outDir, "discover.json"), JSON.stringify(result, null, 2));
    logLine(logPath, "INFO", "discover", "Saved out/bi/discover.json");
    await browser.close();
    return;
  }

  // Export loop 2024..2026
  const exported = [];
  for (let year = cfg.year_from; year <= cfg.year_to; year++) {
    logLine(logPath, "INFO", "export", `Exporting year ${year}`);

    const r = await page.evaluate(async (params) => {
      function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
      function abs(u) { try { return new URL(u, window.location.href).toString(); } catch { return u; } }

      window.require.config({
        baseUrl: `${window.location.protocol}//${window.location.host}/resources`
      });

      const qlik = await new Promise((resolve, reject) => {
        window.require(["js/qlik"], (q) => resolve(q), (err) => reject(err));
      });

      const config = {
        host: window.location.host,
        prefix: "/",
        port: window.location.protocol === "https:" ? 443 : 80,
        isSecure: window.location.protocol === "https:"
      };

      const app = qlik.openApp(params.app_id, config);

      // Clear previous selections to avoid “sticky” state
      try { await app.clearAll(); } catch {}

      // apply year
      try {
        if (params.field_year) {
          await app.field(params.field_year).selectMatch(String(params.year), true);
          await sleep(800);
        }
      } catch {}

      // apply cpv (tolerant; optional)
      try {
        if (params.field_cpv && params.cpv_codes?.length) {
          const fld = app.field(params.field_cpv);
          for (const code of params.cpv_codes) {
            try { await fld.selectMatch(`${code}*`, true); } catch {}
          }
          await sleep(800);
        }
      } catch {}

      const vis = await app.visualization.get(params.viz_id);
      const link = await vis.exportData({ format: params.export_format || "OOXML", state: "P" });
      return { year: params.year, export_url: abs(link) };
    }, {
      app_id: cfg.app_id,
      viz_id: cfg.viz_id,
      field_year: cfg.field_year || "",
      field_cpv: cfg.field_cpv || "",
      year,
      cpv_codes: cfg.cpv_codes || [],
      export_format: cfg.export_format || "OOXML"
    });

    const filename = `bi_milk_${year}.${(cfg.export_format || "OOXML") === "OOXML" ? "xlsx" : "csv"}`;
    const dest = path.join(outDir, filename);

    logLine(logPath, "INFO", "download", `Downloading export for ${year}`, { url: r.export_url });

    const resp = await context.request.get(r.export_url, { timeout: cfg.timeout_ms || 180000 });
    if (!resp.ok()) {
      throw new Error(`Failed to download export for ${year}: HTTP ${resp.status()}`);
    }
    const buf = await resp.body();
    fs.writeFileSync(dest, buf);

    logLine(logPath, "INFO", "download", `Saved ${dest}`, { bytes: buf.length });
    exported.push({ year, file: dest });
  }

  fs.writeFileSync(path.join(outDir, "export_index.json"), JSON.stringify({ exported, log: logPath }, null, 2));
  logLine(logPath, "INFO", "done", "Export completed", { exported_count: exported.length });

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
