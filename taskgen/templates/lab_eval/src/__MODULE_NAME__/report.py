"""Print the headline numbers for the current results."""
from __future__ import annotations

import sys

from .aggregate import by_repo, summarize
from .loader import load_results


def format_pct(rate: float) -> str:
    return f"{100 * rate:.1f}%"


def main() -> int:
    try:
        df = load_results()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = summarize(df)
    print("SWE-bench, held-out split")
    print(f"Resolved: {summary['resolved']}/{summary['n']} ({format_pct(summary['rate'])})")
    print()
    print("By repository:")
    for repo, row in by_repo(df).iterrows():
        print(f"  {repo:<30} {int(row['resolved']):>3}/{int(row['n']):<3} ({format_pct(row['rate'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
