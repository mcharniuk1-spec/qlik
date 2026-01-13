const fs = require("fs");
const path = require("path");
const ExcelJS = require("exceljs");
const { parse } = require("csv-parse");

function detectYearFromRow(row) {
  // try tenderID: UA-2024-...
  const tenderId = row.tenderID || row.tender_id || row.tenderId || row["tenderID"];
  if (tenderId) {
    const m = String(tenderId).match(/UA-(\d{4})-/);
    if (m) return Number(m[1]);
  }

  // try dateModified: 2024-...
  const dm = row.dateModified || row["dateModified"] || row["Дата зміни"] || row.date;
  if (dm) {
    const m = String(dm).match(/^(\d{4})-/);
    if (m) return Number(m[1]);
  }

  return null;
}

function normalizeCpv(v) {
  return String(v || "").trim();
}

async function getCsvHeaders(csvPath) {
  const firstLine = fs.readFileSync(csvPath, "utf8").split(/\r?\n/)[0] || "";
  // CSV_C from Qlik should be comma-separated with quotes sometimes
  // We'll parse headers properly by csv-parse
  return new Promise((resolve, reject) => {
    const headers = [];
    const parser = parse({ to_line: 1 });
    parser.on("readable", () => {
      let record;
      while ((record = parser.read())) {
        for (const h of record) headers.push(h);
      }
    });
    parser.on("error", reject);
    parser.on("end", () => resolve(headers));
    parser.write(firstLine + "\n");
    parser.end();
  });
}

async function streamCsv(csvPath, onRow) {
  return new Promise((resolve, reject) => {
    const rs = fs.createReadStream(csvPath);
    const parser = parse({
      columns: true,
      bom: true,
      relax_quotes: true,
      relax_column_count: true,
      skip_empty_lines: true
    });

    rs.on("error", reject);
    parser.on("error", reject);

    parser.on("readable", () => {
      let row;
      while ((row = parser.read())) onRow(row);
    });

    parser.on("end", resolve);
    rs.pipe(parser);
  });
}

async function writeXlsxFromCsvExports({ csvPaths, years, cpvCodes, outXlsxPath, meta, logs }) {
  fs.mkdirSync(path.dirname(outXlsxPath), { recursive: true });

  const cpvSet = new Set(cpvCodes);
  const yearSet = new Set(years.map((x) => Number(x)));

  const headers = await getCsvHeaders(csvPaths[0]);

  // Streaming writer: safer for big tables
  const wb = new ExcelJS.stream.xlsx.WorkbookWriter({
    filename: outXlsxPath,
    useStyles: false,
    useSharedStrings: true
  });

  const wsMeta = wb.addWorksheet("meta");
  wsMeta.columns = [
    { header: "key", key: "key", width: 30 },
    { header: "value", key: "value", width: 120 }
  ];

  const wsLogs = wb.addWorksheet("logs");
  wsLogs.columns = [
    { header: "ts", key: "ts", width: 28 },
    { header: "level", key: "level", width: 8 },
    { header: "stage", key: "stage", width: 14 },
    { header: "msg", key: "msg", width: 80 },
    { header: "extra", key: "extra", width: 120 }
  ];

  const wsItems = wb.addWorksheet("milk_items");
  wsItems.columns = headers.map((h) => ({ header: h, key: h, width: 18 }));

  const wsTenders = wb.addWorksheet("milk_tenders");
  wsTenders.columns = headers.map((h) => ({ header: h, key: h, width: 18 }));

  // meta
  const metaObj = {
    created_at: new Date().toISOString(),
    ...meta,
    years: years.join(","),
    cpv_codes: cpvCodes.join(","),
    csv_exports: csvPaths.map((p) => path.basename(p)).join(",")
  };
  for (const [k, v] of Object.entries(metaObj)) {
    wsMeta.addRow({ key: k, value: String(v) }).commit();
  }

  // logs
  for (const l of logs || []) {
    wsLogs
      .addRow({
        ts: l.ts,
        level: l.level,
        stage: l.stage,
        msg: l.msg,
        extra: l.extra ? JSON.stringify(l.extra) : ""
      })
      .commit();
  }

  // data streaming
  const seenTenders = new Set();
  let itemsWritten = 0;
  let tendersWritten = 0;

  for (const csvPath of csvPaths) {
    await streamCsv(csvPath, (row) => {
      // CPV filter (if field exists in export)
      const cpv =
        row.classification_id ||
        row["classification_id"] ||
        row.cpv ||
        row.CPV ||
        row["Код ДК"] ||
        row["Код CPV"];

      if (cpv) {
        const cpvNorm = normalizeCpv(cpv);
        // allow "15510000-6 — ..." => startsWith
        const ok = Array.from(cpvSet).some((code) => cpvNorm.startsWith(code));
        if (!ok) return;
      } else {
        // якщо в експорті взагалі немає CPV-колонки — не ріжемо, щоб “не втратити дані”
      }

      const y = detectYearFromRow(row);
      if (y && !yearSet.has(y)) return;

      wsItems.addRow(row).commit();
      itemsWritten++;

      const tid = row.tenderID || row.tender_id || row.tenderId || row["tenderID"];
      if (tid && !seenTenders.has(tid)) {
        seenTenders.add(tid);
        wsTenders.addRow(row).commit();
        tendersWritten++;
      }
    });
  }

  // add counts to meta
  wsMeta.addRow({ key: "items_written", value: String(itemsWritten) }).commit();
  wsMeta.addRow({ key: "tenders_written", value: String(tendersWritten) }).commit();

  wsMeta.commit();
  wsLogs.commit();
  wsItems.commit();
  wsTenders.commit();

  await wb.commit();
}

module.exports = { writeXlsxFromCsvExports };
