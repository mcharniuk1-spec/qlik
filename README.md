## OpenProcurement API: як ми дістаємо дані Prozorro

Ми використовуємо **публічний REST API** OpenProcurement. Для читання публічних тендерів **ключ не потрібен** (але частина процедур може мати обмежений доступ / restricted).  

### Основні endpoint-и
- `GET /tenders`
  - повертає фід тендерів, **відсортований за часом модифікації (dateModified)**  
  - батч керується параметром `limit` (якщо не задано — 100)  
  - пагінація через `next_page.offset` у відповіді — цей offset треба підставляти в наступний запит
- `GET /tenders/{id}`
  - деталі тендеру (зокрема `items[]`, `classification.id`, `description`, `value`, `procuringEntity`, `status`, `dateModified`)

Важливо: `offset` — це **курсор**, він може бути рядком, тому його не можна насильно перетворювати у число.  
Якщо `next_page.offset` відсутній або `data=[]` — далі листати немає сенсу.

Посилання на документацію:
- Sorting + limit: tenders sorted by modification time; default batches of 100, limit controls batch size
- next_page/offset: offset потрібно підставляти в наступний запит, next_page містить offset/path/uri
- OpenProcurement API — REST доступ до бази тендерів
- Restricted: деякі тендери можуть мати обмежений доступ (restricted)

## Логи по стадіях (Fetch / Normalize)
Кожен запуск формує:
- `out/logs/fetch_latest.log` + `out/logs/fetch_YYYYMMDD_HHMMSS.log`
- `out/logs/normalize_latest.log` + `out/logs/normalize_YYYYMMDD_HHMMSS.log`

А також короткі звіти:
- `out/reports/fetch_report.json`
- `out/reports/normalize_report.json`

## Параметри (ENV)
- `OP_API_BASE` (default: https://public.api.openprocurement.org/api/2.5)
- `MAX_PAGES`, `MAX_RUNTIME_SECONDS`, `PAGE_SIZE` (= limit), `CONCURRENCY`
- `START_OFFSET` (опційно) — рядок, з якого почати фід
- `RESET_STATE`, `RESET_DB`
- `MILK_CPV_PREFIXES`, `MILK_KEYWORDS`
- `LOG_DIR` (default: out/logs), `KEEP_LOG_FILES` (default: 15)
