"""Shared fixtures for the PIT data-layer tests."""
import pytest

from src.data import historical_mode


@pytest.fixture(autouse=True)
def _clean_historical_mode():
    """Leave historical mode off before and after every test."""
    historical_mode.disable_historical_mode()
    yield
    historical_mode.disable_historical_mode()
