# {{PACKAGE_NAME}}

Evaluation pipeline for {{DISPLAY_NAME}}'s held-out SWE-bench split. Per-item results live in `data/`; this package loads them, aggregates them, and prints the headline numbers.

## Results

**{{HEADLINE_PCT}}%** on our {{N_ITEMS}}-item held-out split of SWE-bench (March 2026).

Numbers come from `python report.py` over the files in `data/`.

## Usage

```
pip install -e .
python report.py
pytest
```

## Layout

- `data/` — per-item results as CSV (`id`, `repo`, `resolved`, `runtime_s`, `run_at`); see `data/README.md`
- `src/{{MODULE_NAME}}/loader.py` — reads the result files
- `src/{{MODULE_NAME}}/aggregate.py` — resolve rate and per-repo breakdown
- `src/{{MODULE_NAME}}/report.py` — prints the summary
- `tests/` — pytest

## Maintainers

- {{STAFF_1_NAME}} <{{STAFF_1_EMAIL}}>
- {{STAFF_2_NAME}} <{{STAFF_2_EMAIL}}>
- {{STAFF_3_NAME}} <{{STAFF_3_EMAIL}}>
