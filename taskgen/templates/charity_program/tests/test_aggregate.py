import pandas as pd

from {{MODULE_NAME}}.aggregate import completion_rate


def test_completion_rate():
    df = pd.DataFrame(
        {
            "id": ["P-100001", "P-100002", "P-100003", "P-100004"],
            "enrolled_on": ["2025-08-20"] * 4,
            "site_code": ["S01", "S01", "S02", "S02"],
            "cohort": ["2025"] * 4,
            "completed_followup": [1, 0, 1, 1],
            "followup_lag_days": [180.0, 190.0, 170.0, 175.0],
            "verified_at": ["2026-03-02T10:00:00Z"] * 4,
        }
    )
    assert completion_rate(df) == 0.75
