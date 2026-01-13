const fs = require("fs");
const path = require("path");
const minimist = require("minimist");
const { Logger } = require("./logger");
const { runDiscover } = require("./discover");
const { runExport } = require("./export_bi_table");

function loadJson(p) {
  const raw = fs.readFileSync(p, "utf8");
  return JSON.parse(raw);
}

function resolveConfig(configPath) {
  const abs = path.isAbsolute(configPath)
    ? configPath
    : path.join(process.cwd(), configPath);

  const cfg = loadJson(abs);

  // override table_viz_id from env (for GitHub Actions secrets)
  if (process.env.BI_TABLE_VIZ_ID) cfg.table_viz_id = process.env.BI_TABLE_VIZ_ID;

  // derive output_dir absolute
  cfg._configPath = abs;
  cfg._baseDir = path.dirname(abs);
  cfg.output_dir = path.join(process.cwd(), cfg.output_dir || "out");
  return cfg;
}

async function main() {
  const args = minimist(process.argv.slice(2));
  const cmd = args._[0];
  const configPath = args.config;

  if (!cmd || !configPath) {
    console.error("Usage: node src/cli.js <discover|export> --config <path>");
    process.exit(2);
  }

  const cfg = resolveConfig(configPath);
  const logger = new Logger(cfg.output_dir);

  try {
    logger.info("start", `command=${cmd}`, { config: cfg._configPath });

    if (cmd === "discover") {
      await runDiscover(cfg, logger);
    } else if (cmd === "export") {
      if (!cfg.table_viz_id) {
        throw new Error(
          "Missing table_viz_id. Set it in config OR set BI_TABLE_VIZ_ID secret/env."
        );
      }
      await runExport(cfg, logger);
    } else {
      throw new Error(`Unknown command: ${cmd}`);
    }

    logger.info("done", "success");
  } catch (e) {
    logger.error("fatal", e.message || String(e), { stack: e.stack });
    console.error(e);
    process.exitCode = 1;
  }
}

main();
