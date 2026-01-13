const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { writeXlsxFromCsvExports } = require("./xlsx_writer");

function parseAppIdFromUrl(u) {
  const m = u.match(/\/app\/([0-9a-f-]{36})/i);
  return m ? m[1] : null;
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

async function runExport(cfg, logger) {
  const biUrl = cfg.bi_url;
  const appId = parseAppIdFromUrl(biUrl);
  const years = cfg.years || [];
  const cpvCodes = cfg.cpv_codes || [];
  const vizId = cfg.table_viz_id;

  const outDir = cfg.output_dir;
  ensureDir(outDir);

  logger.info("export", "launch browser", { headless: cfg.headless, vizId });

  const browser = await chromium.launch({
    headless: !!cfg.headless,
    args: ["--disable-blink-features=AutomationControlled"]
  });

  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    userAgent:
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
  });

  const page = await context.newPage();

  const rawCsvPaths = [];

  try {
    logger.info("export", "goto bi_url", { bi_url: biUrl });
    await page.goto(biUrl, { waitUntil: "domcontentloaded", timeout: cfg.timeout_ms || 180000 });

    await page.waitForFunction(() => !!window.require || !!window.qlik, null, {
      timeout: cfg.timeout_ms || 180000
    });

    for (const y of years) {
      logger.info("export", "request exportData link", { year: y });

      const evalRes = await page.evaluate(
        async ({ prefix, appId, vizId, cpvCodes, year, exportFormat, exportState, fieldHints }) => {
          const origin = location.origin;
          const baseUrl = origin + (prefix || "/sense/") + "resources";

          async function getQlikApp() {
            if (window.__EXPORT_APP__) return window.__EXPORT_APP__;

            if (window.qlik && window.qlik.openApp) {
              window.__EXPORT_APP__ = window.qlik.openApp(appId, {
                host: location.hostname,
                prefix: prefix || "/sense/",
                port: 443,
                isSecure: true
              });
              return window.__EXPORT_APP__;
            }

            if (!window.require) throw new Error("require.js not found on page");
            window.require.config({ baseUrl });

            const qlik = await new Promise((resolve, reject) => {
              window.require(["js/qlik"], resolve, reject);
            });

            window.__EXPORT_APP__ = qlik.openApp(appId, {
              host: location.hostname,
              prefix: prefix || "/sense/",
              port: 443,
              isSecure: true
            });
            return window.__EXPORT_APP__;
          }

          function normalize(s) {
            return String(s || "").trim().toLowerCase();
          }

          function pickField(allFields, hints) {
            const normFields = allFields.map((f) => ({ raw: f, n: normalize(f) }));
            for (const h of hints || []) {
              const hn = normalize(h);
              const exact = normFields.find((x) => x.n === hn);
              if (exact) return exact.raw;
              const contains = normFields.find((x) => x.n.includes(hn));
              if (contains) return contains.raw;
            }
            return null;
          }

          const app = await getQlikApp();

          // get fields
          const fields = await new Promise((resolve) => {
            app.getList("FieldList", (reply) => {
              const items = reply?.qFieldList?.qItems || [];
              resolve(items.map((x) => x.qName));
            });
          });

          // best-effort field detection
          const cpvField = pickField(fields, fieldHints?.cpv) || pickField(fields, ["cpv", "classification"]);
          const yearField = pickField(fields, fieldHints?.year) || pickField(fields, ["year", "рік"]);
          const tenderIdField = pickField(fields, fieldHints?.tender_id) || pickField(fields, ["tenderid", "tender_id"]);
          const dateField = pickField(fields, fieldHints?.date) || pickField(fields, ["datemodified", "date"]);

          // clear selections to avoid default 2015-2016 state
          try { await app.clearAll(); } catch (e) {}

          // apply CPV selection if field exists
          if (cpvField) {
            for (const code of cpvCodes) {
              try {
                // match "15510000-6" and also "15510000-6 — ..."
                await app.field(cpvField).selectMatch(`${code}*`, true);
              } catch (e) {}
            }
          }

          // apply year selection (priority: explicit yearField -> tenderId prefix -> date prefix)
          const yearStr = String(year);

          if (yearField) {
            try {
              await app.field(yearField).selectMatch(yearStr, false);
            } catch (e) {}
          } else if (tenderIdField) {
            try {
              await app.field(tenderIdField).selectMatch(`UA-${yearStr}*`, false);
            } catch (e) {}
          } else if (dateField) {
            try {
              await app.field(dateField).selectMatch(`${yearStr}-*`, false);
            } catch (e) {}
          }

          // get hypercube size (rows) to validate selection actually moved away from 2015/2016
          const vis = await app.visualization.get(vizId);
          const layout = await vis.model.getLayout();
          const rows = layout?.qHyperCube?.qSize?.qcy ?? null;

          // build export link
          const linkObj = await vis.exportData({ format: exportFormat, state: exportState });
          const link = linkObj?.qUrl || linkObj;

          return {
            origin,
            cpvField,
            yearField,
            tenderIdField,
            dateField,
            rows,
            link
          };
        },
        {
          prefix: cfg.prefix,
          appId,
          vizId,
          cpvCodes,
          year: y,
          exportFormat: cfg.export_format || "CSV_C",
          exportState: cfg.export_state || "P",
          fieldHints: cfg.field_hints || {}
        }
      );

      logger.info("export", "selection+export prepared", evalRes);

      if (!evalRes.link) {
        throw new Error(`No export link returned for year=${y}. Check viz_id and object type.`);
      }

      const absUrl = new URL(evalRes.link, evalRes.origin).toString();
      logger.info("download", "downloading export", { year: y, url: absUrl });

      const resp = await context.request.get(absUrl, { timeout: cfg.timeout_ms || 180000 });
      if (!resp.ok()) {
        throw new Error(`Download failed year=${y}: HTTP ${resp.status()}`);
      }

      const buf = await resp.body();
      const outCsv = path.join(outDir, `raw_export_${y}.csv`);
      fs.writeFileSync(outCsv, buf);
      rawCsvPaths.push(outCsv);

      logger.info("download", "saved raw csv", { year: y, path: outCsv, bytes: buf.length });
    }

    // build final XLSX (items + tenders + logs + meta)
    const xlsxPath = path.join(outDir, cfg.output_xlsx || "prozorro-bi-milk-2024-2026.xlsx");

    await writeXlsxFromCsvExports({
      csvPaths: rawCsvPaths,
      years,
      cpvCodes,
      outXlsxPath: xlsxPath,
      meta: {
        bi_url: cfg.bi_url,
        table_viz_id: cfg.table_viz_id,
        export_format: cfg.export_format,
        export_state: cfg.export_state
      },
      logs: logger.getEntries()
    });

    logger.info("xlsx", "saved workbook", { path: xlsxPath });

    // also save small manifest json
    const manifest = {
      ts: new Date().toISOString(),
      xlsx: path.basename(xlsxPath),
      raw_exports: rawCsvPaths.map((p) => path.basename(p)),
      years,
      cpvCodes
    };
    fs.writeFileSync(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
  } finally {
    await context.close();
    await browser.close();
  }
}

module.exports = { runExport };
