"""Print the headline numbers for the current cohort."""
from __future__ import annotations

import sys

from .aggregate import by_site, summarize
from .loader import load_participants


def format_pct(rate: float) -> str:
    return f"{100 * rate:.1f}%"


def main() -> int:
    try:
        df = load_participants()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = summarize(df)
    print("2025 cohort, 6-month follow-up")
    print(f"Completed: {summary['completed']}/{summary['n']} ({format_pct(summary['rate'])})")
    print()
    print("By site:")
    for site, row in by_site(df).iterrows():
        print(f"  {site:<6} {int(row['completed']):>4}/{int(row['n']):<4} ({format_pct(row['rate'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
