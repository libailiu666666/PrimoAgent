"""Walk-forward benchmark framework (Gate 2).

Deterministic baselines over a frozen PIT data layer. Modules:

- ``config``   — experiment YAML loading, canonical hash, legacy-switch resolution
- ``folds``    — data-driven annual expanding-window fold construction
- ``data``     — adjusted price loading + deterministic data snapshot hash
- ``execution``— T+1 execution engine, PIT view, causal-invariant fills
- ``strategies``— the five deterministic baselines
- ``metrics``  — performance metrics
- ``manifest`` — experiment manifest builder
- ``runner``   — walk-forward orchestration
"""
from . import (  # noqa: F401
    config,
    data,
    execution,
    folds,
    manifest,
    metrics,
    runner,
    strategies,
)
