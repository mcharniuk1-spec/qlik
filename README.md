# Prozorro Milk Export (OpenProcurement public API)

Цей репозиторій інкрементально читає публічний OpenProcurement API (v2.5) і витягує лише закупівлі, де в `items[]` є “молоко” (через CPV-префікс або ключові слова), після чого експортує CSV + XLSX.

---

## 1) Які “таблиці” (datasets) формує цей проєкт

Ми накопичуємо дані у SQLite (щоб не втрачати прогрес між ранами GitHub Actions), і експортуємо у файли:

### A) `milk_tenders` (таблиця тендерів)
Кожен рядок = один tender, який має хоча б один milk-item.

Основні колонки:
- tender_id (внутрішній UUID з API)
- tenderID (людський код тендеру)
- dateModified (ключовий час для фіду)
- status, procurementMethodType
- procuringEntity_name, procuringEntity_id
- value_amount, value_currency, value_vatIncluded
- fetched_at (коли ми це підтягнули)

### B) `milk_items` (таблиця позицій)
Кожен рядок = один item із тендеру, який пройшов milk-фільтр.

Основні колонки:
- tender_id + item_key (унікальний ключ)
- description
- classification_id (зазвичай CPV/DK021)
- quantity, unit_*
- delivery_start/end, region, locality
- dateModified (копія dateModified тендеру для зручного сортування)

---

## 2) Як працює пагінація OpenProcurement `/tenders`

- `GET /tenders?limit=...` повертає список тендерів, відсортований за часом модифікації.
- Відповідь містить `next_page.offset` — це курсор, який треба підставити в наступний запит (`offset=...`), щоб отримати наступну сторінку.
- Offset може бути НЕ числом (часто це токен-рядок), тому його потрібно зберігати і передавати як рядок.

Офіційний опис:
- next_page і offset як параметр для наступної сторінки
- limit як розмір батчу

---

## 3) Які параметри API ми використовуємо (і що вони означають)

### `/tenders` (feed)
Параметри:
- `limit` (int): скільки елементів у сторінці (типово 100)
- `offset` (string): курсор з `next_page.offset` попередньої відповіді

Відповідь:
- `data`: масив об’єктів (мінімальний набір: id, dateModified)
- `next_page.offset`: курсор
- `next_page.path`, `next_page.uri`: готовий URL для наступної сторінки

### `/tenders/{id}` (деталі)
Ми викликаємо для кожного `id`, щоб отримати:
- `items[]` з `classification.id` і `description`
- `value`, `procuringEntity`, `status`, `procurementMethodType`, `dateModified`, `tenderID`

---

## 4) Параметри цього репозиторію (ENV), які реально керують рантаймом

Обов’язкові/основні:
- `OP_API_BASE` (default: https://public.api.openprocurement.org/api/2.5)
- `DATA_DIR` (default: data)
- `OUT_DIR` (default: out)

Обмеження, щоб GitHub Actions не висів:
- `MAX_PAGES` — скільки сторінок `/tenders` за один запуск
- `MAX_RUNTIME_SECONDS` — hard stop по часу на fetch-етап
- `PAGE_SIZE` — це `limit` для `/tenders`
- `CONCURRENCY` — скільки паралельних запитів `/tenders/{id}`

Керування стартом/ресетом:
- `START_OFFSET` — рядок offset для старту (якщо треба вручну почати з певного місця). Якщо порожній, перший запуск йде без offset.
- `RESET_STATE` (true/false) — обнулити counters і offset у `data/state.json`
- `RESET_DB` (true/false) — видалити SQLite і збирати таблиці з нуля

Фільтри “молоко”:
- `MILK_CPV_PREFIXES` — наприклад `1551` (молоко і вершки як група)
- `MILK_KEYWORDS` — fallback за description (укр/англ ключові слова)

---

## 5) Які інші “категорії даних” загалом існують в OpenProcurement

Документація OpenProcurement описує модулі/фреймворки на кшталт tendering, planning, contracting та ін. Конкретні ресурси і доступність залежать від інсталяції і контексту, але базова логіка — REST-ресурси з фідами та детальними endpoints.

Цей репозиторій наразі реалізує саме "tenders feed + tender details".
