# Prozorro Milk Export (OpenProcurement API)

This repo exports procurement data related to milk from the public OpenProcurement API.

## Outputs
- `out/milk_items.csv`
- `out/milk_tenders.csv`
- `out/milk_export.xlsx` (2 sheets)

## Automation
GitHub Actions workflow: `.github/workflows/prozorro_milk_export.yml`

Runs daily and on manual dispatch.
