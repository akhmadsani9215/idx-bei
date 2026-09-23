import os, json, numpy as np, pandas as pd
from importlib.util import spec_from_file_location, module_from_spec

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "backtest_v3_2.py")

spec = spec_from_file_location("v32", SRC)
v32 = module_from_spec(spec)
spec.loader.exec_module(v32)

OUT = os.path.abspath(os.path.join(BASE, "..", "data", "backtest_v35_robustness_lab.json"))

TRAIN_END = pd.Timestamp("2026-03-31")
TEST_START = pd.Timestamp("2026-04-01")

COSTS = [0.0, 0.001, 0.002, 0.003, 0.005]

SETUPS = [
    "PULLBACK",
    "FOREIGN_SUPPORT",
    "FOREIGN",
    "MOMENTUM",
    "MOMENTUM_FOREIGN",
    "MOMENTUM_RVOL2",
    "ABSORPTION",
    "ABSORPTION_FOREIGN",
    "ABSORPTION_RVOL2",
    "REVERSAL",
    "REVERSAL_FOREIGN",
    "REVERSAL_RVOL2"
]

# Candidate edges from V3.4 that deserve deeper robustness testing.
ROBUSTNESS_TARGETS = [
    ("nextday", "MOMENTUM_RVOL2"),
    ("swing", "ABSORPTION"),
    ("swing", "ABSORPTION_FOREIGN"),
]

PARAM_GRID = [
    (0.75, 1.50),
    (0.75, 2.00),
    (0.75, 2.50),
    (1.00, 1.50),
    (1.00, 2.00),
    (1.00, 2.50),
    (1.00, 3.00),
    (1.25, 2.00),
    (1.25, 2.50),
    (1.25, 3.00),
    (1.25, 3.50),
    (1.50, 2.00),
    (1.50, 2.50),
    (1.50, 3.00),
    (1.50, 3.50),
    (1.75, 2.50),
    (1.75, 3.00),
    (1.75, 3.50),
]

def finite(x):
    try:
        return np.isfinite(float(x))
    except Exception:
        return False

def fixed_levels(r, horizon, sl_atr, tp_atr):
    close = float(r.Close)
    atr = float(r.ATR14)

    if not finite(close) or not finite(atr) or close <= 0 or atr <= 0:
        return None

    hold = 3 if horizon == "nextday" else 20
    trigger = 0.15 if horizon == "nextday" else 0.20

    return {
        "entry": close + trigger * atr,
        "sl": close - sl_atr * atr,
        "tp": close + tp_atr * atr,
        "hold": hold
    }

def simulate_fixed(g, i, horizon, sl_atr, tp_atr, cost):
    if i + 1 >= len(g):
        return None

    r = g.iloc[i]
    lv = fixed_levels(r, horizon, sl_atr, tp_atr)

    if lv is None:
        return None

    entry_level = lv["entry"]
    day = g.iloc[i + 1]

    if float(day.Open) >= entry_level:
        entry = float(day.Open)
    elif float(day.High) >= entry_level:
        entry = float(entry_level)
    else:
        return None

    mfe = -999.0
    mae = 999.0
    pnl = None
    exit_reason = None
    tp_day = None
    sl_day = None
    exit_day = None

    hold = int(lv["hold"])
    end = min(len(g), i + 1 + hold)

    for j in range(i + 1, end):
        d = g.iloc[j]
        hi = float(d.High)
        lo = float(d.Low)

        mfe = max(mfe, (hi / entry - 1) * 100)
        mae = min(mae, (lo / entry - 1) * 100)

        # Same-bar ambiguity: stop first, exactly as V3.4.
        if lo <= lv["sl"]:
            pnl = (lv["sl"] / entry - 1) * 100
            sl_day = j - (i + 1) + 1
            exit_day = j
            exit_reason = "SL"
            break

        if hi >= lv["tp"]:
            pnl = (lv["tp"] / entry - 1) * 100
            tp_day = j - (i + 1) + 1
            exit_day = j
            exit_reason = "TP"
            break

    if pnl is None:
        j = end - 1
        pnl = (float(g.iloc[j].Close) / entry - 1) * 100
        exit_day = j
        exit_reason = "TIME"

    pnl -= cost * 100

    return {
        "date": str(r.Date.date()),
        "code": str(r.StockCode),
        "pnl": float(pnl),
        "mfe": float(mfe),
        "mae": float(mae),
        "days": int(exit_day - (i + 1) + 1),
        "exit_reason": exit_reason,
        "tp_day": tp_day,
        "sl_day": sl_day
    }

def summarize(rows):
    if not rows:
        return {"n": 0}

    z = pd.DataFrame(rows)

    gains = z.loc[z.pnl > 0, "pnl"].sum()
    losses = abs(z.loc[z.pnl < 0, "pnl"].sum())
    pf = gains / losses if losses > 0 else None

    tp = z.tp_day.dropna()
    sl = z.sl_day.dropna()

    return {
        "n": int(len(z)),
        "win_rate_pct": round(float((z.pnl > 0).mean() * 100), 3),
        "expectancy_pct": round(float(z.pnl.mean()), 4),
        "median_pnl_pct": round(float(z.pnl.median()), 4),
        "profit_factor": None if pf is None else round(float(pf), 4),
        "median_mfe_pct": round(float(z.mfe.median()), 4),
        "median_mae_pct": round(float(z.mae.median()), 4),
        "median_duration_days": round(float(z.days.median()), 3),
        "tp_rate_pct": round(float(z.tp_day.notna().mean() * 100), 3),
        "sl_rate_pct": round(float(z.sl_day.notna().mean() * 100), 3),
        "time_rate_pct": round(float((z.exit_reason == "TIME").mean() * 100), 3),
        "median_tp_days": round(float(tp.median()), 3) if len(tp) else None,
        "median_sl_days": round(float(sl.median()), 3) if len(sl) else None
    }

def run_fixed(df, horizon, setup, sl_atr, tp_atr, cost, split_filter=None):
    rows = []

    for code, g in df.groupby("StockCode", sort=False):
        g = g.reset_index(drop=True)

        mask = g[setup].fillna(False) & g["LIQUID"].fillna(False)
        idx = np.where(mask.values)[0]

        for i in idx:
            r = g.iloc[i]

            if split_filter == "TRAIN" and r.Date > TRAIN_END:
                continue

            if split_filter == "TEST" and r.Date < TEST_START:
                continue

            x = simulate_fixed(
                g, i, horizon,
                sl_atr, tp_atr,
                cost
            )

            if x is not None:
                rows.append(x)

    return summarize(rows), rows

def run_baseline(df, horizon, cost, split_filter="TEST"):
    rows = []

    for code, g in df.groupby("StockCode", sort=False):
        g = g.reset_index(drop=True)

        mask = g["LIQUID"].fillna(False)
        idx = np.where(mask.values)[0]

        for i in idx:
            r = g.iloc[i]

            if split_filter == "TRAIN" and r.Date > TRAIN_END:
                continue

            if split_filter == "TEST" and r.Date < TEST_START:
                continue

            x = simulate_fixed(
                g, i, horizon,
                1.0,
                2.0,
                cost
            )

            if x is not None:
                rows.append(x)

    return summarize(rows)

def regime_name(g, i):
    r = g.iloc[i]

    close = float(r.Close)
    sma20 = float(r.SMA20) if "SMA20" in g.columns and finite(r.SMA20) else np.nan
    sma50 = float(r.SMA50) if "SMA50" in g.columns and finite(r.SMA50) else np.nan
    ret5 = float(r.RET5) if "RET5" in g.columns and finite(r.RET5) else 0.0
    atr = float(r.ATR14) if finite(r.ATR14) else np.nan

    if finite(atr):
        atr_pct = atr / close * 100 if close > 0 else np.nan
    else:
        atr_pct = np.nan

    if finite(sma20) and finite(sma50):
        if close > sma20 > sma50 and ret5 > 0:
            trend = "BULL"
        elif close < sma20 < sma50 and ret5 < 0:
            trend = "BEAR"
        else:
            trend = "SIDEWAYS"
    else:
        trend = "SIDEWAYS"

    # Relative volatility uses the stock's own recent ATR distribution.
    if "ATR14" in g.columns:
        recent = pd.to_numeric(g.ATR14, errors="coerce").iloc[max(0, i-60):i+1]
        med = float(recent.median()) if recent.notna().any() else np.nan
        if finite(med) and finite(atr) and atr > med * 1.25:
            vol = "HIGH_VOL"
        elif finite(med) and finite(atr) and atr < med * 0.80:
            vol = "LOW_VOL"
        else:
            vol = "NORMAL_VOL"
    else:
        vol = "NORMAL_VOL"

    return trend, vol

def regime_test(df, horizon, setup):
    buckets = {
        "BULL": [],
        "SIDEWAYS": [],
        "BEAR": [],
        "HIGH_VOL": [],
        "LOW_VOL": []
    }

    for code, g in df.groupby("StockCode", sort=False):
        g = g.reset_index(drop=True)

        mask = g[setup].fillna(False) & g["LIQUID"].fillna(False)
        idx = np.where(mask.values)[0]

        for i in idx:
            r = g.iloc[i]

            if r.Date < TEST_START:
                continue

            # Use the same fixed base policy for regime comparison.
            x = simulate_fixed(g, i, horizon, 1.0, 2.0, 0.002)

            if x is None:
                continue

            trend, vol = regime_name(g, i)

            if trend in buckets:
                buckets[trend].append(x)

            if vol in buckets:
                buckets[vol].append(x)

    return {k: summarize(v) for k, v in buckets.items()}

def cost_test(df, horizon, setup):
    out = {}

    for cost in COSTS:
        s, _ = run_fixed(
            df, horizon, setup,
            1.0, 2.0,
            cost,
            "TEST"
        )
        out[str(cost)] = s

    return out

def parameter_test(df, horizon, setup):
    out = {}

    for sl_atr, tp_atr in PARAM_GRID:
        key = f"SL{sl_atr:.2f}_TP{tp_atr:.2f}"

        s, _ = run_fixed(
            df, horizon, setup,
            sl_atr, tp_atr,
            0.002,
            "TEST"
        )

        out[key] = {
            "sl_atr": sl_atr,
            "tp_atr": tp_atr,
            **s
        }

    return out

def stability_score(parameter_results):
    valid = [
        v for v in parameter_results.values()
        if v.get("n", 0) >= 100
        and v.get("profit_factor") is not None
    ]

    if not valid:
        return {
            "tested": 0,
            "positive_expectancy": 0,
            "pf_above_1": 0,
            "positive_pct": 0.0,
            "pf_above_1_pct": 0.0
        }

    positive = sum(v["expectancy_pct"] > 0 for v in valid)
    pf1 = sum(v["profit_factor"] > 1 for v in valid)

    return {
        "tested": len(valid),
        "positive_expectancy": positive,
        "pf_above_1": pf1,
        "positive_pct": round(positive / len(valid) * 100, 2),
        "pf_above_1_pct": round(pf1 / len(valid) * 100, 2)
    }

def verdict(base, costs, params, regimes, baseline):
    pf = base.get("profit_factor")
    exp = base.get("expectancy_pct", 0)
    n = base.get("n", 0)

    cost02 = costs.get("0.002", {})
    cost05 = costs.get("0.005", {})

    st = stability_score(params)

    surviving_costs = 0
    for v in costs.values():
        if (
            v.get("n", 0) >= 100
            and v.get("profit_factor") is not None
            and v.get("expectancy_pct", 0) > 0
            and v.get("profit_factor", 0) > 1
        ):
            surviving_costs += 1

    robust_regimes = 0
    for k in ["BULL", "SIDEWAYS", "BEAR"]:
        v = regimes.get(k, {})
        if (
            v.get("n", 0) >= 100
            and v.get("profit_factor") is not None
            and v.get("expectancy_pct", 0) > 0
        ):
            robust_regimes += 1

    baseline_exp = baseline.get("expectancy_pct", 0)
    lift = exp - baseline_exp

    # Deliberately conservative classification.
    if (
        n >= 300
        and exp > 0
        and pf is not None
        and pf > 1.05
        and st["positive_pct"] >= 60
        and st["pf_above_1_pct"] >= 60
        and surviving_costs >= 3
        and robust_regimes >= 2
        and lift > 0
    ):
        label = "ROBUST"
    elif (
        n >= 300
        and exp > 0
        and pf is not None
        and pf > 1.0
        and (
            st["positive_pct"] >= 40
            or surviving_costs >= 2
            or lift > 0
        )
    ):
        label = "FRAGILE"
    else:
        label = "INCONCLUSIVE"

    return {
        "label": label,
        "base_expectancy_pct": exp,
        "base_pf": pf,
        "sample_size": n,
        "parameter_stability": st,
        "positive_cost_survivors": surviving_costs,
        "positive_trend_regimes": robust_regimes,
        "baseline_expectancy_pct": baseline_exp,
        "baseline_lift_pct": round(lift, 4),
        "cost_0_2": cost02,
        "cost_0_5": cost05
    }

print("=" * 70)
print("V3.5 ROBUSTNESS LAB")
print("=" * 70)

print("\nLoading V3.2 data/indicators...")
raw = v32.load_data()

df = pd.concat(
    [v32.prepare(g) for _, g in raw.groupby("StockCode", sort=False)],
    ignore_index=True
)

df["Date"] = pd.to_datetime(df["Date"])
df = df.sort_values(["StockCode", "Date"]).reset_index(drop=True)

print(
    f"Prepared rows={len(df):,} | "
    f"stocks={df.StockCode.nunique():,} | "
    f"{df.Date.min().date()} -> {df.Date.max().date()}"
)

results = {
    "meta": {
        "train_end": str(TRAIN_END.date()),
        "test_start": str(TEST_START.date()),
        "costs": COSTS,
        "parameter_grid": [
            {"sl_atr": a, "tp_atr": b}
            for a, b in PARAM_GRID
        ],
        "method": "V3.4 simulator baseline + robustness layers",
        "same_bar_rule": "STOP_FIRST",
        "intraday_data": False
    },
    "targets": {}
}

for horizon, setup in ROBUSTNESS_TARGETS:

    print("\n" + "=" * 70)
    print(f"{horizon.upper()} / {setup}")
    print("=" * 70)

    base, _ = run_fixed(
        df,
        horizon,
        setup,
        1.0,
        2.0,
        0.002,
        "TEST"
    )

    print(
        f"BASE      n={base.get('n',0):5} "
        f"exp={base.get('expectancy_pct',0):7.3f}% "
        f"PF={base.get('profit_factor')} "
        f"win={base.get('win_rate_pct',0):6.2f}%"
    )

    costs = cost_test(df, horizon, setup)

    print("\nCOST SENSITIVITY")
    for c, v in costs.items():
        print(
            f"cost={float(c)*100:4.1f}% "
            f"n={v.get('n',0):5} "
            f"exp={v.get('expectancy_pct',0):7.3f}% "
            f"PF={v.get('profit_factor')} "
            f"win={v.get('win_rate_pct',0):6.2f}%"
        )

    params = parameter_test(df, horizon, setup)
    st = stability_score(params)

    print("\nPARAMETER ROBUSTNESS")
    print(
        f"tested={st['tested']} | "
        f"positive_exp={st['positive_pct']:.1f}% | "
        f"PF>1={st['pf_above_1_pct']:.1f}%"
    )

    # Show the best and worst parameter combinations, but DO NOT
    # select them as production parameters.
    valid_params = [
        (k, v) for k, v in params.items()
        if v.get("n", 0) >= 100
        and v.get("profit_factor") is not None
    ]

    valid_params.sort(
        key=lambda x: x[1].get("expectancy_pct", -999),
        reverse=True
    )

    print("Top parameter cells:")
    for k, v in valid_params[:5]:
        print(
            f"  {k:<18} "
            f"n={v['n']:5} "
            f"exp={v['expectancy_pct']:7.3f}% "
            f"PF={v['profit_factor']}"
        )

    print("\nREGIME TEST")
    regimes = regime_test(df, horizon, setup)

    for k, v in regimes.items():
        print(
            f"{k:<10} "
            f"n={v.get('n',0):5} "
            f"exp={v.get('expectancy_pct',0):7.3f}% "
            f"PF={v.get('profit_factor')} "
            f"win={v.get('win_rate_pct',0):6.2f}%"
        )

    print("\nALL_LIQUID BASELINE")
    baseline = run_baseline(
        df,
        horizon,
        0.002,
        "TEST"
    )

    print(
        f"n={baseline.get('n',0):5} "
        f"exp={baseline.get('expectancy_pct',0):7.3f}% "
        f"PF={baseline.get('profit_factor')} "
        f"win={baseline.get('win_rate_pct',0):6.2f}%"
    )

    vd = verdict(
        base,
        costs,
        params,
        regimes,
        baseline
    )

    print("\nVERDICT")
    print(
        f"{vd['label']} | "
        f"baseline lift={vd['baseline_lift_pct']:+.3f}% | "
        f"cost survivors={vd['positive_cost_survivors']} | "
        f"trend regimes={vd['positive_trend_regimes']}"
    )

    results["targets"][f"{horizon}|{setup}"] = {
        "base": base,
        "cost_sensitivity": costs,
        "parameter_robustness": params,
        "parameter_stability": st,
        "regimes": regimes,
        "all_liquid_baseline": baseline,
        "verdict": vd
    }

os.makedirs(os.path.dirname(OUT), exist_ok=True)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(
        results,
        f,
        ensure_ascii=False,
        indent=2,
        default=lambda x: None
    )

print("\n" + "=" * 70)
print(f"V3.5 OK -> {OUT}")
print("=" * 70)
