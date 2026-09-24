"""get_fundamentals read-cache regression tests (Gate 2 performance fix).

The cache must be a pure memoization of the parsed facts frame: it may never
change the PIT answer, leak future disclosures, or skip the ``as_of`` filter.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data import historical_store as hs
from src.data.historical_store import HistoricalDataStore


@pytest.fixture
def store():
    return HistoricalDataStore("historical")


@pytest.fixture(autouse=True)
def _clear_cache():
    hs._FUNDAMENTALS_CACHE.clear()
    yield
    hs._FUNDAMENTALS_CACHE.clear()


def test_cache_avoids_repeated_parquet_reads(store, monkeypatch):
    """A second query for the same symbol must not re-read the parquet files."""
    calls = []
    orig = hs.pd.read_parquet

    def counting(path, *args, **kwargs):
        calls.append(str(path))
        return orig(path, *args, **kwargs)

    monkeypatch.setattr(hs.pd, "read_parquet", counting)

    as_of = "2024-06-01T00:00:00Z"
    store.get_fundamentals("AAPL", as_of)
    n_first = len(calls)
    store.get_fundamentals("AAPL", as_of)
    n_second = len(calls)

    assert n_first >= 2  # facts + submissions on a cold load
    assert n_second == n_first  # cache hit reads nothing new


def test_cache_different_as_of_pit(store):
    """Different as_of over the same cached frame yield different PIT results."""
    early = store.get_fundamentals("AAPL", "2018-06-01T00:00:00Z")
    late = store.get_fundamentals("AAPL", "2024-06-01T00:00:00Z")

    assert not early.empty and not late.empty
    assert (early["known_at"] <= pd.Timestamp("2018-06-01T00:00:00Z")).all()
    assert (late["known_at"] <= pd.Timestamp("2024-06-01T00:00:00Z")).all()
    assert early["known_at"].max() < late["known_at"].max()


def test_cache_no_future_restatement_leak(store):
    """A warm cache hit at an early as_of must NOT see a later restatement."""
    def ap(df):
        s = df[
            (df["concept"] == "AccountsPayableCurrent")
            & (df["unit"] == "USD")
            & (df["end"] == "2017-09-30")
        ]
        return float(s["val"].iloc[0]) if len(s) else None

    before = store.get_fundamentals("AAPL", "2018-06-01T00:00:00Z")
    after = store.get_fundamentals("AAPL", "2018-11-06T00:00:00Z")
    before_again = store.get_fundamentals("AAPL", "2018-06-01T00:00:00Z")  # cache hit

    assert ap(before) == 49049000000.0
    assert ap(after) == 44242000000.0
    assert ap(before_again) == 49049000000.0  # no restatement leaked through the cache


def test_cache_equivalent_to_uncached(store, monkeypatch):
    """Cached and forced-miss (re-parsed) queries must return identical frames."""
    as_offs = ["2018-06-01T00:00:00Z", "2020-03-15T00:00:00Z", "2024-06-01T00:00:00Z"]

    hs._FUNDAMENTALS_CACHE.clear()
    warm = {a: store.get_fundamentals("AAPL", a) for a in as_offs}

    class _Miss(dict):
        def get(self, key, default=None):
            return None

    monkeypatch.setattr(hs, "_FUNDAMENTALS_CACHE", _Miss())
    cold = {a: store.get_fundamentals("AAPL", a) for a in as_offs}

    for a in as_offs:
        assert warm[a].equals(cold[a])
