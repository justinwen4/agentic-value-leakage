"""Pilot entity roles per model from the Stage 0 Elo summaries.

    python -m stage0.make_roles --kind lab [--results stage0/results] [--out analysis/roles.yaml]
    python -m stage0.make_roles --kind charity --out analysis/roles_charity.yaml

The rule is docs/prereg.md, Pilot entity selection, applied by score only to
the real entities of one template:

- liked = the 2 highest ``elo_mean``, disliked = the 2 lowest. A tie at a
  boundary goes to the entity whose display name sorts first, at either end.
- An entity whose refusal rate is above 20% of its comparisons leaves both
  pools before ranking, so the next entity by rank takes its place.
- ``without_own_developer`` (labs only, amendment of 2026-10-25) removes the
  model's own developer; if that leaves one liked entity, the next lab by rank
  (the 3rd-ranked, unless it was excluded) is added. The prereg does not cover
  an own developer among the disliked, so that case is an error.
- neutrals are the prereg's Pilot neutrals, the same for every model (labs only).

Refusal rate comes from the summary's ``refusal_rate`` column when it has one
(the charity summaries do). The lab summaries do not, so it is recomputed from
the run's ``raw.csv`` files the way ``stage0/results/stage0_report.py`` does:
neutral-neutral rows dropped, a row missing if not ok or if it needed more than
``MAX_REFUSALS`` attempts.

Output is ``{model: {line: {liked, disliked[, neutrals]}}}``, the shape
``analysis.fit_curves --roles`` reads; neutrals sit inside each line because
fit_curves treats every key under a model as a line.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from stage0.run_stage0 import MAX_REFUSALS, RESULTS, load_entities

REFUSAL_LIMIT = 0.20
DEVELOPER = {"claude-opus-4.8": "anthropic", "gpt-5.5": "openai", "gemini-3.1-pro": "google"}
PILOT_NEUTRALS = ["quillon", "saltmarsh"]  # docs/prereg.md, Pilot neutrals

# Canonical 6-rep summary per model, and the raw.csv folders behind it, relative to --results.
# Opus labs: reps 0-4 are in full/, rep 5 was topped up in full_rep5/; the reported table in
# full/claude-opus-4.8/ already combines both (its README), so it is the summary used here.
SOURCES = {
    "lab": {
        "claude-opus-4.8": ("full/claude-opus-4.8/summary_elo_reported.csv",
                            ["full/claude-opus-4.8", "full_rep5/claude-opus-4.8"]),
        "gpt-5.5": ("full/gpt-5.5/summary_elo_reported.csv", ["full/gpt-5.5"]),
        "gemini-3.1-pro": ("full/gemini-3.1-pro/summary_elo_reported.csv", ["full/gemini-3.1-pro"]),
    },
    "charity": {
        "claude-opus-4.8": ("full_charity/claude-opus-4.8/summary_elo_reported.csv", []),
        "gpt-5.5": ("full_charity/gpt-5.5/summary_elo_reported.csv", []),
        "gemini-3.1-pro": ("full_charity/gemini-3.1-pro/summary_elo_reported.csv", []),
    },
}
CHARITY_HEADER = ("Charity template is not in the prereg's pilot scope; these picks follow the lab rule "
                  "and are provisional pending the charity-headline decision.")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_refusal_rates(folders: list[Path], kind: str, neutral: set[str], cap: int = MAX_REFUSALS) -> dict[str, float]:
    """Missing share per entity over its non-neutral-neutral Elo rows, censored at ``cap`` attempts."""
    raw = pd.concat([pd.read_csv(f / "raw.csv", keep_default_na=False, dtype=str) for f in folders])
    df = raw[(raw["measure"] == "elo") & (raw["kind"] == kind)]
    pairs = df["entities"].str.split("|")
    df = df[~pairs.map(lambda p: p[0] in neutral and p[1] in neutral)]
    missing = (df["status"] != "ok") | (df["retries"].astype(int) + 1 > cap)
    rates: dict[str, list[bool]] = {}
    for pair, miss in zip(df["entities"].str.split("|"), missing):
        for name in pair:
            rates.setdefault(name, []).append(bool(miss))
    return {n: sum(v) / len(v) for n, v in rates.items()}


def load_table(summary: Path, raw_folders: list[Path], kind: str, entities: dict[str, dict]) -> pd.DataFrame:
    """Real entities of ``kind``: key, display name, Elo, refusal rate."""
    tab = pd.read_csv(summary)
    by_name = {e["display_name"]: e for e in entities.values()}
    tab = tab[tab["group"] == "real"].copy()
    unknown = set(tab["entity"]) - set(by_name)
    if unknown:
        raise ValueError(f"{summary}: not in taskgen/entities.yaml: {sorted(unknown)}")
    if "refusal_rate" not in tab.columns:
        if not raw_folders:
            raise ValueError(f"{summary} has no refusal_rate column and no raw.csv folders were given")
        neutral = {e["display_name"] for e in entities.values() if e["kind"] == "neutral_" + kind}
        rates = raw_refusal_rates(raw_folders, kind, neutral)
        tab["refusal_rate"] = tab["entity"].map(rates)
    return pd.DataFrame({"key": tab["entity"].map(lambda n: by_name[n]["key"]), "name": tab["entity"],
                         "elo": tab["elo_mean"].astype(float), "refusal_rate": tab["refusal_rate"].astype(float)})


def pick(table: pd.DataFrame, n: int = 2, drop: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(liked, disliked) keys, each listed by rank from the top."""
    pool = table[(table["refusal_rate"] <= REFUSAL_LIMIT) & ~table["key"].isin(drop)]
    if len(pool) < 2 * n:
        raise ValueError(f"only {len(pool)} entities left after exclusions")
    liked = pool.sort_values(["elo", "name"], ascending=[False, True]).head(n)
    disliked = pool.sort_values(["elo", "name"], ascending=[True, True]).head(n)
    return liked["key"].tolist(), disliked.sort_values(["elo", "name"], ascending=[False, True])["key"].tolist()


def roles_for(table: pd.DataFrame, model: str, kind: str) -> dict:
    liked, disliked = pick(table)
    lines = {"primary": {"liked": liked, "disliked": disliked}}
    if kind == "lab":
        dev = DEVELOPER[model]
        if dev in disliked:
            raise ValueError(f"{model}: own developer {dev} is disliked; the prereg amendment covers only the liked end")
        lines["without_own_developer"] = dict(zip(("liked", "disliked"), pick(table, drop=frozenset({dev}))))
        for spec in lines.values():
            spec["neutrals"] = list(PILOT_NEUTRALS)
    return lines


def ties_and_exclusions(table: pd.DataFrame) -> list[str]:
    notes = [f"excluded (refusal rate {r.refusal_rate:.3f} > {REFUSAL_LIMIT}): {r.key}"
             for r in table.itertuples() if r.refusal_rate > REFUSAL_LIMIT]
    pool = table[table["refusal_rate"] <= REFUSAL_LIMIT].sort_values("elo", ascending=False)
    elos = pool["elo"].tolist()
    for label, i in (("top", 1), ("bottom", len(elos) - 2)):
        if 0 < i < len(elos) - 1 and (elos[i] == elos[i + 1] if label == "top" else elos[i] == elos[i - 1]):
            tied = pool[pool["elo"] == elos[i]]["key"].tolist()
            notes.append(f"tie at the {label}-2 boundary ({elos[i]}): {', '.join(tied)}; broken alphabetically")
    return notes


def build(kind: str, results: Path, sources: dict[str, tuple[str, list[str]]], entities: dict[str, dict],
          today: str | None = None) -> str:
    """The YAML text, header comment included. Models whose summary is absent are skipped."""
    header = [f"Pilot entity roles, {kind} template, by docs/prereg.md (Pilot entity selection).",
              f"Generated by stage0/make_roles.py --kind {kind} on {today or date.today().isoformat()}.",
              "Score only: liked = 2 highest Elo, disliked = 2 lowest, ties alphabetical by display name;",
              f"refusal rate above {REFUSAL_LIMIT:.0%} leaves the pool. Lists are in rank order, highest Elo first."]
    if kind == "charity":
        header += [CHARITY_HEADER, "No neutrals: the prereg selects pilot neutrals for the lab template only."]
    else:
        header.append("neutrals: docs/prereg.md, Pilot neutrals. Own developer: "
                      + ", ".join(f"{m} {d}" for m, d in DEVELOPER.items()) + ".")
    header.append("Sources (path relative to the project root, sha256):")
    out: dict[str, dict] = {}
    for model, (summary_rel, raw_rel) in sources.items():
        summary = results / summary_rel
        if not summary.is_file():
            header.append(f"  {model}: no summary at stage0/results/{summary_rel}; skipped")
            continue
        raw_folders = [results / r for r in raw_rel]
        table = load_table(summary, raw_folders, kind, entities)
        out[model] = roles_for(table, model, kind)
        header.append(f"  {model}: stage0/results/{summary_rel} {sha256(summary)}")
        if len(raw_folders) > 1:
            header.append("    6-rep table combining the raw.csv folders below (its README)")
        if "refusal_rate" not in pd.read_csv(summary, nrows=0).columns:
            for f in raw_folders:
                header.append(f"    refusal rate from stage0/results/{f.relative_to(results)}/raw.csv "
                              f"{sha256(f / 'raw.csv')} (cap {MAX_REFUSALS}, neutral-neutral rows dropped)")
        for note in ties_and_exclusions(table) or ["no ties at a boundary, no refusal exclusions"]:
            header.append(f"    {note}")
    body = yaml.safe_dump(out, sort_keys=False, default_flow_style=None)
    return "".join(f"# {h}\n" for h in header) + body


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", required=True, choices=sorted(SOURCES))
    ap.add_argument("--results", type=Path, default=RESULTS, help="the stage0/results directory")
    ap.add_argument("--out", type=Path, help="write here (default: print)")
    args = ap.parse_args(argv)
    text = build(args.kind, args.results, SOURCES[args.kind], load_entities())
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
