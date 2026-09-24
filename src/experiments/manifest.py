"""Experiment manifest builder (Gate 2).

Captures everything needed to reproduce a run: experiment id, strategy/version,
fold ranges, ticker universe, config/data/git hashes, random seed, cost and
execution assumptions, the final legacy-risk switch values, output paths, and a
generation timestamp.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..config.paths import PROJECT_ROOT


def git_commit() -> Dict[str, str]:
    """Return the current git commit (or an empty marker when unavailable)."""
    try:
        full = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        short = full[:7]
        dirty = (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            ).stdout.strip()
            != ""
        )
        return {"commit": full, "short": short, "dirty": dirty}
    except Exception:
        return {"commit": "", "short": "", "dirty": None}


def new_experiment_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"


def build_manifest(
    *,
    experiment_id: str,
    generated_at: str,
    config_path: str,
    config_hash: str,
    data_snapshot_hash: str,
    git: Dict[str, str],
    random_seed: int,
    cost_assumptions: Dict[str, Any],
    execution_assumptions: Dict[str, Any],
    legacy_risk_switches: Dict[str, bool],
    ticker_universe: List[str],
    folds: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    output_paths: Dict[str, str],
) -> Dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "generated_at": generated_at,
        "config_path": config_path,
        "config_hash": config_hash,
        "data_snapshot_hash": data_snapshot_hash,
        "git_commit": git.get("commit"),
        "git_short": git.get("short"),
        "git_dirty": git.get("dirty"),
        "random_seed": random_seed,
        "cost_assumptions": cost_assumptions,
        "execution_assumptions": execution_assumptions,
        "legacy_risk_switches": legacy_risk_switches,
        "ticker_universe": ticker_universe,
        "folds": folds,
        "results": results,
        "output_paths": output_paths,
    }


def write_json(path: str | Path, payload: Dict[str, Any]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_json_default)
    return p


def _json_default(obj: Any) -> Any:
    import pandas as pd

    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
