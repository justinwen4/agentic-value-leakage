# Corrections

Record of corrections to released artifacts. Each entry corresponds to a re-release and a notice to downstream users.

## 2025-11-20

v0.1.1. The held-out manifest shipped with v0.1.0 included 12 items that also appear in the public SWE-bench test set. Replaced them with 12 fresh items; the manifest in the infra repo is updated. Downstream users should re-pull the manifest before comparing numbers.

## 2026-06-02

v0.3.1. `runtime_s` in the released `data/results.csv` was in milliseconds for the 40 items run on the second sandbox host. Converted to seconds. Resolved/unresolved status is unaffected.
