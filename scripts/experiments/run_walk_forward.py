#!/usr/bin/env python
"""Run the Gate 2 walk-forward benchmark.

Examples
--------
    # single cost level (0 bps) — deterministic, reproducible
    python scripts/experiments/run_walk_forward.py \
        --config configs/experiments/gate2_baseline.yaml --cost-bps 0

    # full cost-sensitivity sweep (0 / 10 / 20 / 50 bps)
    python scripts/experiments/run_walk_forward.py \
        --config configs/experiments/gate2_baseline.yaml --cost-sensitivity
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.experiments.config import ExperimentConfig
from src.experiments.metrics import pool_metrics
from src.experiments.runner import DEFAULT_COST_GRID, run_walk_forward

_METRIC_COLS = [
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "sharpe_ratio",
    "max_drawdown",
    "calmar_ratio",
    "turnover_rate",
    "total_cost",
]


def _pooled_table(results):
    """Group results by (strategy, cost_bps) and pool metrics across folds."""
    groups: dict = {}
    for r in results:
        key = (r["strategy"], r["cost_bps"])
        groups.setdefault(key, []).append(r)

    rows = []
    for (sname, cost), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        pooled = pool_metrics([r["metrics"] | {"_returns": r.get("_returns")} for r in rs])
        rows.append((sname, cost, pooled))
    return rows


def _fmt_pct(x) -> str:
    if x is None or (isinstance(x, float) and x != x):  # NaN
        return "    n/a"
    return f"{x * 100:7.2f}%"


def print_summary(results) -> None:
    rows = _pooled_table(results)
    header = (
        f"{'strategy':<18} {'cost':>5} {'tot_ret':>9} {'ann_ret':>9} {'ann_vol':>9} "
        f"{'sharpe':>7} {'max_dd':>9} {'calmar':>8} {'n_days':>6}"
    )
    print("\nPooled walk-forward results (all test folds chained):")
    print(header)
    print("-" * len(header))
    for sname, cost, m in rows:
        print(
            f"{sname:<18} {int(cost):>5} "
            f"{_fmt_pct(m.get('total_return')):>9} "
            f"{_fmt_pct(m.get('annualized_return')):>9} "
            f"{_fmt_pct(m.get('annualized_volatility')):>9} "
            f"{m.get('sharpe_ratio') or 0:>7.2f} "
            f"{_fmt_pct(m.get('max_drawdown')):>9} "
            f"{m.get('calmar_ratio') or 0:>8.2f} "
            f"{int(m.get('n_days', 0)):>6}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate 2 walk-forward benchmark")
    parser.add_argument("--config", required=True, help="experiment YAML config")
    parser.add_argument(
        "--cost-bps", type=float, default=None, help="single commission level in bps"
    )
    parser.add_argument(
        "--costs", type=str, default=None, help="comma-separated commission levels in bps"
    )
    parser.add_argument(
        "--cost-sensitivity", action="store_true",
        help="run the default 0/10/20/50 bps sensitivity sweep",
    )
    parser.add_argument(
        "--strategies", type=str, default=None, help="comma-separated strategy subset"
    )
    parser.add_argument("--slippage-bps", type=float, default=None)
    args = parser.parse_args()

    cfg = ExperimentConfig.load(args.config)

    if args.cost_sensitivity:
        cost_grid = DEFAULT_COST_GRID
    elif args.costs:
        cost_grid = [float(x) for x in args.costs.split(",")]
    elif args.cost_bps is not None:
        cost_grid = [args.cost_bps]
    else:
        cost_grid = [cfg.commission_bps]

    strategies = args.strategies.split(",") if args.strategies else None

    out = run_walk_forward(
        cfg,
        cost_grid=cost_grid,
        strategies=strategies,
        slippage_bps=args.slippage_bps,
    )

    print_summary(out["results"])
    print(f"\nManifest: {out['run_dir']}/manifest.json")


if __name__ == "__main__":
    main()
