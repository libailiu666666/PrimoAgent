"""Historical-mode network guard (PIT_FROZEN_SPEC v1.1 section 3.5).

In historical mode the data layer may read local files only. Any attempt to
reach a realtime endpoint (Finnhub / Tiingo / Alpha Vantage / Yahoo /
Firecrawl / SEC) must fail fast rather than silently fall back to live data.

The guard patches the low-level network entry points used across the codebase
(``requests`` and ``aiohttp``) so that *any* network call raises
``HistoricalModeViolation`` while the mode is active.
"""
from __future__ import annotations

from typing import Any, Optional

_ACTIVE = False

_orig_requests_request: Optional[Any] = None
_orig_aiohttp_request: Optional[Any] = None


class HistoricalModeViolation(RuntimeError):
    """Raised when historical mode attempts any network I/O."""


def historical_mode_active() -> bool:
    return _ACTIVE


def _guarded_requests_request(self, method: str, url: str, **kwargs: Any):
    raise HistoricalModeViolation(
        f"network request forbidden in historical mode: {method.upper()} {url}"
    )


def _guarded_aiohttp_request(self, method: str, url: str, **kwargs: Any):
    raise HistoricalModeViolation(
        f"network request forbidden in historical mode: {method.upper()} {url}"
    )


def _install_guard() -> None:
    global _orig_requests_request, _orig_aiohttp_request
    import requests.sessions

    if _orig_requests_request is None:
        _orig_requests_request = requests.sessions.Session.request
    requests.sessions.Session.request = _guarded_requests_request

    try:
        import aiohttp

        if _orig_aiohttp_request is None:
            _orig_aiohttp_request = aiohttp.ClientSession._request
        aiohttp.ClientSession._request = _guarded_aiohttp_request
    except ImportError:
        pass


def _remove_guard() -> None:
    global _orig_requests_request, _orig_aiohttp_request
    import requests.sessions

    if _orig_requests_request is not None:
        requests.sessions.Session.request = _orig_requests_request
        _orig_requests_request = None

    if _orig_aiohttp_request is not None:
        try:
            import aiohttp

            aiohttp.ClientSession._request = _orig_aiohttp_request
        except ImportError:
            pass
        _orig_aiohttp_request = None


def enable_historical_mode() -> None:
    """Activate the network guard. Idempotent."""
    global _ACTIVE
    if not _ACTIVE:
        _install_guard()
    _ACTIVE = True


def disable_historical_mode() -> None:
    """Deactivate the network guard and restore original network entry points."""
    global _ACTIVE
    if _ACTIVE:
        _remove_guard()
    _ACTIVE = False
