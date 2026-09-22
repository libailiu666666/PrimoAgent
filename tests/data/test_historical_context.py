"""Future-signal exclusion for the historical-context reader (PIT_FROZEN_SPEC 3.2).

The portfolio manager's ``read_historical_context`` must read the per-symbol
file and return only decisions strictly before ``feature_as_of``. Because the
agent module imports the full LLM stack (langgraph/langchain), these tests
verify the data + filter contract directly and, when the stack is present, the
function itself.
"""
import pandas as pd

from src.config.paths import PROJECT_ROOT

SYMBOL = "AAPL"
CSV = PROJECT_ROOT / "output" / "csv" / f"daily_analysis_{SYMBOL}.csv"


def _pit_filter(symbol: str, analysis_date, count: int = 20) -> pd.DataFrame:
    """Replicate the exact filter contract of read_historical_context."""
    df = pd.read_csv(CSV)
    df = df[df["symbol"] == symbol.upper()]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if analysis_date is not None:
        cutoff = pd.to_datetime(analysis_date, errors="coerce")
        if pd.notna(cutoff):
            df = df[df["date"] < cutoff]
    df = df.sort_values("date", ascending=False)
    return df.head(count).reset_index(drop=True)


def test_per_symbol_file_exists_and_scoped():
    assert CSV.exists()
    df = pd.read_csv(CSV)
    assert not df.empty
    assert (df["symbol"] == SYMBOL).all()


def test_future_signals_excluded():
    df = _pit_filter(SYMBOL, "2025-01-03")
    assert not df.empty
    assert (df["date"] < pd.Timestamp("2025-01-03")).all()


def test_same_day_signal_excluded():
    df = _pit_filter(SYMBOL, "2025-01-02")
    assert not (df["date"] >= pd.Timestamp("2025-01-02")).any()


def test_newest_first_and_bounded():
    df = _pit_filter(SYMBOL, None, count=20)
    assert len(df) <= 20
    assert df["date"].is_monotonic_decreasing


def test_read_historical_context_function():
    # Import the workflow package first to break a pre-existing circular import
    # (portfolio_manager_agent -> workflows.state -> workflow -> agents).
    import src.workflows.workflow  # noqa: F401

    from src.agents.portfolio_manager_agent import read_historical_context

    rows = read_historical_context(SYMBOL, "2025-01-03")
    assert rows, "expected historical rows for AAPL"
    for r in rows:
        assert str(r["analysis_date"]) < "2025-01-03"
