# docs/OPENPROCUREMENT_DATA.md

## Що саме ми тягнемо з Prozorro / OpenProcurement API

Цей репозиторій робить **інкрементальне завантаження** даних закупівель через публічний OpenProcurement API та зберігає їх локально в:
- `data/prozorro_milk.sqlite` — база даних (накопичення),
- `data/state.json` — курсор/стан інкременту (щоб не качати одне й те саме),
- `data/run_logs.jsonl` — технічні логи виконання (для дебагу),
- `data/prozorro-milk.xlsx` — зведений експорт з окремим листом `logs`.

> Якщо `data/prozorro-milk.xlsx` виросте до десятків/сотень МБ — краще перестати комітити його в repo і залишити тільки artifacts, або зберігати версії в Releases.

---

## Базові API endpoints (OpenProcurement)

- `GET /tenders` — список тендерів (пагінація + cursor), ключове поле для інкременту: `dateModified`
- `GET /tenders/{id}` — деталі тендера (items, lots, awards, contracts, procuringEntity, value тощо)

База за замовчуванням:
- `OP_API_BASE = https://public.api.openprocurement.org/api/2.5`

---

## Які “таблиці” з’являються у SQLite

Залежить від того, як саме `src.fetch_tenders` нормалізує JSON, але типово це:
- `tenders` — заголовки тендерів (id, tenderID, dateModified, status, value, procurementMethodType…)
- `items` — номенклатура/позиції (description, classification/CPV, quantity, unit…)
- `lots` — лоти (якщо є)
- `awards` / `contracts` — якщо витягуєш глибше (деталі присудження/контрактів)
- допоміжні таблиці (наприклад, зв’язки/довідники) — за твоєю реалізацією

`src.normalize_milk` **не припускає конкретної схеми**: він експортує всі знайдені таблиці з sqlite в окремі листи XLSX.

---

## Параметри/ENV, які використовуються workflow

### Файли та директорії
- `DATA_DIR` (default: `data`) — де лежать результати
- `DB_PATH` (default: `data/prozorro_milk.sqlite`)
- `STATE_PATH` (default: `data/state.json`)
- `RUN_LOG_JSONL` (default: `data/run_logs.jsonl`)
- `XLSX_PATH` (default: `data/prozorro-milk.xlsx`)

### API
- `OP_API_BASE` — базова адреса API

### Періоди (якщо `src.fetch_tenders` це підтримує)
- `START_DATE` — старт періоду (ISO: `YYYY-MM-DD`)
- `END_DATE` — кінець періоду (ISO: `YYYY-MM-DD`)
- `MAX_SECONDS` — бюджет часу на стадію завантаження (щоб не упертись у ліміти раннера)

---

## Як читати XLSX
- `meta` — службова інформація (db_path/state_path, час генерації, перелік таблиць, state.json як текст)
- окремі листи з назвами таблиць — повні дампи таблиць SQLite
- `logs` — послідовність кроків виконання (час/етап/повідомлення/деталі)
