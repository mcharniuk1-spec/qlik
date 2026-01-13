const fs = require("fs");
const path = require("path");

class Logger {
  constructor(outDir) {
    this.outDir = outDir;
    fs.mkdirSync(outDir, { recursive: true });
    this.logPath = path.join(outDir, "run.log.jsonl");
    this.entries = [];
  }

  _write(level, stage, msg, extra) {
    const entry = {
      ts: new Date().toISOString(),
      level,
      stage,
      msg,
      ...(extra ? { extra } : {})
    };
    this.entries.push(entry);
    fs.appendFileSync(this.logPath, JSON.stringify(entry) + "\n", "utf8");
  }

  info(stage, msg, extra) {
    this._write("INFO", stage, msg, extra);
  }
  warn(stage, msg, extra) {
    this._write("WARN", stage, msg, extra);
  }
  error(stage, msg, extra) {
    this._write("ERROR", stage, msg, extra);
  }

  getEntries() {
    return this.entries;
  }
}

module.exports = { Logger };
