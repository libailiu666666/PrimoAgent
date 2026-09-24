"""Manifest builder: required fields and JSON round-trip."""
from __future__ import annotations

import json

import pandas as pd

from src.experiments.manifest import (
    build_manifest,
    git_commit,
    new_experiment_id,
    write_json,
)

REQUIRED = {
    "experiment_id",
    "generated_at",
    "config_path",
    "config_hash",
    "data_snapshot_hash",
    "git_commit",
    "random_seed",
    "cost_assumptions",
    "execution_assumptions",
    "legacy_risk_switches",
    "ticker_universe",
    "folds",
    "results",
    "output_paths",
}


def _manifest():
    return build_manifest(
        experiment_id="exp_1",
        generated_at="2026-09-23T00:00:00Z",
        config_path="configs/experiments/gate2_baseline.yaml",
        config_hash="abc123",
        data_snapshot_hash="def456",
        git={"commit": "abc", "short": "abc", "dirty": False},
        random_seed=42,
        cost_assumptions={"commission_bps_grid": [0, 10, 20, 50]},
        execution_assumptions={"protocol": "T close -> signal after close -> T+1 open"},
        legacy_risk_switches={
            "risk.regime.enabled": False,
            "backtesting.enable_trailing_stop": False,
            "backtesting.enable_take_profit": False,
        },
        ticker_universe=["AAPL", "MSFT"],
        folds=[{"fold": 0}],
        results=[{"strategy": "equal_weight", "fold": 0}],
        output_paths={"manifest": "manifest.json"},
    )


def test_manifest_contains_all_required_fields():
    m = _manifest()
    assert REQUIRED <= set(m)


def test_manifest_records_legacy_switches_off():
    m = _manifest()
    assert all(v is False for v in m["legacy_risk_switches"].values())


def test_git_commit_returns_structured_dict():
    g = git_commit()
    assert set(g) == {"commit", "short", "dirty"}


def test_new_experiment_id_is_unique():
    assert new_experiment_id("gate2_baseline") != new_experiment_id("gate2_baseline")


def test_write_json_roundtrips_timestamps(tmp_path):
    payload = {
        "ts": pd.Timestamp("2024-01-02"),
        "nested": {"arr": [pd.Timestamp("2024-01-03")]},
    }
    p = write_json(tmp_path / "sub" / "m.json", payload)
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["ts"] == "2024-01-02T00:00:00"
    assert loaded["nested"]["arr"] == ["2024-01-03T00:00:00"]
