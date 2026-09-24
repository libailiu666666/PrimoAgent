"""Data-driven walk-forward fold construction (annual expanding window).

Folds are derived from the actual common trading-date coverage of the
universe — nothing is hardcoded to a date range that may not exist. The
windows are strictly time-ordered:

    train  <  calibration  <  test        (non-overlapping, never shuffled)

For an annual expanding scheme with ``train_years=T``, ``calibration_years=C``
and ``test_years=S``, the fold whose test year is ``Y`` covers:

    train         = [start_year, Y - C - S]
    calibration   = [Y - S, Y - 1]
    test          = [Y, Y]

and the first test year is ``start_year + T + C + S - 1`` (so the shortest
train window is exactly ``train_years`` long, then expands by one year each
subsequent fold).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import pandas as pd


@dataclass(frozen=True)
class Fold:
    """One walk-forward split (all bounds are inclusive calendar years)."""

    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    calibration_start: pd.Timestamp
    calibration_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    is_partial_test: bool = False

    def as_dict(self) -> dict:
        return {
            "fold": self.index,
            "train_start": self.train_start.date().isoformat(),
            "train_end": self.train_end.date().isoformat(),
            "calibration_start": self.calibration_start.date().isoformat(),
            "calibration_end": self.calibration_end.date().isoformat(),
            "test_start": self.test_start.date().isoformat(),
            "test_end": self.test_end.date().isoformat(),
            "is_partial_test": self.is_partial_test,
        }


def _first_last_by_year(dates: Sequence[pd.Timestamp]) -> dict:
    """Map year -> (first trading date, last trading date) in that year."""
    out: dict = {}
    for d in dates:
        y = int(d.year)
        if y not in out:
            out[y] = (d, d)
        else:
            first, last = out[y]
            out[y] = (min(first, d), max(last, d))
    return out


def build_annual_expanding_folds(
    common_dates: Sequence[pd.Timestamp],
    start_year: int,
    train_years: int,
    calibration_years: int,
    test_years: int,
) -> List[Fold]:
    """Build expanding annual folds from the observed common trading dates.

    ``common_dates`` must be sorted ascending. Folds are only produced for test
    years that actually have data; a final partial test year is kept but flagged
    via ``is_partial_test``.
    """
    if train_years < 1 or calibration_years < 1 or test_years < 1:
        raise ValueError("train/calibration/test years must be >= 1")

    dates = sorted(pd.Timestamp(d).normalize() for d in common_dates)
    if not dates:
        return []

    by_year = _first_last_by_year(dates)
    first_data_year = int(dates[0].year)
    last_data_year = int(dates[-1].year)

    # First test year gives a train window of exactly ``train_years``.
    first_test_year = start_year + train_years + calibration_years + test_years - 1
    if first_test_year < first_data_year:
        first_test_year = first_data_year

    folds: List[Fold] = []
    for y in range(first_test_year, last_data_year + 1):
        cal_year = y - test_years
        train_end_year = y - calibration_years - test_years

        if cal_year not in by_year or train_end_year not in by_year:
            continue
        if y not in by_year:
            continue
        if start_year not in by_year:
            continue

        train_start = by_year[start_year][0]
        train_end = by_year[train_end_year][1]
        cal_start = by_year[cal_year][0]
        cal_end = by_year[cal_year][1]
        test_start = by_year[y][0]
        test_end = by_year[y][1]

        # A test window is partial when the data does not extend through
        # December of its year (e.g. the final year, when data stops mid-year).
        is_partial = pd.Timestamp(test_end).month < 12

        folds.append(
            Fold(
                index=len(folds),
                train_start=train_start,
                train_end=train_end,
                calibration_start=cal_start,
                calibration_end=cal_end,
                test_start=test_start,
                test_end=test_end,
                is_partial_test=is_partial,
            )
        )
    return folds


def select_dates(dates: Sequence[pd.Timestamp], start, end) -> List[pd.Timestamp]:
    """Return the trading dates in ``[start, end]`` (inclusive)."""
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    return [d for d in dates if s <= d <= e]
