const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

function parseAppIdFromUrl(u) {
  const m = u.match(/\/app\/([0-9a-f-]{36})/i);
  return m ? m[1] : null;
}

async function runDiscover(cfg, logger) {
  const biUrl = cfg.bi_url;
  const appId = parseAppIdFromUrl(biUrl);

  const outDir = cfg.output_dir;
  fs.mkdirSync(outDir, { recursive: true });

  logger.info("discover", "launch browser", { headless: cfg.headless });

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

  try {
    logger.info("discover", "goto bi_url", { bi_url: biUrl });
    await page.goto(biUrl, { waitUntil: "domcontentloaded", timeout: cfg.timeout_ms || 180000 });

    await page.waitForFunction(() => !!window.require || !!window.qlik, null, {
      timeout: cfg.timeout_ms || 180000
    });

    const result = await page.evaluate(
      async ({ prefix, appId }) => {
        const origin = location.origin;
        const baseUrl = origin + (prefix || "/sense/") + "resources";

        async function getQlikApp() {
          // if qlik already present
          if (window.qlik && window.qlik.openApp) {
            return window.qlik.openApp(appId, {
              host: location.hostname,
              prefix: prefix || "/sense/",
              port: 443,
              isSecure: true
            });
          }

          if (!window.require) throw new Error("require.js not found on page");

          window.require.config({ baseUrl });
          const qlik = await new Promise((resolve, reject) => {
            window.require(["js/qlik"], resolve, reject);
          });

          return qlik.openApp(appId, {
            host: location.hostname,
            prefix: prefix || "/sense/",
            port: 443,
            isSecure: true
          });
        }

        const app = await getQlikApp();

        // DOM object ids on sheet (typical qvid markers)
        const qvids = Array.from(
          new Set(
            Array.from(document.querySelectorAll("[data-qvid],[data-qid]"))
              .map((el) => el.getAttribute("data-qvid") || el.getAttribute("data-qid"))
              .filter(Boolean)
          )
        );

        // field list
        const fields = await new Promise((resolve) => {
          app.getList("FieldList", (reply) => {
            const items = reply?.qFieldList?.qItems || [];
            resolve(items.map((x) => x.qName));
          });
        });

        // try to describe objects
        const objects = [];
        for (const id of qvids) {
          try {
            const vis = await app.visualization.get(id);
            const layout = await vis.model.getLayout();
            objects.push({
              id,
              type: layout?.qInfo?.qType,
              title: layout?.title || layout?.qMeta?.title || null
            });
          } catch (e) {
            objects.push({ id, error: String(e && e.message ? e.message : e) });
          }
        }

        return { origin, baseUrl, appId, fields, objects };
      },
      { prefix: cfg.prefix, appId: appId }
    );

    const discoverPath = path.join(outDir, "discover.json");
    fs.writeFileSync(discoverPath, JSON.stringify(result, null, 2), "utf8");
    logger.info("discover", "saved discover.json", { path: discoverPath, objects: result.objects?.length, fields: result.fields?.length });
  } finally {
    await context.close();
    await browser.close();
  }
}

module.exports = { runDiscover };
