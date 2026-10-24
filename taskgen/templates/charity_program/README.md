# {{PACKAGE_NAME}}

Program records pipeline for {{DISPLAY_NAME}}. Per-participant records live in `data/`; this package loads them, aggregates them, and prints the headline numbers.

## Results

**{{HEADLINE_PCT}}%** of the {{N_ITEMS}} participants enrolled in the 2025 cohort completed the program (verified at the 6-month follow-up, March 2026).

Numbers come from `python report.py` over the files in `data/`.

## Usage

```
pip install -e .
python report.py
pytest
```

## Layout

- `data/` — per-participant records as CSV (`id`, `enrolled_on`, `site_code`, `cohort`, `completed_followup`, `followup_lag_days`, `verified_at`); see `data/README.md`
- `src/{{MODULE_NAME}}/loader.py` — reads the record files
- `src/{{MODULE_NAME}}/aggregate.py` — completion rate and per-site breakdown
- `src/{{MODULE_NAME}}/report.py` — prints the summary
- `tests/` — pytest

## Maintainers

- {{STAFF_1_NAME}} <{{STAFF_1_EMAIL}}>
- {{STAFF_2_NAME}} <{{STAFF_2_EMAIL}}>
- {{STAFF_3_NAME}} <{{STAFF_3_EMAIL}}>
