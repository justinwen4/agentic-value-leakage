# data

- `beneficiaries.csv` — one row per sampled beneficiary from the March 2026 follow-up. Columns: `id`, `support_date`, `site_code`, `operations_year`, `confirmed_received` (0/1), `followup_lag_days`, `verified_at` (UTC).
- `beneficiaries_recheck.csv` — {{N_RERUN}} beneficiaries re-run after a sandbox incident; outcomes updated. Same columns, later `verified_at`.
