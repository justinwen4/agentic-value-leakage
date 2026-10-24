# Corrections

Record of corrections to released artifacts. Each entry corresponds to a re-release and a notice to downstream users.

## 2025-11-20

v0.1.1. The 2025 cohort file shipped with v0.1.0 included 12 participant ids that were also in the 2024 cohort. Replaced them with 12 fresh ids; the enrollment export is updated. Downstream users should re-pull the export before comparing numbers.

## 2026-06-02

v0.3.1. `followup_lag_days` in the released `data/participants.csv` was in hours for the 40 participants verified on the second export. Converted to days. Completion status is unaffected.
