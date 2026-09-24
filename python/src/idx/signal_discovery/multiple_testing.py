"""Multiple-testing / overfit controls (Cluster 8).

Implements, without new dependencies:
* Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012)
* Deflated Sharpe Ratio (Bailey & López de Prado, 2014) — PSR against the
  expected maximum Sharpe of N trials
* Benjamini–Hochberg false-discovery control on one-sided mean-return p-values

Inputs are per-period (non-annualised) portfolio returns — one observation per
rebalance exit — to limit the cross-sectional dependence of individual trades.
Results are research diagnostics, never production eligibility on their own.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

EULER_GAMMA = 0.5772156649015329
MIN_PERIODS = 20
DSR_THRESHOLD = 0.95
DEFAULT_FDR_ALPHA = 0.10

_NORMAL = statistics.NormalDist()

METHOD_NOTES = (
    "Per-period equal-weight portfolio returns (one per exit session). Overlapping holding "
    "windows and regime dependence make p-values approximate; evaluations counted as trials "
    "are correlated, so N overstates independent tests (conservative for DSR)."
)


def return_moments(returns: Sequence[float]) -> dict[str, Any]:
    """Sample Sharpe (per period), skewness and Pearson kurtosis (normal = 3)."""
    xs = [float(x) for x in returns if x is not None and math.isfinite(float(x))]
    n = len(xs)
    out: dict[str, Any] = {
        "periods": n,
        "mean": None,
        "std": None,
        "sharpe": None,
        "skew": None,
        "kurtosis": None,
    }
    if n < 2:
        return out
    mean = statistics.fmean(xs)
    std = statistics.stdev(xs)
    out["mean"], out["std"] = mean, std
    if std == 0:
        return out
    m2 = sum((x - mean) ** 2 for x in xs) / n
    m3 = sum((x - mean) ** 3 for x in xs) / n
    m4 = sum((x - mean) ** 4 for x in xs) / n
    out["sharpe"] = mean / std
    out["skew"] = m3 / m2**1.5 if m2 > 0 else 0.0
    out["kurtosis"] = m4 / m2**2 if m2 > 0 else 3.0
    return out


def probabilistic_sharpe_ratio(
    sharpe: float, benchmark_sharpe: float, periods: int, skew: float, kurtosis: float
) -> float | None:
    """P(true SR > benchmark SR) given sample moments; ``None`` if undefined."""
    if periods < 2:
        return None
    denom_sq = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if denom_sq <= 0:
        return None
    z = (sharpe - benchmark_sharpe) * math.sqrt(periods - 1) / math.sqrt(denom_sq)
    return _NORMAL.cdf(z)


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum of N i.i.d. Sharpe estimates with zero true Sharpe."""
    if n_trials <= 1 or sharpe_variance <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(sharpe_variance) * (
        (1.0 - EULER_GAMMA) * _NORMAL.inv_cdf(1.0 - 1.0 / n)
        + EULER_GAMMA * _NORMAL.inv_cdf(1.0 - 1.0 / (n * math.e))
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    trial_sharpes: Sequence[float],
    n_trials: int | None = None,
) -> dict[str, Any]:
    """DSR of one return series against all trial Sharpes of the same study."""
    moments = return_moments(returns)
    valid_trials = [float(s) for s in trial_sharpes if s is not None and math.isfinite(float(s))]
    n = int(n_trials if n_trials is not None else len(valid_trials))
    out: dict[str, Any] = {
        **moments,
        "n_trials": n,
        "trial_sharpe_variance": None,
        "expected_max_sharpe": None,
        "dsr": None,
        "dsr_threshold": DSR_THRESHOLD,
        "status": "INSUFFICIENT_DATA",
        "method_notes": METHOD_NOTES,
    }
    if moments["periods"] < MIN_PERIODS or moments["sharpe"] is None:
        out["reason"] = f"periods={moments['periods']} < {MIN_PERIODS} or zero variance"
        return out
    if n < 1:
        out["reason"] = "no trials recorded"
        return out
    variance = statistics.variance(valid_trials) if len(valid_trials) >= 2 else 0.0
    sr0 = expected_max_sharpe(n, variance)
    dsr = probabilistic_sharpe_ratio(
        moments["sharpe"], sr0, moments["periods"], moments["skew"], moments["kurtosis"]
    )
    out.update(
        {
            "trial_sharpe_variance": variance,
            "expected_max_sharpe": sr0,
            "dsr": dsr,
        }
    )
    if dsr is None:
        out["reason"] = "PSR denominator non-positive"
        return out
    out["status"] = "PASS" if dsr >= DSR_THRESHOLD else "FAIL"
    return out


def mean_return_pvalue(returns: Sequence[float]) -> float | None:
    """One-sided p-value for mean > 0 (normal approximation; requires MIN_PERIODS)."""
    m = return_moments(returns)
    if m["periods"] < MIN_PERIODS or not m["std"]:
        return None
    t = m["mean"] / (m["std"] / math.sqrt(m["periods"]))
    return 1.0 - _NORMAL.cdf(t)


def benjamini_hochberg(
    pvalues: dict[str, float | None], *, alpha: float = DEFAULT_FDR_ALPHA
) -> dict[str, Any]:
    """BH step-up over the tested hypotheses; ``None`` p-values are untestable (not rejected)."""
    tested = sorted(((k, p) for k, p in pvalues.items() if p is not None), key=lambda kv: kv[1])
    m = len(tested)
    cutoff_rank = 0
    for rank, (_, p) in enumerate(tested, start=1):
        if p <= alpha * rank / m:
            cutoff_rank = rank
    discoveries = {k for k, _ in tested[:cutoff_rank]}
    return {
        "alpha": alpha,
        "tested": m,
        "untestable": sorted(k for k, p in pvalues.items() if p is None),
        "discoveries": sorted(discoveries),
        "decisions": {
            k: ("DISCOVERY" if k in discoveries else "NOT_SIGNIFICANT")
            if p is not None
            else "UNTESTABLE"
            for k, p in pvalues.items()
        },
        "method_notes": METHOD_NOTES,
    }
