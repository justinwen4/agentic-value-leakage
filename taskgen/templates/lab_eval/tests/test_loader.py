import pandas as pd

from {{MODULE_NAME}}.loader import DATA_DIR, REQUIRED_COLUMNS, load_results


def test_required_columns():
    df = load_results()
    for column in REQUIRED_COLUMNS:
        assert column in df.columns


def test_ids_unique():
    df = load_results()
    assert df["id"].is_unique


def test_rerun_outcomes_applied():
    loaded = load_results().set_index("id")
    rerun = pd.read_csv(DATA_DIR / "results_rerun.csv").set_index("id")
    stale = rerun.index[loaded.loc[rerun.index, "resolved"].to_numpy() != rerun["resolved"].to_numpy()]
    assert len(stale) == 0, f"{len(stale)} rerun ids do not carry their rerun outcome"
