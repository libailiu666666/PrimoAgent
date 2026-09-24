"""The three pre-Gate2 legacy risk overlays must be OFF."""
from __future__ import annotations

from src.config import config
from src.experiments.config import (
    LEGACY_SWITCH_SPEC,
    ExperimentConfig,
    apply_legacy_switches_to_global,
)

EXPECTED_SWITCHES = {
    "risk.regime.enabled",
    "backtesting.enable_trailing_stop",
    "backtesting.enable_take_profit",
}


def test_gate2_config_disables_all_legacy_switches(gate2_config_path):
    cfg = ExperimentConfig.load(gate2_config_path)
    switches = cfg.legacy_switches()
    assert set(switches) == EXPECTED_SWITCHES
    assert all(v is False for v in switches.values())
    cfg.assert_legacy_switches_off()  # must not raise


def test_legacy_switch_spec_matches_config_paths(gate2_config_path):
    cfg = ExperimentConfig.load(gate2_config_path)
    for dotted, keys in LEGACY_SWITCH_SPEC:
        assert cfg._get("legacy_risk", *keys) is False


def test_apply_legacy_switches_to_global_forces_off(restore_global_config):
    applied = apply_legacy_switches_to_global(
        {
            "risk.regime.enabled": False,
            "backtesting.enable_trailing_stop": False,
            "backtesting.enable_take_profit": False,
        }
    )
    assert applied["risk.regime.enabled"] is False
    assert applied["backtesting.enable_trailing_stop"] is False
    assert applied["backtesting.enable_take_profit"] is False
    assert config.risk_regime_enabled is False
    assert config.backtest_enable_trailing_stop is False
    assert config.backtest_enable_take_profit is False
