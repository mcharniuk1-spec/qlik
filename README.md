## BI.Prozorro (Qlik Sense) export: Milk tenders (2024–2026)

Цей репозиторій підтримує експорт даних прямо з BI.Prozorro (Qlik Sense) через **Qlik Capability API** у headless-браузері (Playwright).

### Чому саме так
Qlik Capability API працює у браузері. Скрипт відкриває sheet URL, викликає `vis.exportData()` для таблиці/візуалізації, завантажує результат і пакує фінальний XLSX з окремим листом `logs`.

- `exportData()` експортує **underlying hypercube data** та повертає посилання на файл.  
- Якщо потрібно дочитувати “сторінками”, Qlik має Table API (`qlik-table-interface`), але в цьому пайплайні базовий шлях — `exportData()`.

### Які “таблиці” можна експортувати
Практично будь-яка візуалізація, яка має HyperCube (straight table, pivot table, частина chart-ів). Експорт іде з HyperCube, а не з DOM.

### Workflow
Workflow: `.github/workflows/export_bi_milk_2024_2026.yml`

Результат:
- `data/prozorro_bi_milk_2024_2026.xlsx`:
  - `data` або `data_YYYY` — дані (за 2024–2026 і CPV-фільтром)
  - `meta` — метадані (включно з `qLastReloadTime` як індикатор “freshness”)
  - `logs` — покроковий прогрес
- `data/prozorro_bi_milk_2024_2026.csv`
- `data/prozorro_bi_milk_2024_2026.logs.jsonl`

### Параметри (env / workflow_dispatch)
- `BI_URL` — URL sheet у BI.Prozorro
- `YEARS` — кома-список років (default: `2024,2025,2026`)
- `CPV_CODES` — кома-список CPV (dairy):
  `15500000-3,15510000-6,15511000-3,15511100-4,15511210-8,15512000-0,15530000-2,15540000-5,15550000-8`
- `VIZ_ID` — (опційно) конкретний object id таблиці. Якщо порожньо, скрипт пробує авто-детект.
- `DISCOVER_ONLY=true` — режим “тільки знайти”: збирає candidates, chosen, qLastReloadTime, але не експортує data.
- `FIELD_YEAR`, `FIELD_CPV` — (опційно) назви полів у Qlik, якщо авто-детект не спрацював.
- `EXPORT_FORMAT` — `CSV_C` (default) або `OOXML` (xlsx з боку Qlik, якщо стабільно працює на твоєму app)

### Як гарантовано знайти правильний VIZ_ID
1) Запусти workflow вручну з `discover_only=true`.
2) В `data/prozorro_bi_milk_2024_2026.xlsx` → лист `meta`:
   - `candidates` містить список об’єктів і їх `qType/size/title`.
3) Візьми потрібний `id` і передай як `VIZ_ID` у звичайному запуску.
