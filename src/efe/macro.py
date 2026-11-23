"""Macro series (USD/EGP average rate, CPI) from data/macro/egypt_macro.csv, with their source.

Refresh with scripts/fetch_macro.py. A missing year returns None; nothing is interpolated.
"""
import csv
from dataclasses import dataclass
from functools import lru_cache

from efe import config

MACRO_CSV = config.DATA / "macro" / "egypt_macro.csv"

# Event dates from docs/03 section 3. A fiscal year is a devaluation year if it contains one.
DEVALUATIONS = [
    ("2016-11-03", "Float under IMF programme"),
    ("2022-03-21", "Devaluation"),
    ("2022-10-27", "Move to flexible regime"),
    ("2023-01-04", "Further depreciation (early January 2023)"),
    ("2024-03-06", "Float with 6-point rate hike"),
]


@dataclass(frozen=True)
class Point:
    series: str
    year: int
    value: float
    source: str

    @property
    def ref(self) -> str:
        return f"{self.series} {self.year} = {self.value:,.4g} ({self.source})"


@lru_cache(maxsize=1)
def _load() -> dict[tuple[str, int], Point]:
    if not MACRO_CSV.exists():
        return {}
    with open(MACRO_CSV, newline="", encoding="utf-8") as fh:
        return {(r["series"], int(r["year"])): Point(r["series"], int(r["year"]), float(r["value"]),
                                                    f"{r['source']}, retrieved {r['retrieved_on']}")
                for r in csv.DictReader(fh)}


def get(series: str, year: int) -> Point | None:
    return _load().get((series, year))


def devaluation_years(period_end: str) -> dict[int, list[str]]:
    """Fiscal years (labelled by the year they end in) that contain a devaluation event."""
    month_day = period_end[5:]
    out: dict[int, list[str]] = {}
    for date, name in DEVALUATIONS:
        fy = int(date[:4]) + (1 if date[5:] > month_day else 0)
        out.setdefault(fy, []).append(f"{name} ({date})")
    return out
