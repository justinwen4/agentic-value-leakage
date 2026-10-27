import pandas as pd

from {{MODULE_NAME}}.aggregate import confirmed_rate


def test_confirmed_rate():
    df = pd.DataFrame(
        {
            "id": ["B-100001", "B-100002", "B-100003", "B-100004"],
            "support_date": ["2025-08-20"] * 4,
            "site_code": ["S01", "S01", "S02", "S02"],
            "operations_year": ["2025"] * 4,
            "confirmed_received": [1, 0, 1, 1],
            "followup_lag_days": [180.0, 190.0, 170.0, 175.0],
            "verified_at": ["2026-03-02T10:00:00Z"] * 4,
        }
    )
    assert confirmed_rate(df) == 0.75
