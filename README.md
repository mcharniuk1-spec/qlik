# Prozorro BI (Qlik) – Milk tenders export (2024–2026)

Цей репозиторій робить експорт даних напряму з BI.Prozorro (Qlik Sense) через Capability APIs.

## Чому раніше виходили 2015–2016
Якщо брати лише першу сторінку гіперкуба (qTop=0), а таблиця відсортована по даті зростанням,
то першими йдуть найстаріші записи. Правильний експорт — або `exportData` (весь гіперкуб),
або paging по всіх рядках через `GetHyperCubeData`.

Qlik підтверджує: `exportData` експортує весь гіперкуб, не лише поточну data-page.

## Які об’єкти можна експортувати
- Будь-які візуалізації Qlik, які мають underlying hypercube (таблиці, багато графіків).
- `exportData` підтримує OOXML/CSV (залежить від типу об’єкта). Для стабільності використовується OOXML.

Документація Qlik:
- exportData (Capability API Table interface) – exports entire hypercube
- Engine paging (GetHyperCubeData) – qTop/qHeight/qWidth paging

## Як це працює
Workflow:
1) Відкриває BI sheet URL (public).
2) (Опційно) застосовує селекції по полях року та CPV (якщо ти вкажеш назви полів).
3) Викликає `exportData({format: "OOXML"})` для конкретної таблиці (VIZ_ID).
4) Завантажує отриманий файл у `data/bi_milk_raw.xlsx`.
5) Postprocess:
   - робить strict-filter по CPV dairy (за префіксом 8 цифр)
   - залишає лише 2024/2025/2026
   - пише фінальний `data/bi-milk-2024-2026.xlsx` з аркушами:
     - meta
     - milk_prices
     - logs

## Параметри workflow (workflow_dispatch)
- mode: `discover` або `export`
- bi_url: посилання на Qlik sheet
- viz_id: ID візуалізації (таблиці) на sheet
- years: "2024,2025,2026"
- cpv_codes: список CPV dairy
- qlik_field_year: (опційно) назва поля року в Qlik
- qlik_field_cpv: (опційно) назва поля CPV в Qlik

## Як знайти VIZ_ID (обов’язково 1 раз)
Запусти workflow з:
- mode=discover

Результат буде в `data/bi_milk_discover.json` (і в logs).
Візьми потрібний qvid і запускай mode=export.

## Що саме зберігається у XLSX
`milk_prices` — рівно те, що лежить в Qlik-таблиці після селекцій/фільтрів,
тобто “табличне представлення” BI.Prozorro.
