import pandas as pd

from {{MODULE_NAME}}.loader import DATA_DIR, REQUIRED_COLUMNS, load_beneficiaries


def test_required_columns():
    df = load_beneficiaries()
    for column in REQUIRED_COLUMNS:
        assert column in df.columns


def test_ids_unique():
    df = load_beneficiaries()
    assert df["id"].is_unique


def test_rerun_outcomes_applied():
    loaded = load_beneficiaries().set_index("id")
    rerun = pd.read_csv(DATA_DIR / "beneficiaries_recheck.csv").set_index("id")
    stale = rerun.index[
        loaded.loc[rerun.index, "confirmed_received"].to_numpy() != rerun["confirmed_received"].to_numpy()
    ]
    assert len(stale) == 0, f"{len(stale)} rerun ids do not carry their rerun outcome"
