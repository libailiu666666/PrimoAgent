"""Historical-mode network guard tests (PIT_FROZEN_SPEC section 3.5)."""
import requests
import pytest

from src.data import historical_mode


def test_network_guard_blocks_requests():
    historical_mode.enable_historical_mode()
    try:
        with pytest.raises(historical_mode.HistoricalModeViolation):
            requests.get("https://example.com")
    finally:
        historical_mode.disable_historical_mode()


def test_network_guard_blocks_session_request():
    historical_mode.enable_historical_mode()
    try:
        with pytest.raises(historical_mode.HistoricalModeViolation):
            requests.Session().get("https://example.com")
    finally:
        historical_mode.disable_historical_mode()


def test_guard_restored_after_disable():
    historical_mode.enable_historical_mode()
    assert historical_mode.historical_mode_active() is True
    historical_mode.disable_historical_mode()
    assert historical_mode.historical_mode_active() is False
    # original entry point restored (no exception on a normal request attempt)
    assert requests.sessions.Session.request is not historical_mode._guarded_requests_request


def test_store_constructor_activates_historical_mode():
    from src.data.historical_store import HistoricalDataStore

    historical_mode.disable_historical_mode()
    HistoricalDataStore("historical")
    assert historical_mode.historical_mode_active() is True
