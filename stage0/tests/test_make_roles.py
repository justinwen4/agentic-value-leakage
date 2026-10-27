"""stage0/make_roles.py: the prereg's pilot selection rule on fake Elo summaries (a tie,
a refusal exclusion, the own-developer backfill), the raw.csv refusal rate, and the
YAML shape analysis.fit_curves --roles reads."""
from __future__ import annotations

import hashlib

import pandas as pd
import pytest
import yaml

from stage0 import make_roles as mr

ENTITIES = {k: {"key": k, "kind": "lab", "display_name": n} for k, n in [
    ("alpha", "Alpha"), ("bravo", "Bravo"), ("charlie", "Charlie"), ("delta", "Delta"),
    ("echo", "Echo"), ("foxtrot", "Foxtrot"), ("golf", "Golf")]}
ENTITIES["quillon"] = {"key": "quillon", "kind": "neutral_lab", "display_name": "Quillon Labs"}


def summary(rows, refusal=True):
    """rows: (display name, elo[, refusal rate]); a neutral row is added as the real summaries have."""
    df = pd.DataFrame([{"entity": r[0], "group": "real", "elo_mean": r[1], "elo_sd": 0.0, "reps": 6,
                        "refusal_rate": r[2] if len(r) > 2 else 0.0} for r in rows])
    df = pd.concat([df, pd.DataFrame([{"entity": "Quillon Labs", "group": "neutral", "elo_mean": 1372.0,
                                       "elo_sd": 0.0, "reps": 6, "refusal_rate": 0.9}])])
    return df if refusal else df.drop(columns="refusal_rate")


def table(rows):
    return pd.DataFrame([{"key": n.lower(), "name": n, "elo": e, "refusal_rate": r} for n, e, r in rows])


def test_tie_at_either_end_goes_to_the_alphabetically_first():
    t = table([("Alpha", 1700, 0), ("Delta", 1650, 0), ("Bravo", 1650, 0), ("Charlie", 1600, 0),
               ("Golf", 1500, 0), ("Echo", 1500, 0), ("Foxtrot", 1400, 0)])
    liked, disliked = mr.pick(t)
    assert liked == ["alpha", "bravo"]
    assert disliked == ["echo", "foxtrot"]
    notes = mr.ties_and_exclusions(t)
    assert any("top-2" in n and "bravo" in n and "delta" in n for n in notes)
    assert any("bottom-2" in n and "echo" in n and "golf" in n for n in notes)


def test_refusal_over_20_percent_leaves_both_pools_and_the_next_by_rank_is_used():
    t = table([("Alpha", 1700, 0.25), ("Bravo", 1650, 0.2), ("Charlie", 1600, 0), ("Delta", 1550, 0),
               ("Echo", 1500, 0), ("Foxtrot", 1450, 0.5)])
    liked, disliked = mr.pick(t)
    assert liked == ["bravo", "charlie"]  # 0.2 is not above the limit
    assert disliked == ["delta", "echo"]
    assert [n for n in mr.ties_and_exclusions(t) if n.startswith("excluded")] == [
        "excluded (refusal rate 0.250 > 0.2): alpha", "excluded (refusal rate 0.500 > 0.2): foxtrot"]


def test_own_developer_line_backfills_the_third_ranked_lab(monkeypatch):
    monkeypatch.setitem(mr.DEVELOPER, "m", "alpha")
    t = table([("Alpha", 1700, 0), ("Bravo", 1650, 0), ("Charlie", 1600, 0), ("Delta", 1550, 0),
               ("Echo", 1500, 0), ("Foxtrot", 1450, 0)])
    lines = mr.roles_for(t, "m", "lab")
    assert lines["primary"]["liked"] == ["alpha", "bravo"]
    assert lines["without_own_developer"]["liked"] == ["bravo", "charlie"]
    assert lines["without_own_developer"]["disliked"] == lines["primary"]["disliked"] == ["echo", "foxtrot"]
    monkeypatch.setitem(mr.DEVELOPER, "m", "charlie")  # ranked 3rd: neither pair changes
    lines = mr.roles_for(t, "m", "lab")
    assert lines["without_own_developer"] == lines["primary"]
    monkeypatch.setitem(mr.DEVELOPER, "m", "foxtrot")
    with pytest.raises(ValueError, match="disliked"):
        mr.roles_for(t, "m", "lab")


def test_charity_has_only_the_primary_line_and_no_neutrals():
    t = table([("Alpha", 1700, 0), ("Bravo", 1650, 0), ("Charlie", 1600, 0), ("Delta", 1550, 0)])
    assert mr.roles_for(t, "anything", "charity") == {"primary": {"liked": ["alpha", "bravo"],
                                                                  "disliked": ["charlie", "delta"]}}


def test_refusal_rate_from_raw_is_censored_at_the_cap_and_drops_neutral_pairs(tmp_path):
    rows = [("Alpha|Bravo", "ok", 0), ("Alpha|Bravo", "ok", mr.MAX_REFUSALS),  # 31 attempts: missing
            ("Alpha|Quillon Labs", "missing", 100), ("Bravo|Quillon Labs", "ok", 0),
            ("Quillon Labs|Other Neutral", "missing", 100)]
    pd.DataFrame([{"measure": "elo", "kind": "lab", "entities": e, "status": s, "retries": r} for e, s, r in rows]
                 ).to_csv(tmp_path / "raw.csv", index=False)
    rates = mr.raw_refusal_rates([tmp_path], "lab", {"Quillon Labs", "Other Neutral"})
    assert rates["Alpha"] == pytest.approx(2 / 3)
    assert rates["Bravo"] == pytest.approx(1 / 3)
    assert rates["Quillon Labs"] == pytest.approx(1 / 2)
    assert "Other Neutral" not in rates


def test_build_writes_the_fit_curves_shape_with_a_sourced_header(tmp_path, monkeypatch):
    monkeypatch.setitem(mr.DEVELOPER, "fake-model", "alpha")
    folder = tmp_path / "full" / "fake-model"
    folder.mkdir(parents=True)
    path = folder / "summary_elo_reported.csv"
    summary([("Alpha", 1700.0), ("Bravo", 1650.0), ("Charlie", 1640.0), ("Delta", 1600.0),
             ("Echo", 1500.0), ("Foxtrot", 1500.0, 0.3), ("Golf", 1450.0)]).to_csv(path, index=False)
    sources = {"fake-model": ("full/fake-model/summary_elo_reported.csv", []),
               "absent-model": ("full/absent-model/summary_elo_reported.csv", [])}
    text = mr.build("lab", tmp_path, sources, ENTITIES, today="2026-10-27")
    assert hashlib.sha256(path.read_bytes()).hexdigest() in text
    assert "on 2026-10-27" in text and "absent-model: no summary" in text
    assert "excluded (refusal rate 0.300 > 0.2): foxtrot" in text
    roles = yaml.safe_load(text)
    assert list(roles) == ["fake-model"]
    for spec in roles["fake-model"].values():  # what fit_curves.gap_table indexes
        assert set(spec) == {"liked", "disliked", "neutrals"}
        assert spec["neutrals"] == mr.PILOT_NEUTRALS
    assert roles["fake-model"]["primary"] == {"liked": ["alpha", "bravo"], "disliked": ["echo", "golf"],
                                              "neutrals": mr.PILOT_NEUTRALS}
    assert roles["fake-model"]["without_own_developer"]["liked"] == ["bravo", "charlie"]


def test_summary_without_refusal_column_needs_raw_folders(tmp_path):
    path = tmp_path / "s.csv"
    summary([("Alpha", 1700.0)], refusal=False).to_csv(path, index=False)
    with pytest.raises(ValueError, match="no refusal_rate column"):
        mr.load_table(path, [], "lab", ENTITIES)


def test_unknown_entity_name_is_an_error(tmp_path):
    path = tmp_path / "s.csv"
    summary([("Zulu", 1700.0)]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Zulu"):
        mr.load_table(path, [], "lab", ENTITIES)
