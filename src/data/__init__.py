"""Point-in-time data access layer (PIT_FROZEN_SPEC v1.1).

Submodules:
- contracts: frozen time fields, the causal invariant, and tz helpers.
- historical_mode: global guard that forbids any network I/O in historical mode.
- historical_store: the four PIT-safe query interfaces backed by local data only.
"""
from .contracts import (
    PITTimeError,
    UTC,
    close_time_utc,
    ensure_utc,
    open_time_utc,
    validate_causal_order,
)
from .historical_mode import (
    HistoricalModeViolation,
    disable_historical_mode,
    enable_historical_mode,
    historical_mode_active,
)
from .historical_store import HistoricalDataStore, snapshot_hash

__all__ = [
    "PITTimeError",
    "UTC",
    "close_time_utc",
    "ensure_utc",
    "open_time_utc",
    "validate_causal_order",
    "HistoricalModeViolation",
    "disable_historical_mode",
    "enable_historical_mode",
    "historical_mode_active",
    "HistoricalDataStore",
    "snapshot_hash",
]
