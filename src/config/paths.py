"""Canonical project paths.

All runtime paths are resolved from the repository root instead of the shell's
current working directory. This keeps scripts and agents stable after the
project was reorganized.
"""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output"

DATA_DIR = OUTPUT_DIR / "data"
YAHOO_DATA_DIR = DATA_DIR / "yahoo"
FINNHUB_DATA_DIR = DATA_DIR / "finnhub"
SEC_DATA_DIR = DATA_DIR / "sec"
NEWS_DATA_DIR = DATA_DIR / "news"
ALPHA_VANTAGE_DATA_DIR = DATA_DIR / "alpha_vantage"
MACRO_DATA_DIR = DATA_DIR / "macro"

CACHE_DIR = OUTPUT_DIR / "cache"
TIINGO_CACHE_DIR = CACHE_DIR / "tiingo"
CSV_OUTPUT_DIR = OUTPUT_DIR / "csv"
BACKTEST_OUTPUT_DIR = OUTPUT_DIR / "backtests"

DOCS_DIR = PROJECT_ROOT / "docs"
DATA_INVENTORY_PATH = DOCS_DIR / "data" / "DATA_INVENTORY.md"
ENV_PATH = PROJECT_ROOT / ".env"
