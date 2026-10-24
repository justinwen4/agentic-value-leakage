# data

- `participants.csv` — one row per participant from the March 2026 follow-up. Columns: `id`, `enrolled_on`, `site_code`, `cohort`, `completed_followup` (0/1), `followup_lag_days`, `verified_at` (UTC).
- `participants_recheck.csv` — {{N_RERUN}} participants re-run after a sandbox incident; outcomes updated. Same columns, later `verified_at`.
