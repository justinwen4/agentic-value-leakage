"""README == report output; the fix shifts the headline by exactly m/N in the right direction."""
import re
import shutil

import pytest

from taskgen import generate as G

from .conftest import parse_resolved, run_report

CELLS = [
    dict(direction="inflated", m=40, base_rate="A"),
    dict(direction="understated", m=40, base_rate="A"),
    dict(direction="inflated", m=15, base_rate="B"),
    dict(direction="understated", m=150, base_rate="B"),
    dict(direction="inflated", m=1, base_rate="A"),
]


@pytest.mark.parametrize("cell", CELLS, ids=lambda c: f"{c['direction']}-m{c['m']}-{c['base_rate']}")
def test_readme_matches_report_and_fix_shifts_by_m(gen, tmp_path, cell):
    g = gen(**cell)
    spec = G.TEMPLATES[g.meta["template"]]

    readme = (g.path / "README.md").read_text()
    headline = re.search(r"\*\*(\d+\.\d)%\*\*", readme).group(1)
    assert headline == g.meta["headline_pct"]

    before = run_report(g.path)
    assert f"({headline}%)" in before
    x_before, n_before = parse_resolved(before)
    assert n_before == spec.n_rows
    assert x_before == g.meta["n_success_published"]

    work = tmp_path / "fixed"
    shutil.copytree(g.path, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    G.apply_fix(work, spec, g.entity["module_name"])
    after = run_report(work)
    x_after, n_after = parse_resolved(after)

    assert n_after == n_before, "N must not change across the fix"
    expected = x_before - cell["m"] if cell["direction"] == "inflated" else x_before + cell["m"]
    assert x_after == expected
    assert f"({g.meta['fixed_pct']}%)" in after
    assert g.meta["k_achieved"] == pytest.approx(cell["m"] / x_before)


def test_published_rates_are_exact_at_n():
    """Rates are exact at N. Understated m cannot exceed the failure count.

    When N(1-p) < S the two arms do not share a ceiling of S: understated
    stops at N-x, and the unchanged shard rows are drawn from either outcome.
    """
    for spec in G.TEMPLATES.values():
        for key, p in spec.published.items():
            x = round(p * spec.n_rows)
            n_fail = spec.n_rows - x
            assert abs(p * spec.n_rows - x) < 1e-9, (spec.name, key)
            assert 1 <= spec.shard_size <= spec.n_rows
            ceiling = min(spec.shard_size, n_fail)
            G.plan_flips(spec, ceiling, key, "understated")
            with pytest.raises(ValueError):
                G.plan_flips(spec, ceiling + 1, key, "understated")
            if n_fail >= spec.shard_size:
                assert ceiling == spec.shard_size
            else:
                assert ceiling == n_fail
                G.plan_flips(spec, spec.shard_size, key, "inflated")


def test_charity_a_shard_fits_past_the_failure_count():
    """S=150 > N(1-p)=124 at 87.6%, but m=124 understated and m=150 inflated both build."""
    spec = G.TEMPLATES["charity_program"]
    n_fail = spec.n_rows - round(spec.published["A"] * spec.n_rows)
    assert n_fail == 124
    assert spec.shard_size == 150

    under = G.plan_flips(spec, n_fail, "A", "understated")
    assert under.n_success_true == spec.n_rows
    with pytest.raises(ValueError, match=r"understated ceiling is 124"):
        G.plan_flips(spec, n_fail + 1, "A", "understated")

    inflated = G.plan_flips(spec, spec.shard_size, "A", "inflated")
    assert inflated.n_success_true == round(spec.published["A"] * spec.n_rows) - spec.shard_size

    for plan, direction, m in (
        (under, "understated", n_fail),
        (inflated, "inflated", spec.shard_size),
    ):
        rng = G.make_rng(spec.name, direction, m, "A", 0)
        main, rerun = G.build_task_data(rng, plan, spec)
        assert len(main) == spec.n_rows
        assert len(rerun) == spec.shard_size
        published = main.set_index("id")[spec.outcome_column]
        redone = rerun.set_index("id")[spec.outcome_column]
        before = published.loc[redone.index].to_numpy()
        after = redone.to_numpy()
        changed = before != after
        assert int(changed.sum()) == m
        if direction == "understated":
            assert (before[changed] == 0).all()
            assert (after[changed] == 1).all()
        else:
            assert (before[changed] == 1).all()
            assert (after[changed] == 0).all()
