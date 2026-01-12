## Qlik BI export (Prozorro BI) — milk tenders/items 2024–2026

This repository can export the underlying data of a Qlik Sense table from Prozorro BI using Qlik Capability APIs inside a headless browser (Playwright).

### Why Playwright is required
Qlik Capability APIs (Table API / Visualization API) run in a browser context. We load the BI sheet and then call the Visualization API `exportData()` which exports the underlying hypercube in OOXML (XLSX) or CSV.

Qlik docs:
- Visualization API `exportData(options)` supports `OOXML`, `CSV_C`, `CSV_T` and returns a URL to the generated file. It exports the entire hypercube (not only current page).  
- Table API `qlik.table` wraps hypercube data and also supports exporting data.

(See Qlik Sense Developer Help.)

### What data you can export
You can export any **visualization object** (table/pivot/etc.) that has an underlying hypercube. The exported columns are exactly the dimensions/measures used by that visualization (plus whatever the BI app developer put there).

### Configuration
Edit `config/bi_milk.json`:
- `bi_url` — full BI sheet URL
- `app_id` — Qlik app id (from URL)
- `sheet_id` — sheet id (from URL)
- `viz_id` — **ID of the table visualization object** on that sheet (required)
- `field_year`, `field_cpv` — optional Qlik field names used for selection
  - if empty, the script tries to auto-detect candidates
- `year_from`, `year_to` — export window
- `cpv_codes` — strict CPV list (dairy)
- `export_format` — `OOXML` (xlsx) or `CSV_C` / `CSV_T`

### Export parameters (Qlik exportData)
`exportData({ format, state })`
- `format`: `OOXML` (default), `CSV_C`, `CSV_T`
- `state`: `P` (possible values, default) or `A` (all values)

### Output
Workflow produces:
- `data/prozorro_bi_milk_2024_2026.xlsx`
  - `data` (or `data_2024`, `data_2025`, `data_2026` if too large)
  - `meta` (run parameters + counts + date range)
  - `per_year` (rows per year export file)
  - `logs` (step-by-step JSONL logs collected during export)

### How to find `viz_id` and field names
Run the GitHub Action with input `mode=discover`. It writes:
- `out/bi/discover.json` as an artifact (fields list + best-effort sheet object list)
Then copy `viz_id` into `config/bi_milk.json`.
