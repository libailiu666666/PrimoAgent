"""Walk-forward runner (Gate 2).

Orchestrates the deterministic baselines over data-driven expanding folds:

1. resolve + assert the three legacy risk switches are OFF (and push them to the
   global config object as defense in depth),
2. load the adjusted universe and the SPY benchmark,
3. build annual expanding folds from the real common date coverage,
4. run every strategy over every fold at every cost level with the frozen
   T close -> T+1 open execution protocol,
5. assemble a reproducible manifest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ..config.paths import PROJECT_ROOT
from ..data.historical_store import HistoricalDataStore
from .config import ExperimentConfig, apply_legacy_switches_to_global
from .data import load_spy, load_universe
from .execution import CostModel, run_backtest
from .folds import build_annual_expanding_folds, select_dates
from .manifest import build_manifest, git_commit, new_experiment_id, write_json
from .metrics import attach_returns, compute_metrics
from .strategies import STRATEGY_CLASSES, FitData

DEFAULT_COST_GRID = [0, 10, 20, 50]


def _print_legacy_switches(switches: Dict[str, bool]) -> None:
    print("Legacy risk switches (final values):")
    for k, v in switches.items():
        print(f"  {k} = {v}")
    assert all(v is False for v in switches.values()), "legacy overlays must be off"


def _align_to_dates(df: pd.DataFrame, dates: List[pd.Timestamp]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.Timestamp(d).normalize() for d in dates)
    return df.reindex(idx).ffill()


def run_walk_forward(
    exp_cfg: ExperimentConfig,
    cost_grid: Optional[List[float]] = None,
    strategies: Optional[List[str]] = None,
    slippage_bps: Optional[float] = None,
    write_outputs: bool = True,
) -> Dict:
    """Run the full walk-forward benchmark and return a structured result dict."""
    # 1. Legacy switches ------------------------------------------------------
    switches = exp_cfg.legacy_switches()
    exp_cfg.assert_legacy_switches_off()
    applied = apply_legacy_switches_to_global(switches)
    _print_legacy_switches(applied)

    # 2. Data ----------------------------------------------------------------
    universe = load_universe(exp_cfg.tickers, exp_cfg.price_source)
    if not universe.dates:
        raise RuntimeError("universe produced no common trading dates")
    spy_df = load_spy(exp_cfg.spy_ticker, exp_cfg.spy_source)
    spy_aligned = _align_to_dates(spy_df, universe.dates) if spy_df is not None else None

    # 3. Folds ---------------------------------------------------------------
    folds = build_annual_expanding_folds(
        universe.dates,
        exp_cfg.start_year,
        exp_cfg.train_years,
        exp_cfg.calibration_years,
        exp_cfg.test_years,
    )
    if not folds:
        raise RuntimeError("no folds could be built from the available data")
    print(f"Walk-forward folds ({len(folds)}):")
    for f in folds:
        flag = " (partial test)" if f.is_partial_test else ""
        print(
            f"  fold {f.index}: train {f.train_start.date()}..{f.train_end.date()} | "
            f"cal {f.calibration_start.date()}..{f.calibration_end.date()} | "
            f"test {f.test_start.date()}..{f.test_end.date()}{flag}"
        )

    # 4. Run -----------------------------------------------------------------
    cost_grid = list(cost_grid) if cost_grid is not None else [exp_cfg.commission_bps]
    strategies = list(strategies) if strategies is not None else list(exp_cfg.strategies)
    slippage = slippage_bps if slippage_bps is not None else exp_cfg.slippage_bps

    store = HistoricalDataStore("historical") if "fundamental_only" in strategies else None

    results: List[Dict] = []
    equity_artifacts: Dict[str, pd.Series] = {}
    fills_artifacts: Dict[str, list] = {}

    for fold in folds:
        test_dates = select_dates(universe.dates, fold.test_start, fold.test_end)
        if not test_dates:
            continue
        train_dates = select_dates(universe.dates, fold.train_start, fold.train_end)
        cal_dates = select_dates(universe.dates, fold.calibration_start, fold.calibration_end)
        fit_prices = {s: df.loc[: fold.calibration_end] for s, df in universe.prices.items()}
        fit_data = FitData(train_dates=train_dates, calibration_dates=cal_dates, prices=fit_prices, store=store)

        for sname in strategies:
            if sname == "spy_benchmark":
                continue  # handled separately below (zero-cost reference)
            prices = {"SPY": spy_aligned} if sname == "buy_and_hold" else universe.prices
            params = dict(exp_cfg.strategy_params.get(sname, {}))
            cls = STRATEGY_CLASSES[sname]

            for cost_bps in cost_grid:
                cost = CostModel(
                    initial_capital=exp_cfg.initial_capital,
                    commission_bps=float(cost_bps),
                    slippage_bps=float(slippage),
                    cash_reserve_pct=exp_cfg.cash_reserve_pct,
                )
                strat = cls(params=params, store=store)
                strat.fit(fit_data)
                reb = strat.rebalance_indices(test_dates)
                res = run_backtest(strat, test_dates, prices, cost, reb, fold.index)

                m = compute_metrics(
                    res.equity,
                    exp_cfg.initial_capital,
                    res.total_commission,
                    res.total_slippage,
                    res.total_turnover,
                    n_trades=len(res.fills),
                )
                m = attach_returns(m, res.equity)

                key = f"{sname}_fold{fold.index}_cost{int(cost_bps)}"
                equity_artifacts[key] = res.equity
                fills_artifacts[key] = [f.as_dict() for f in res.fills]

                results.append(
                    {
                        "strategy": sname,
                        "version": strat.version,
                        "fold": fold.index,
                        "cost_bps": float(cost_bps),
                        "slippage_bps": float(slippage),
                        "train": [fold.train_start.date().isoformat(), fold.train_end.date().isoformat()],
                        "calibration": [fold.calibration_start.date().isoformat(), fold.calibration_end.date().isoformat()],
                        "test": [fold.test_start.date().isoformat(), fold.test_end.date().isoformat()],
                        "is_partial_test": fold.is_partial_test,
                        "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
                        "_returns": m.get("_returns"),
                        "equity_path": f"equity/{key}.csv",
                        "fills_path": f"fills/{key}.json",
                    }
                )

    # spy_benchmark: SPY total-return index (zero cost reference), per fold.
    if "spy_benchmark" in strategies and spy_aligned is not None:
        for fold in folds:
            test_dates = select_dates(universe.dates, fold.test_start, fold.test_end)
            eq = _spy_index_equity(spy_aligned, test_dates, exp_cfg.initial_capital)
            if eq is None:
                continue
            m = compute_metrics(eq, exp_cfg.initial_capital, 0.0, 0.0, 0.0, 0)
            m = attach_returns(m, eq)
            key = f"spy_benchmark_fold{fold.index}_cost0"
            equity_artifacts[key] = eq
            results.append(
                {
                    "strategy": "spy_benchmark",
                    "version": "index",
                    "fold": fold.index,
                    "cost_bps": 0.0,
                    "slippage_bps": 0.0,
                    "train": [fold.train_start.date().isoformat(), fold.train_end.date().isoformat()],
                    "calibration": [fold.calibration_start.date().isoformat(), fold.calibration_end.date().isoformat()],
                    "test": [fold.test_start.date().isoformat(), fold.test_end.date().isoformat()],
                    "is_partial_test": fold.is_partial_test,
                    "metrics": {k: v for k, v in m.items() if not k.startswith("_")},
                    "_returns": m.get("_returns"),
                    "equity_path": f"equity/{key}.csv",
                    "fills_path": None,
                }
            )

    # 5. Manifest ------------------------------------------------------------
    experiment_id = new_experiment_id(exp_cfg.name)
    generated_at = datetime.now(timezone.utc).isoformat()
    git = git_commit()
    cost_assumptions = {
        "initial_capital": exp_cfg.initial_capital,
        "commission_bps_grid": cost_grid,
        "slippage_bps": slippage,
        "cash_reserve_pct": exp_cfg.cash_reserve_pct,
    }
    execution_assumptions = {
        "protocol": exp_cfg.execution_protocol,
        "signal_time": "T close",
        "execution_time": "T+1 open",
        "causal_invariant": "feature_as_of <= signal_generated_at < execution_at",
    }

    out_root = Path(PROJECT_ROOT) / exp_cfg.output_root
    run_dir = out_root / experiment_id
    output_paths = {
        "manifest": str(run_dir / "manifest.json"),
        "results_csv": str(run_dir / "results.csv"),
        "equity_dir": str(run_dir / "equity"),
        "fills_dir": str(run_dir / "fills"),
    }

    manifest_results = [{k: v for k, v in r.items() if k != "_returns"} for r in results]
    manifest = build_manifest(
        experiment_id=experiment_id,
        generated_at=generated_at,
        config_path=str(exp_cfg.path),
        config_hash=exp_cfg.config_hash(),
        data_snapshot_hash=universe.snapshot_hash(),
        git=git,
        random_seed=exp_cfg.random_seed,
        cost_assumptions=cost_assumptions,
        execution_assumptions=execution_assumptions,
        legacy_risk_switches=applied,
        ticker_universe=universe.symbols,
        folds=[f.as_dict() for f in folds],
        results=manifest_results,
        output_paths=output_paths,
    )

    if write_outputs:
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "manifest.json", manifest)
        _write_artifacts(run_dir, equity_artifacts, fills_artifacts)
        _write_results_csv(run_dir / "results.csv", results)

    return {
        "experiment_id": experiment_id,
        "config_hash": exp_cfg.config_hash(),
        "data_snapshot_hash": universe.snapshot_hash(),
        "git": git,
        "random_seed": exp_cfg.random_seed,
        "legacy_risk_switches": applied,
        "folds": [f.as_dict() for f in folds],
        "results": results,
        "manifest": manifest,
        "run_dir": str(run_dir),
    }


def _spy_index_equity(spy_df: pd.DataFrame, test_dates, initial_capital: float) -> Optional[pd.Series]:
    sub = spy_df["close"].reindex(test_dates).ffill().dropna()
    if len(sub) < 2:
        return None
    return pd.Series(initial_capital * sub / sub.iloc[0], index=sub.index)


def _write_artifacts(run_dir: Path, equity: Dict[str, pd.Series], fills: Dict[str, list]) -> None:
    eq_dir = run_dir / "equity"
    fl_dir = run_dir / "fills"
    eq_dir.mkdir(parents=True, exist_ok=True)
    fl_dir.mkdir(parents=True, exist_ok=True)
    for key, s in equity.items():
        s.to_csv(eq_dir / f"{key}.csv", header=["equity"])
    for key, fl in fills.items():
        write_json(fl_dir / f"{key}.json", fl)


def _write_results_csv(path: Path, results: List[Dict]) -> None:
    rows = []
    for r in results:
        row = {
            "strategy": r["strategy"],
            "version": r["version"],
            "fold": r["fold"],
            "cost_bps": r["cost_bps"],
            "slippage_bps": r["slippage_bps"],
            "test_start": r["test"][0],
            "test_end": r["test"][1],
            "is_partial_test": r["is_partial_test"],
        }
        row.update(r["metrics"])
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)
