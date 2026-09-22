"""Timezone-boundary and causal-invariant tests (PIT_FROZEN_SPEC section 1 & 3.3)."""
from datetime import datetime

import pandas as pd
import pytest

from src.data.contracts import (
    PITTimeError,
    close_time_utc,
    ensure_utc,
    open_time_utc,
    validate_causal_order,
)


def test_close_time_utc_dst_and_standard():
    # US equities close 16:00 America/New_York -> 20:00 UTC (DST) / 21:00 UTC (std).
    assert close_time_utc("2024-07-01") == pd.Timestamp("2024-07-01T20:00:00Z")
    assert close_time_utc("2024-01-02") == pd.Timestamp("2024-01-02T21:00:00Z")


def test_open_time_utc():
    assert open_time_utc("2024-07-01") == pd.Timestamp("2024-07-01T13:30:00Z")
    assert open_time_utc("2024-01-02") == pd.Timestamp("2024-01-02T14:30:00Z")


def test_ensure_utc_rejects_naive():
    with pytest.raises(PITTimeError):
        ensure_utc("2024-01-02")  # naive date string
    with pytest.raises(PITTimeError):
        ensure_utc(datetime(2024, 1, 2, 16, 0))  # naive local datetime


def test_ensure_utc_normalizes_tz_aware():
    assert ensure_utc("2024-01-02T21:00:00Z") == pd.Timestamp("2024-01-02T21:00:00Z")
    # +00:00 and explicit UTC both normalize to UTC
    assert ensure_utc("2024-01-02T21:00:00+00:00") == pd.Timestamp(
        "2024-01-02T21:00:00Z"
    )


def test_validate_causal_order_ok():
    # feature_as_of <= signal_generated_at < execution_at
    validate_causal_order(
        "2024-01-02T21:00:00Z", "2024-01-02T21:00:00Z", "2024-01-03T14:30:00Z"
    )


def test_validate_causal_order_rejects_lookahead():
    # feature_as_of AFTER signal_generated_at is lookahead
    with pytest.raises(PITTimeError):
        validate_causal_order(
            "2024-01-03T21:00:00Z", "2024-01-02T21:00:00Z", "2024-01-03T14:30:00Z"
        )


def test_validate_causal_order_rejects_execution_before_signal():
    with pytest.raises(PITTimeError):
        validate_causal_order(
            "2024-01-02T21:00:00Z", "2024-01-03T14:30:00Z", "2024-01-03T14:00:00Z"
        )


def test_validate_causal_order_rejects_equal_execution_and_signal():
    # right side is strict '<'
    with pytest.raises(PITTimeError):
        validate_causal_order(
            "2024-01-02T21:00:00Z", "2024-01-03T14:30:00Z", "2024-01-03T14:30:00Z"
        )
