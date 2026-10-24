PY ?= .venv/bin/python

.PHONY: test smoke stage0 midpoint pilot curves

test:
	$(PY) -m pytest taskgen/tests harness/tests

smoke:
	$(PY) -m harness.run --config configs/smoke.yaml

stage0:
	$(PY) -m stage0.run_stage0

midpoint:
	$(PY) -m harness.run --config configs/midpoint_sweep.yaml

pilot:
	$(PY) -m harness.run --config configs/pilot.yaml

curves:
	$(PY) -m analysis.fit_curves --runs runs
