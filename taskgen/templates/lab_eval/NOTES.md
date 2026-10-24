# Notes

Internal working notes for the eval pipeline. Not released.

## 2025-11-14

Sandbox image is pinned in the infra repo. `runtime_s` is only comparable between runs on the same image version.

## 2025-12-09

Agreed: `data/results.csv` is regenerated from the raw sandbox logs, never edited by hand. Raw logs stay in the bucket.

## 2026-02-04

Sandbox image bumped to Python 3.12 ahead of the March run.

## 2026-03-09

{{N_RERUN}} items re-run after a sandbox incident; outcomes updated. Rows are in `data/results_rerun.csv`.

## 2026-04-15

CI runs pytest on push. `report.py` is run by hand before a release.

## 2026-07-22

Renamed the results bucket prefix. Loader paths are unaffected.
