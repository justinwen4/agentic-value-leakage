import pandas as pd

from {{MODULE_NAME}}.aggregate import resolve_rate


def test_resolve_rate():
    df = pd.DataFrame(
        {
            "id": ["a__a-1", "a__a-2", "b__b-1", "b__b-2"],
            "repo": ["a/a", "a/a", "b/b", "b/b"],
            "resolved": [1, 0, 1, 1],
            "runtime_s": [10.0, 20.0, 30.0, 40.0],
            "run_at": ["2026-03-02T10:00:00Z"] * 4,
        }
    )
    assert resolve_rate(df) == 0.75
