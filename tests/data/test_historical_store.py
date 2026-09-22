"""HistoricalDataStore PIT tests over the real local dataset (PIT_FROZEN_SPEC 2 & 7.2)."""
import pandas as pd
import pytest

from src.data.historical_store import HistoricalDataStore, snapshot_hash


@pytest.fixture
def store():
    return HistoricalDataStore("historical")


# ---------------------------------------------------------------- market window

def test_market_window_no_lookahead(store):
    as_of = pd.Timestamp("2024-01-05T21:00:00Z")
    mw = store.get_market_window("AAPL", as_of, lookback_days=30)
    assert not mw.empty
    assert (mw["known_at"] <= as_of).all()


def test_market_window_intraday_excludes_t_close(store):
    # as_of is intraday (before the 21:00 UTC close); the T=2024-01-05 close bar
    # must NOT be returned, only T-1 and earlier.
    as_of = pd.Timestamp("2024-01-05T18:00:00Z")
    mw = store.get_market_window("AAPL", as_of, lookback_days=10)
    assert not mw.empty
    assert mw["date"].max() <= pd.Timestamp("2024-01-04")


def test_market_window_non_trading_day_no_bar(store):
    # Saturday 2024-01-06: no bar may be dated that day.
    mw = store.get_market_window("AAPL", "2024-01-06T21:00:00Z", lookback_days=5)
    assert not (mw["date"].dt.strftime("%Y-%m-%d") == "2024-01-06").any()


# ------------------------------------------------------------------------ news

def test_news_future_excluded(store):
    as_of = pd.Timestamp("2024-06-30T00:00:00Z")
    ne = store.get_news_events("AAPL", as_of, lookback_days=365)
    assert not ne.empty
    assert (ne["available_at"] <= as_of).all()


# ---------------------------------------------------------------- fundamentals

def test_fundamentals_no_lookahead(store):
    as_of = pd.Timestamp("2018-06-01T00:00:00Z")
    ff = store.get_fundamentals("AAPL", as_of)
    assert not ff.empty
    assert (ff["known_at"] <= as_of).all()


def test_fundamentals_restatement_version_selection(store):
    """AAPL AccountsPayableCurrent/USD/end=2017-09-30 was restated 2018-11-05.

    Before the restatement the historical query must return the original value;
    after it, the restated value. Never backfill the future restatement.
    """
    def ap(df):
        s = df[
            (df["concept"] == "AccountsPayableCurrent")
            & (df["unit"] == "USD")
            & (df["end"] == "2017-09-30")
        ]
        return float(s["val"].iloc[0]) if len(s) else None

    before = store.get_fundamentals("AAPL", "2018-06-01T00:00:00Z")
    after = store.get_fundamentals("AAPL", "2018-11-06T00:00:00Z")
    assert ap(before) == 49049000000.0
    assert ap(after) == 44242000000.0


# -------------------------------------------------------------------- calendar

def test_trading_calendar_weekend_and_holiday(store):
    cal = store.get_trading_calendar("2024-01-14", "2024-01-16")
    d = dict(zip(cal["date"].astype(str), cal["is_trading_day"]))
    assert not d["2024-01-14"]  # Sunday
    assert not d["2024-01-15"]  # MLK holiday
    assert d["2024-01-16"]  # Tuesday
    assert cal.attrs.get("calendar_version")


def test_trading_calendar_special_closure(store):
    # 2025-01-09 (President Carter mourning day) is a temporary full closure that
    # may be absent from a standard holiday feed; the frozen supplement must catch it.
    cal = store.get_trading_calendar("2025-01-08", "2025-01-10")
    d = dict(zip(cal["date"].astype(str), cal["is_trading_day"]))
    r = dict(zip(cal["date"].astype(str), cal["holiday"]))
    assert d["2025-01-08"]  # Wednesday (trading)
    assert not d["2025-01-09"]  # special closure
    assert d["2025-01-10"]  # Friday (trading)
    assert "mourning" in r["2025-01-09"].lower() or "carter" in r["2025-01-09"].lower()


# -------------------------------------------------------------- determinism

def test_snapshot_hash_deterministic(store):
    a = store.get_market_window("AAPL", "2024-01-05T21:00:00Z", lookback_days=10)
    b = store.get_market_window("AAPL", "2024-01-05T21:00:00Z", lookback_days=10)
    assert snapshot_hash(a) == snapshot_hash(b)
    # row-order independence
    assert snapshot_hash(a.iloc[::-1].reset_index(drop=True)) == snapshot_hash(a)
