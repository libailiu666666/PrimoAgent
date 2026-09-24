"""Point-in-time historical data store (PIT_FROZEN_SPEC v1.1 section 2).

The four frozen query interfaces, all backed by local parquet files only:

    get_market_window(symbol, as_of, lookback_days)
    get_news_events(symbol, as_of, lookback_days)
    get_fundamentals(symbol, as_of)
    get_trading_calendar(start, end)

Every ``as_of`` is bound to ``feature_as_of`` and every interface returns only
records with ``known_at <= feature_as_of``. In historical mode the store
activates the network guard so no realtime endpoint can be reached.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pandas as pd

from ..config.paths import (
    FINNHUB_DATA_DIR,
    NEWS_DATA_DIR,
    SEC_DATA_DIR,
    TIINGO_CACHE_DIR,
)
from . import historical_mode
from .contracts import DEFAULT_EXCHANGE, close_time_utc, ensure_utc

NEWS_FILE = NEWS_DATA_DIR / "news_events_primary.parquet"
HOLIDAYS_FILE = FINNHUB_DATA_DIR / "market_holidays.parquet"

# Special (temporary) full market closures within the experiment range
# (2025-01-01 .. 2026-04-01) that a standard "announced holidays" feed may miss.
# PIT_FROZEN_SPEC 5.3; promoted for the observed 2025-01-09 gap. Frozen here so
# the backtest calendar is deterministic. Early-close half-sessions
# (e.g. 2025-07-03, 2025-11-28, 2025-12-24) remain a documented P1 limitation.
SPECIAL_CLOSURES: dict[str, str] = {
    "2025-01-09": "National day of mourning (President Carter) - full closure",
}


def snapshot_hash(df: pd.DataFrame) -> str:
    """Deterministic content hash of a DataFrame (row/column order independent)."""
    cols = sorted(df.columns)
    sub = df[cols].copy()
    key = sub.apply(lambda r: "|".join(map(str, r.values)), axis=1)
    sub = sub.iloc[key.argsort(kind="stable")].reset_index(drop=True)
    payload = sub.to_json(orient="values", date_format="iso")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_acceptance_utc(raw) -> pd.Timestamp:
    """Parse an EDGAR acceptance_datetime into tz-aware UTC.

    EDGAR emits US Eastern without a marker, or ISO-8601 ending in Z/+00:00.
    """
    s = str(raw).strip().replace("T", " ")
    if s.endswith("Z"):
        return pd.Timestamp(s.replace("Z", "") + "+00:00").tz_convert("UTC")
    if "+00:00" in s or "-00:00" in s:
        return pd.Timestamp(s).tz_convert("UTC")
    return pd.Timestamp(s).tz_localize("America/New_York").tz_convert("UTC")


# Per-symbol read cache for ``get_fundamentals``. Stores the parsed facts frame
# (with ``known_at`` / ``is_date_only`` precomputed) keyed by symbol; the
# ``as_of`` disclosure-time filter is ALWAYS applied on top of the cached frame,
# so the cache never bypasses the PIT cut. The signature (resolved path +
# mtime_ns + size) invalidates the entry when the underlying parquet changes.
_FUNDAMENTALS_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}


def _fundamentals_signature(facts_path, subs_path) -> str:
    parts = []
    for p in (facts_path, subs_path):
        try:
            st = p.stat()
            parts.append(f"{p.resolve()}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{p.resolve()}:missing")
    return "|".join(parts)


class HistoricalDataStore:
    """PIT-safe read-only store over local ``output/`` data."""

    def __init__(self, mode: str = "historical") -> None:
        if mode not in ("historical", "live"):
            raise ValueError("mode must be 'historical' or 'live'")
        self.mode = mode
        if mode == "historical":
            historical_mode.enable_historical_mode()

    # ------------------------------------------------------------------ calendar

    def get_trading_calendar(self, start, end) -> pd.DataFrame:
        """Return trading/non-trading days in [start, end] with a source fingerprint.

        A day is non-trading if it is a weekend or a US exchange holiday from the
        locally stored ``market_holidays.parquet``. The returned frame carries
        ``calendar_version`` (a sha256 of the holiday set) as ``df.attrs``.
        """
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)

        holidays: set[str] = set()
        if HOLIDAYS_FILE.exists():
            h = pd.read_parquet(HOLIDAYS_FILE)
            h = h[h["exchange"].astype(str).str.upper() == "US"]
            holidays = set(h["date"].astype(str).unique())

        dates = pd.date_range(start.date(), end.date(), freq="D")
        rows = []
        for d in dates:
            ds = d.strftime("%Y-%m-%d")
            if d.weekday() >= 5:
                is_trading, reason = False, "weekend"
            elif ds in SPECIAL_CLOSURES:
                is_trading, reason = False, SPECIAL_CLOSURES[ds]
            elif ds in holidays:
                is_trading, reason = False, ds
            else:
                is_trading, reason = True, ""
            rows.append(
                {"date": d.date(), "is_trading_day": bool(is_trading), "holiday": reason}
            )
        out = pd.DataFrame(rows)
        out.attrs["calendar_version"] = hashlib.sha256(
            "|".join(sorted(holidays | set(SPECIAL_CLOSURES))).encode("utf-8")
        ).hexdigest()
        return out

    def _trading_days(self, start, end) -> set:
        cal = self.get_trading_calendar(start, end)
        return set(cal.loc[cal["is_trading_day"], "date"].astype(str))

    # ------------------------------------------------------------------- market

    def get_market_window(self, symbol: str, as_of, lookback_days: int = 30) -> pd.DataFrame:
        """Daily bars for ``symbol`` knowable at ``as_of``.

        - ``as_of`` is bound to ``feature_as_of`` (tz-aware UTC enforced).
        - A bar dated T is included only if ``close_time_utc(T) <= as_of``.
        - ``lookback_days`` is natural days; the bar count conversion uses
          ``get_trading_calendar`` rather than raw calendar subtraction.
        """
        a = ensure_utc(as_of)
        symbol = symbol.upper()

        path = TIINGO_CACHE_DIR / f"{symbol}_ohlcv.parquet"
        if not path.exists():
            return pd.DataFrame()

        df = pd.read_parquet(path)
        if df.empty:
            return df

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["date"] = df["date"].dt.tz_localize(None)
        df["known_at"] = df["date"].map(lambda d: close_time_utc(d, DEFAULT_EXCHANGE))

        # T-bar visibility: close_time_utc(T) <= feature_as_of
        df = df[df["known_at"] <= a]

        if lookback_days is not None:
            window_start = (a - timedelta(days=lookback_days)).date()
            trading_days = self._trading_days(window_start, a.date())
            df = df[df["date"].dt.strftime("%Y-%m-%d").isin(trading_days)]

        return df.sort_values("date").reset_index(drop=True)

    # --------------------------------------------------------------------- news

    def get_news_events(self, symbol: str, as_of, lookback_days=None) -> pd.DataFrame:
        """News/filing events knowable at ``as_of``.

        Filter key is ``known_at`` = ``available_at`` (never ``published_at``).
        """
        a = ensure_utc(as_of)
        symbol = symbol.upper()

        if not NEWS_FILE.exists():
            return pd.DataFrame()

        events = pd.read_parquet(NEWS_FILE)
        if events.empty:
            return events

        m = (events["ticker"] == symbol) & (events["available_at"] <= a)
        if lookback_days is not None:
            m &= events["available_at"] > (a - timedelta(days=lookback_days))
        return events[m].sort_values("available_at").reset_index(drop=True)

    # ------------------------------------------------------------- fundamentals

    def get_fundamentals(self, symbol: str, as_of) -> pd.DataFrame:
        """SEC XBRL facts knowable at ``as_of`` with as-filed version selection.

        Two frozen steps:
          1. disclosure-time filter: ``known_at <= as_of`` (``known_at`` =
             acceptance_datetime, or ``filed`` EOD when acceptance is unknown;
             a same-day date-only filing is conservatively excluded).
          2. version selection: within the surviving subset, pick the latest
             ``known_at`` per ``(concept, unit, end)``.
        """
        a = ensure_utc(as_of)
        symbol = symbol.upper()

        facts_path = SEC_DATA_DIR / f"{symbol}_facts.parquet"
        subs_path = SEC_DATA_DIR / f"{symbol}_submissions.parquet"
        if not facts_path.exists():
            return pd.DataFrame()

        sig = _fundamentals_signature(facts_path, subs_path)
        cached = _FUNDAMENTALS_CACHE.get(symbol)
        if cached is not None and cached[0] == sig:
            facts = cached[1]
        else:
            facts = pd.read_parquet(facts_path)
            if facts.empty:
                return facts

            acceptance_map: dict[str, pd.Timestamp] = {}
            if subs_path.exists():
                subs = pd.read_parquet(subs_path)
                for _, r in subs.iterrows():
                    acceptance_map[str(r["accession_no"])] = _parse_acceptance_utc(
                        r["acceptance_datetime"]
                    )

            known_at = []
            date_only = []
            for acc, filed in zip(facts["accn"], facts["filed"]):
                precise = acceptance_map.get(str(acc))
                if precise is not None:
                    known_at.append(precise)
                    date_only.append(False)
                    continue
                ft = pd.to_datetime(filed, errors="coerce")
                if pd.isna(ft):
                    known_at.append(pd.NaT)
                else:
                    known_at.append(
                        ft.tz_localize("UTC")
                        + pd.Timedelta(days=1)
                        - pd.Timedelta(microseconds=1)
                    )
                date_only.append(True)

            facts = facts.copy()
            facts["known_at"] = pd.to_datetime(known_at, utc=True)
            facts["is_date_only"] = date_only
            _FUNDAMENTALS_CACHE[symbol] = (sig, facts)

        m = facts["known_at"] <= a
        # conservative same-day exclusion for date-only filed == feature_as_of.date()
        filed_date = pd.to_datetime(facts["filed"], errors="coerce").dt.date
        m &= ~(facts["is_date_only"] & (filed_date == a.date()))
        visible = facts[m]

        if visible.empty:
            return visible

        visible = visible.sort_values("known_at")
        return (
            visible.groupby(["concept", "unit", "end"], dropna=False)
            .tail(1)
            .sort_values("known_at")
            .reset_index(drop=True)
        )
