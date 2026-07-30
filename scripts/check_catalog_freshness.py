"""Fail loudly when time-sensitive catalog data has aged out.

Why this exists
---------------
`rotating_categories` rows carry an `effective_until`. `CardService` filters on
`effective_from <= today <= effective_until`, so once a quarter lapses the
query simply returns nothing: no exception, no log line, no failing test — a
lesser card just quietly wins the recommendation. Between 2026-07-01 and
2026-07-30 every rotating 5x bonus in the app returned the card's base rate
for exactly this reason, on the feature the product is named for.

The lesson is that expiring data needs an expiry *alarm*, not an expiry field.
This script is that alarm.

It reads the seed file rather than the database on purpose. The seed file is
the source of truth that gets committed and reviewed; a database can be stale
for reasons that are nobody's fault (fresh checkout, wiped volume), and we do
not want those to look like the same problem. It also means this runs in CI
with no Postgres.

Deliberately NOT a pytest case. PR #98 made the card fixtures time-invariant on
purpose, because a date-dependent test turns every unrelated PR red and trains
people to ignore it. This is a standalone check you can wire to a cron or a
scheduled CI job, where a red result means "go get the new categories" and
nothing else is blocked in the meantime.

Exit codes:
    0 — the newest quarter is effective and has more than WARN_WINDOW_DAYS left
    1 — expired, or expiring inside the warning window (action needed)

Usage:
    python3 scripts/check_catalog_freshness.py
    python3 scripts/check_catalog_freshness.py --warn-days 30
"""

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Lead time before expiry at which we start failing. Two weeks is enough to
# find the issuer's announcement, confirm it against their own page, and land
# a seed PR without anyone working a weekend.
WARN_WINDOW_DAYS = 14


def check_rotating_categories(today: date, warn_days: int) -> tuple[bool, list[str]]:
    """Return (ok, lines) describing rotating-category freshness."""
    from seed_rotating_categories import ROTATING_CATEGORIES

    lines: list[str] = []

    # Group by card so one card lapsing is not masked by another being current.
    by_card: dict[tuple[str, str], list[dict]] = {}
    for row in ROTATING_CATEGORIES:
        by_card.setdefault((row["card_issuer"], row["card_product"]), []).append(row)

    ok = True
    for (issuer, product), rows in sorted(by_card.items()):
        newest = max(rows, key=lambda r: r["effective_until"])
        expires = newest["effective_until"]
        days_left = (expires - today).days
        label = f"{issuer}/{product}"

        if days_left < 0:
            ok = False
            lines.append(
                f"  ✗ {label}: newest quarter {newest['quarter']} EXPIRED "
                f"{-days_left} day(s) ago ({expires}). Every rotating bonus on "
                f"this card is silently returning the base rate right now."
            )
        elif days_left <= warn_days:
            ok = False
            lines.append(
                f"  ✗ {label}: {newest['quarter']} expires in {days_left} day(s) "
                f"({expires}). Seed the next quarter before then."
            )
        else:
            lines.append(
                f"  ✓ {label}: {newest['quarter']} effective through {expires} "
                f"({days_left} days left)"
            )

    return ok, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--warn-days",
        type=int,
        default=WARN_WINDOW_DAYS,
        help=f"days before expiry to start failing (default {WARN_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="override today's date (ISO format) — for testing this script",
    )
    args = parser.parse_args()

    today = args.today or date.today()
    print(f"Catalog freshness as of {today}\n")

    print("rotating_categories (scripts/seed_rotating_categories.py):")
    ok, lines = check_rotating_categories(today, args.warn_days)
    for line in lines:
        print(line)

    if not ok:
        print(
            "\nNext step: get the upcoming quarter's category lists from the "
            "issuers' own pages — not aggregators — add them to "
            "ROTATING_CATEGORIES, and re-run "
            "`python3 scripts/seed_rotating_categories.py`."
        )
        return 1

    print("\n✓ catalog data is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
