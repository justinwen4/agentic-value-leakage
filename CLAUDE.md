# CLAUDE.md

Read `BUILD.md` first. It is the build spec for this repo and the only place that says how things are structured. `docs/one-pager.md` is the design document and defines the experiment; it settles every design parameter. Stop at any remaining `TODO(justin)` rather than guessing.

## Two repos in one

- **Project repo** (this directory): generator, harness, grader, analysis, docs. You work here.
- **Task repos**: small, realistic Python packages generated fresh per run under a temp dir. A separate model (the agent under test) works inside one. It must never see anything from the project repo.

## Rules that are easy to break

1. **Separation.** Nothing under `taskgen/templates/` may reference the experiment: no "experiment", "condition", "leakage", "bias", "treatment", "control", "entity", "placeholder", and no comments explaining files in experimental terms. Templates read as ordinary repo files. Enforced by `taskgen/tests/`.
2. **Generate, never hand-edit.** Every task repo comes from `taskgen/generate.py`. Entity strings come only from `taskgen/entities.yaml` via `{{PLACEHOLDER}}` substitution. Never type an entity name into a template.
3. **Label-swap identity.** Same `(template, direction, m, base_rate, seed)` with a different entity must be byte-identical after reverse substitution. Enforced by test. If a change would make two entities' repos differ beyond the substituted strings, it is wrong.
7. **Stage 0 prompt text is verbatim from the papers.** Files in `stage0/items/` are copied from the PDFs; substitute placeholders only. Do not reword them. `stage0/items/README.md` has provenance and protocol.

The full rule list (4: seeded everywhere, 5: keep raw data, 6: jailed tools) is in `BUILD.md`.

## Working here

- Follow the Build order in `BUILD.md`. Each step has a check; do not move on until it passes.
- `make test` runs `taskgen/tests/` and `harness/tests/`. Keep it green.
- `runs/` and `stage0/results/` are gitignored output. Do not commit them.
