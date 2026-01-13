# BI.Prozorro (Qlik Sense) export — milk tenders/items 2024–2026

Цей модуль робить експорт даних з BI.Prozorro (Qlik Sense) через Capability APIs:
- відкриває sheet
- скидає дефолтні selections (які часто “залипають” на старих роках)
- застосовує фільтр:
  - роки: 2024, 2025, 2026
  - CPV (dairy): 15500000-3, 15510000-6, 15511000-3, 15511100-4, 15511210-8, 15512000-0, 15530000-2, 15540000-5, 15550000-8
- викликає `exportData()` на потрібній таблиці
- зберігає:
  - `out/raw_export_<year>.csv`
  - `out/prozorro-bi-milk-2024-2026.xlsx`:
    - `milk_items` (рядки item-level)
    - `milk_tenders` (унікальні тендери за tenderID)
    - `logs` (лог кожного етапу)
    - `meta` (параметри/лічильники)

## Чому саме exportData()
`exportData` експортує дані underlying hyperCube у CSV або OOXML. Важливо: експортується весь hyperCube, а не лише поточна “сторінка” таблиці.  
Див. Qlik docs: exportData method (Visualization API).  

## Параметри exportData (коротко)
- `format`: `OOXML` | `CSV_C` (comma) | `CSV_T` (tab)
- `state`: `P` (possible values, default) або `A` (all values)

## Як знайти table_viz_id (ID таблиці)
1) Локально:
```bash
cd bi-export
npm install
npm run discover
