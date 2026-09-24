"""Experiment configuration for the walk-forward benchmark (Gate 2).

Loads and validates ``configs/experiments/*.yaml``, exposes a stable canonical
hash of the resolved config, and resolves the three pre-Gate2 legacy risk
switches that the benchmark must keep disabled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# (dotted name as printed/manifested, nested key path inside legacy_risk)
LEGACY_SWITCH_SPEC: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("risk.regime.enabled", ("risk", "regime", "enabled")),
    ("backtesting.enable_trailing_stop", ("backtesting", "enable_trailing_stop")),
    ("backtesting.enable_take_profit", ("backtesting", "enable_take_profit")),
)


def _canonicalize(value: Any) -> Any:
    """Recursively produce a hash-stable form (sorted dict keys)."""
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    return value


class ExperimentConfig:
    """A resolved experiment configuration loaded from a YAML file."""

    def __init__(self, raw: Dict[str, Any], path: Path) -> None:
        self.raw = raw
        self.path = Path(path)

    # ---------------------------------------------------------------- loaders

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentConfig":
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"experiment config must be a mapping: {p}")
        return cls(raw, p)

    # ----------------------------------------------------------------- helpers

    def _get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    # -------------------------------------------------------------- properties

    @property
    def name(self) -> str:
        return str(self._get("experiment", "name", default="experiment"))

    @property
    def version(self) -> str:
        return str(self._get("experiment", "version", default="1.0.0"))

    @property
    def random_seed(self) -> int:
        return int(self._get("experiment", "random_seed", default=42))

    @property
    def tickers(self) -> List[str]:
        return list(self._get("universe", "tickers", default=[]))

    @property
    def price_source(self) -> str:
        return str(self._get("universe", "price_source", default="tiingo"))

    @property
    def spy_ticker(self) -> str:
        return str(self._get("benchmark", "spy_ticker", default="SPY"))

    @property
    def spy_source(self) -> str:
        return str(self._get("benchmark", "spy_source", default="yahoo"))

    @property
    def walk_forward(self) -> Dict[str, Any]:
        return dict(self._get("walk_forward", default={}))

    @property
    def start_year(self) -> int:
        return int(self._get("walk_forward", "start_year", default=2017))

    @property
    def train_years(self) -> int:
        return int(self._get("walk_forward", "train_years", default=4))

    @property
    def calibration_years(self) -> int:
        return int(self._get("walk_forward", "calibration_years", default=1))

    @property
    def test_years(self) -> int:
        return int(self._get("walk_forward", "test_years", default=1))

    @property
    def costs(self) -> Dict[str, Any]:
        return dict(self._get("costs", default={}))

    @property
    def initial_capital(self) -> float:
        return float(self._get("costs", "initial_capital", default=100000.0))

    @property
    def commission_bps(self) -> float:
        return float(self._get("costs", "commission_bps", default=0.0))

    @property
    def slippage_bps(self) -> float:
        return float(self._get("costs", "slippage_bps", default=0.0))

    @property
    def cash_reserve_pct(self) -> float:
        return float(self._get("costs", "cash_reserve_pct", default=0.0))

    @property
    def strategies(self) -> List[str]:
        return list(self._get("strategies", default=[]))

    @property
    def strategy_params(self) -> Dict[str, Any]:
        return dict(self._get("strategy_params", default={}))

    @property
    def output_root(self) -> str:
        return str(self._get("output", "root", default="output/experiments"))

    @property
    def execution_protocol(self) -> str:
        return str(
            self._get(
                "execution", "protocol",
                default="T close -> signal after close -> T+1 open",
            )
        )

    # ------------------------------------------------------- legacy switches

    def legacy_switches(self) -> Dict[str, bool]:
        """Return the three legacy risk switches keyed by dotted name."""
        out: Dict[str, bool] = {}
        for dotted, keys in LEGACY_SWITCH_SPEC:
            out[dotted] = bool(self._get("legacy_risk", *keys, default=False))
        return out

    def assert_legacy_switches_off(self) -> None:
        """Fail fast if any legacy overlay is not disabled."""
        for dotted, value in self.legacy_switches().items():
            if value is not False:
                raise ValueError(
                    f"legacy overlay must be disabled for the benchmark: "
                    f"{dotted}={value!r} (expected False)"
                )

    # ---------------------------------------------------------------- hashing

    def config_hash(self) -> str:
        """Stable canonical hash of the resolved config (order-independent)."""
        payload = json.dumps(_canonicalize(self.raw), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_legacy_switches_to_global(switches: Dict[str, bool]) -> Dict[str, bool]:
    """Push the legacy switches into the global ``config`` object (defense in
    depth so any shared legacy code path also sees the overlays off)."""
    from ..config import config

    risk = config._config_data.setdefault("risk", {})
    regime = risk.setdefault("regime", {})
    regime["enabled"] = bool(switches.get("risk.regime.enabled", False))
    bt = config._config_data.setdefault("backtesting", {})
    bt["enable_trailing_stop"] = bool(
        switches.get("backtesting.enable_trailing_stop", False)
    )
    bt["enable_take_profit"] = bool(
        switches.get("backtesting.enable_take_profit", False)
    )
    return {
        "risk.regime.enabled": config.risk_regime_enabled,
        "backtesting.enable_trailing_stop": config.backtest_enable_trailing_stop,
        "backtesting.enable_take_profit": config.backtest_enable_take_profit,
    }
