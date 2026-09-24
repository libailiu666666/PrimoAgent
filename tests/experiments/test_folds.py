"""Fold construction: strict time order, non-overlap, data-driven coverage."""
from __future__ import annotations

import pandas as pd

from src.experiments.folds import build_annual_expanding_folds, select_dates


def _dates(start: str, end: str):
    return list(pd.bdate_range(start, end))


def test_folds_are_time_ordered_and_non_overlapping():
    dates = _dates("2017-01-02", "2026-12-31")
    folds = build_annual_expanding_folds(dates, 2017, 4, 1, 1)

    assert len(folds) == 5  # test years 2022..2026

    prev_test_end = None
    for f in folds:
        # within-window ordering
        assert f.train_start <= f.train_end
        assert f.calibration_start <= f.calibration_end
        assert f.test_start <= f.test_end
        # strict, non-overlapping time order: train < calibration < test
        assert f.train_end < f.calibration_start
        assert f.calibration_end < f.test_start
        # folds ascend over time and never overlap
        if prev_test_end is not None:
            assert f.test_start > prev_test_end
        prev_test_end = f.test_end


def test_expanding_train_window():
    dates = _dates("2017-01-02", "2026-12-31")
    folds = build_annual_expanding_folds(dates, 2017, 4, 1, 1)
    train_lens = [len(select_dates(dates, f.train_start, f.train_end)) for f in folds]
    assert all(b > a for a, b in zip(train_lens, train_lens[1:]))


def test_first_test_year_matches_scheme():
    dates = _dates("2017-01-02", "2026-12-31")
    folds = build_annual_expanding_folds(dates, 2017, 4, 1, 1)
    # start_year=2017, train=4, calibration=1, test=1 -> first test year 2022
    assert folds[0].test_start.year == 2022
    assert folds[0].train_start.year == 2017
    assert folds[0].calibration_start.year == 2021


def test_partial_final_year_is_flagged():
    # data stops mid-2026 -> the final test window must be flagged partial
    dates = _dates("2017-01-02", "2026-06-30")
    folds = build_annual_expanding_folds(dates, 2017, 4, 1, 1)
    assert folds and folds[-1].is_partial_test is True
    assert all(not f.is_partial_test for f in folds[:-1])


def test_empty_when_insufficient_data():
    assert build_annual_expanding_folds([], 2017, 4, 1, 1) == []
    # a single partial year cannot produce a full 4-year train window
    short = _dates("2017-01-02", "2017-03-31")
    assert build_annual_expanding_folds(short, 2017, 4, 1, 1) == []


def test_start_year_must_have_data():
    dates = _dates("2020-01-02", "2026-12-31")
    # start_year 2017 has no data -> no folds can be built
    assert build_annual_expanding_folds(dates, 2017, 4, 1, 1) == []


def test_select_dates_inclusive():
    dates = _dates("2022-01-03", "2022-12-30")
    sub = select_dates(dates, "2022-06-01", "2022-06-30")
    assert sub[0] == pd.Timestamp("2022-06-01")
    assert sub[-1] == pd.Timestamp("2022-06-30")
