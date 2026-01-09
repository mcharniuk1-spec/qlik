# Prozorro Milk Export (OpenProcurement API)

Цей репозиторій інкрементально витягує тендери з публічного OpenProcurement API та зберігає лише релевантні до "молока" позиції, потім експортує CSV + XLSX.

## Чому інкрементально
GitHub-hosted runners мають ліміт часу виконання job (типово ~6 годин), тому “всю історію одразу” тягнути не можна — треба дробити.  
API /tenders пагінується через next_page.offset (це курсор, який треба зберігати).  

## Де лежать дані
- `data/state.json` — курсор offset, статистика, прогрес
- `data/prozorro_milk.sqlite` — накопичені "milk" записи (персист між ранами)
- `out/milk_items.csv`
- `out/milk_tenders.csv`
- `out/milk_export.xlsx` (2 sheets)

## Налаштування через env
- OP_API_BASE (default: https://public.api.openprocurement.org/api/2.5)
- MODE: incremental|backfill
- MAX_PAGES, MAX_RUNTIME_SECONDS, PAGE_SIZE, CONCURRENCY
- MILK_CPV_PREFIXES (default: 1551)
- MILK_KEYWORDS (csv string)

## Альтернатива “взяти все одним файлом”
Якщо тобі потрібно “весь Prozorro dataset” без API-сканування:
- На порталі відкритих даних є набір CSV по закупівлях Prozorro (дуже великий), його можна качати і фільтрувати локально.  
