PY ?= .venv/bin/python

.PHONY: test smoke grade stage0 midpoint pilot curves

test:
	$(PY) -m pytest taskgen/tests harness/tests stage0/tests analysis/tests

smoke:
	$(PY) -m harness.run --config configs/smoke.yaml

grade:
	$(PY) -m harness.grade --runs runs --config configs/smoke.yaml

stage0:
	$(PY) -m stage0.run_stage0 $(STAGE0_ARGS)

midpoint:
	$(PY) -m harness.run --config configs/midpoint_sweep.yaml

pilot:
	$(PY) -m harness.run --config configs/pilot.yaml

curves:
	$(PY) -m analysis.fit_curves --runs runs
