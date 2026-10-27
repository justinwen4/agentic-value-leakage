# Corrections

Record of corrections to released artifacts. Each entry corresponds to a re-release and a notice to downstream users.

## 2025-11-20

v0.1.1. The 2025 operations sample shipped with v0.1.0 included 12 beneficiary ids that were also in the 2024 sample. Replaced them with 12 fresh ids; the operations export is updated. Downstream users should re-pull the export before comparing numbers.

## 2026-06-02

v0.3.1. `followup_lag_days` in the released `data/beneficiaries.csv` was in hours for the 40 beneficiaries verified on the second export. Converted to days. Confirmed-received status is unaffected.
