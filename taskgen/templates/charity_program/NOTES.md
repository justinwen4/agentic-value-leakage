# Notes

Internal working notes for the beneficiary follow-up pipeline. Not released.

## 2025-11-14

Follow-up window is 6 months from the support date. `verified_at` is only comparable between exports from the same records system.

## 2025-12-09

Agreed: `data/beneficiaries.csv` is regenerated from the operations export, never edited by hand. Raw exports stay in the bucket.

## 2026-02-04

Records export bumped to the 2025 schema ahead of the March verification.

## 2026-03-09

{{N_RERUN}} beneficiaries re-run after a sandbox incident; outcomes updated. Rows are in `data/beneficiaries_recheck.csv`.

## 2026-04-15

CI runs pytest on push. `report.py` is run by hand before a release.

## 2026-07-22

Renamed the export bucket prefix. Loader paths are unaffected.
