import pandas as pd

from {{MODULE_NAME}}.loader import DATA_DIR, REQUIRED_COLUMNS, load_participants


def test_required_columns():
    df = load_participants()
    for column in REQUIRED_COLUMNS:
        assert column in df.columns


def test_ids_unique():
    df = load_participants()
    assert df["id"].is_unique


def test_rerun_outcomes_applied():
    loaded = load_participants().set_index("id")
    rerun = pd.read_csv(DATA_DIR / "participants_recheck.csv").set_index("id")
    stale = rerun.index[
        loaded.loc[rerun.index, "completed_followup"].to_numpy() != rerun["completed_followup"].to_numpy()
    ]
    assert len(stale) == 0, f"{len(stale)} rerun ids do not carry their rerun outcome"
