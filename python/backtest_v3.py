import json
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "timeseries" / "stock_summary"
OUT = ROOT / "data" / "backtest_v3_trade_management.json"


def load_data():
    files = sorted(DATA_DIR.glob("date=*.parquet"))
    if not files:
        raise RuntimeError(f"Tidak ada parquet: {DATA_DIR}")

    parts = []

    for f in files:
        x = pd.read_parquet(f)

        mp = {}
        for c in x.columns:
            k = str(c).strip().lower().replace("_", "").replace(" ", "")
            if k == "stockcode":
                mp[c] = "StockCode"
            elif k == "date":
                mp[c] = "Date"
            elif k == "openprice":
                mp[c] = "Open"
            elif k == "open":
                mp[c] = "Open"
            elif k == "high":
                mp[c] = "High"
            elif k == "low":
                mp[c] = "Low"
            elif k == "close":
                mp[c] = "Close"
            elif k == "volume":
                mp[c] = "Volume"
            elif k == "value":
                mp[c] = "Value"
            elif k == "foreignbuy":
                mp[c] = "ForeignBuy"
            elif k == "foreignsell":
                mp[c] = "ForeignSell"

        x = x.rename(columns=mp)

        required = ["StockCode", "Date", "Open", "High", "Low", "Close"]
        missing = [c for c in required if c not in x.columns]
        if missing:
            raise RuntimeError(f"{f.name}: kolom kurang {missing}")

        for c in ["Open", "High", "Low", "Close", "Volume",
                  "Value", "ForeignBuy", "ForeignSell"]:
            if c not in x.columns:
                x[c] = 0.0
            x[c] = pd.to_numeric(x[c], errors="coerce")

        x["StockCode"] = x["StockCode"].astype(str).str.upper().str.strip()
        x["Date"] = pd.to_datetime(x["Date"], errors="coerce")

        parts.append(x)

    df = pd.concat(parts, ignore_index=True)

    df = (
        df.dropna(subset=["StockCode", "Date", "Close"])
          .sort_values(["StockCode", "Date"])
          .drop_duplicates(["StockCode", "Date"], keep="last")
          .reset_index(drop=True)
    )

    return df


def prepare(g):
    g = g.sort_values("Date").copy()

    c = g["Close"]
    h = g["High"]
    l = g["Low"]
    o = g["Open"]
    v = g["Volume"]

    pc = c.shift(1)

    tr = pd.concat(
        [
            h - l,
            (h - pc).abs(),
            (l - pc).abs(),
        ],
        axis=1
    ).max(axis=1)

    g["ATR14"] = tr.rolling(14, min_periods=14).mean()

    for n in [5, 20, 50]:
        g[f"SMA{n}"] = c.rolling(n, min_periods=n).mean()

    g["VOL20"] = v.rolling(20, min_periods=20).mean()
    g["RVOL"] = v / g["VOL20"].replace(0, np.nan)

    g["RET1"] = c.pct_change() * 100
    g["RET5"] = c.pct_change(5) * 100

    g["HIGH20"] = h.rolling(20, min_periods=20).max()
    g["LOW20"] = l.rolling(20, min_periods=20).min()

    rng = (h - l).replace(0, np.nan)

    g["CLOSE_LOC"] = (c - l) / rng
    g["UPPER_WICK"] = (h - np.maximum(o, c)) / rng
    g["LOWER_WICK"] = (np.minimum(o, c) - l) / rng

    foreign_net = (
        g["ForeignBuy"].fillna(0) -
        g["ForeignSell"].fillna(0)
    )

    g["FNET5"] = foreign_net.rolling(5, min_periods=5).sum()
    g["FNET10"] = foreign_net.rolling(10, min_periods=10).sum()

    g["SUPDIST_ATR"] = (
        (c - g["LOW20"]) /
        g["ATR14"].replace(0, np.nan)
    )

    g["UPTREND"] = (
        (c > g["SMA20"]) &
        (g["SMA20"] > g["SMA50"]) &
        (g["SMA20"].diff() > 0)
    )

    g["DOWNTREND"] = (
        (c < g["SMA20"]) &
        (g["SMA20"] < g["SMA50"])
    )

    g["ABSORPTION"] = (
        (g["RVOL"] >= 1.5) &
        (g["CLOSE_LOC"] >= 0.65) &
        (g["RET1"].abs() <= 1.5) &
        (g["SUPDIST_ATR"] <= 8)
    )

    g["MOMENTUM"] = (
        (g["RVOL"] >= 1.5) &
        (g["RET1"] >= 1.0) &
        (g["CLOSE_LOC"] >= 0.65) &
        (c >= g["SMA5"])
    )

    g["PULLBACK"] = (
        g["UPTREND"] &
        (g["RET5"] < 0) &
        (g["SUPDIST_ATR"] <= 6) &
        (g["CLOSE_LOC"] >= 0.45) &
        (g["RVOL"] >= 0.8)
    )

    g["REVERSAL"] = (
        (g["DOWNTREND"] | (g["SUPDIST_ATR"] <= 3)) &
        (g["LOWER_WICK"] >= 0.25) &
        (g["CLOSE_LOC"] >= 0.55) &
        (g["RET1"] >= -1.0) &
        (g["RVOL"] >= 1.0)
    )

    g["FOREIGN"] = (
        (g["FNET5"] > 0) &
        (g["FNET10"] > 0)
    )

    g["LIQUID"] = (
        g["Value"].rolling(20, min_periods=10).median() >=
        1_000_000_000
    )

    g["MOMENTUM_RVOL2"] = g["MOMENTUM"] & (g["RVOL"] >= 2)
    g["MOMENTUM_FOREIGN"] = g["MOMENTUM"] & g["FOREIGN"]
    g["MOMENTUM_SUPPORT"] = g["MOMENTUM"] & (g["SUPDIST_ATR"] <= 5)

    g["ABSORPTION_RVOL2"] = g["ABSORPTION"] & (g["RVOL"] >= 2)
    g["ABSORPTION_FOREIGN"] = g["ABSORPTION"] & g["FOREIGN"]
    g["ABSORPTION_SUPPORT"] = g["ABSORPTION"] & (g["SUPDIST_ATR"] <= 5)

    g["REVERSAL_RVOL2"] = g["REVERSAL"] & (g["RVOL"] >= 2)
    g["REVERSAL_FOREIGN"] = g["REVERSAL"] & g["FOREIGN"]
    g["REVERSAL_ABSORPTION"] = g["REVERSAL"] & g["ABSORPTION"]

    g["FOREIGN_RVOL2"] = g["FOREIGN"] & (g["RVOL"] >= 2)
    g["FOREIGN_SUPPORT"] = g["FOREIGN"] & (g["SUPDIST_ATR"] <= 5)

    return g


def tick_size(price):
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def tick(price):
    if not np.isfinite(price):
        return np.nan
    t = tick_size(price)
    return round(price / t) * t


def make_levels(row, mode):
    close = float(row["Close"])
    atr = float(row["ATR14"])

    if not np.isfinite(close) or not np.isfinite(atr) or atr <= 0:
        return None

    if mode == "nextday":
        entry = close * 1.002
        cl1 = close - 0.75 * atr
        cl2 = close - 1.25 * atr
        cl3 = max(close - 1.50 * atr, close * 0.97)

        tp1 = close + 0.75 * atr
        tp2 = close + 1.50 * atr
        tp3 = close + 2.25 * atr

        max_hold = 2

    else:
        support = float(row["LOW20"])

        if not np.isfinite(support):
            support = close - atr

        entry = close * 1.003

        cl1 = close - 0.75 * atr
        cl2 = close - 1.25 * atr
        cl3 = min(
            close - 1.75 * atr,
            support * 0.99
        )

        tp1 = close + 1.25 * atr
        tp2 = close + 2.25 * atr
        tp3 = close + 3.25 * atr

        max_hold = 20

    return {
        "entry": tick(entry),
        "cl1": tick(cl1),
        "cl2": tick(cl2),
        "cl3": tick(cl3),
        "tp1": tick(tp1),
        "tp2": tick(tp2),
        "tp3": tick(tp3),
        "max_hold": max_hold,
    }


def simulate(g, signal_idx, mode):
    levels = make_levels(g.iloc[signal_idx], mode)

    if levels is None:
        return {
            "status": "INVALID",
            "pnl_pct": np.nan,
        }

    start = signal_idx + 1
    end = min(
        len(g) - 1,
        start + levels["max_hold"] - 1
    )

    if start > end:
        return {
            "status": "INVALID",
            "pnl_pct": np.nan,
        }

    entry_px = None
    entry_idx = None

    for j in range(start, end + 1):
        row = g.iloc[j]
        op = float(row["Open"])
        hi = float(row["High"])
        lo = float(row["Low"])

        if op >= levels["entry"]:
            entry_px = op
            entry_idx = j
            break

        if hi >= levels["entry"]:
            entry_px = levels["entry"]
            entry_idx = j
            break

    if entry_px is None:
        return {
            "status": "NO_ENTRY",
            "pnl_pct": np.nan,
            "duration": 0,
            "exit_reason": "NO_ENTRY",
            "entry_px": None,
            "exit_px": None,
            "ambiguous": False,
        }

    exit_px = None
    exit_reason = None
    exit_idx = None
    ambiguous = False

    for j in range(entry_idx, end + 1):
        row = g.iloc[j]

        hi = float(row["High"])
        lo = float(row["Low"])
        cl = float(row["Close"])

        stop_hit = lo <= levels["cl1"]
        tp_hit = hi >= levels["tp1"]

        if stop_hit and tp_hit:
            exit_px = levels["cl1"]
            exit_reason = "CL1_AMBIGUOUS"
            exit_idx = j
            ambiguous = True
            break

        if stop_hit:
            exit_px = levels["cl1"]
            exit_reason = "CL1"
            exit_idx = j
            break

        if tp_hit:
            exit_px = levels["tp1"]
            exit_reason = "TP1"
            exit_idx = j
            break

        if j == end:
            exit_px = cl
            exit_reason = "TIME_STOP"
            exit_idx = j

    if exit_px is None:
        exit_px = float(g.iloc[end]["Close"])
        exit_reason = "TIME_STOP"
        exit_idx = end

    pnl = (exit_px / entry_px - 1) * 100
    duration = exit_idx - entry_idx + 1

    return {
        "status": "TRADE",
        "pnl_pct": pnl,
        "duration": duration,
        "exit_reason": exit_reason,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "ambiguous": ambiguous,
    }


def summarize(rows):
    if not rows:
        return {
            "n": 0,
            "no_entry": 0,
            "win_rate_pct": None,
            "median_pnl_pct": None,
            "mean_pnl_pct": None,
            "expectancy_pct": None,
            "profit_factor": None,
            "max_drawdown_pct": None,
            "median_duration": None,
            "tp1_rate_pct": None,
            "cl1_rate_pct": None,
            "time_stop_rate_pct": None,
            "ambiguous_rate_pct": None,
        }

    df = pd.DataFrame(rows)

    trades = df[df["status"] == "TRADE"].copy()
    no_entry = int((df["status"] == "NO_ENTRY").sum())

    if trades.empty:
        return {
            "n": 0,
            "signals": len(df),
            "no_entry": no_entry,
            "no_entry_rate_pct": no_entry / len(df) * 100,
        }

    pnl = trades["pnl_pct"].astype(float)

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = float("inf")
    else:
        pf = 0.0

    equity = (1 + pnl / 100).cumprod()
    peak = equity.cummax()
    dd = (equity / peak - 1) * 100

    reasons = trades["exit_reason"].astype(str)

    return {
        "n": int(len(trades)),
        "signals": int(len(df)),
        "no_entry": no_entry,
        "no_entry_rate_pct": round(no_entry / len(df) * 100, 2),

        "win_rate_pct": round((pnl > 0).mean() * 100, 2),
        "median_pnl_pct": round(pnl.median(), 4),
        "mean_pnl_pct": round(pnl.mean(), 4),

        "avg_win_pct": round(wins.mean(), 4) if len(wins) else None,
        "avg_loss_pct": round(losses.mean(), 4) if len(losses) else None,

        "expectancy_pct": round(pnl.mean(), 4),
        "profit_factor": round(pf, 4) if np.isfinite(pf) else "INF",

        "max_drawdown_pct": round(dd.min(), 4),

        "median_duration": round(trades["duration"].median(), 2),
        "p25_duration": round(trades["duration"].quantile(0.25), 2),
        "p75_duration": round(trades["duration"].quantile(0.75), 2),

        "tp1_rate_pct": round(
            (reasons == "TP1").mean() * 100, 2
        ),

        "cl1_rate_pct": round(
            reasons.str.startswith("CL1").mean() * 100, 2
        ),

        "time_stop_rate_pct": round(
            (reasons == "TIME_STOP").mean() * 100, 2
        ),

        "ambiguous_rate_pct": round(
            trades["ambiguous"].mean() * 100, 2
        ),
    }


def main():
    print("Loading historical data...")
    df = load_data()

    print(
        f"DATA: {len(df):,} rows | "
        f"{df['StockCode'].nunique():,} stocks | "
        f"{df['Date'].min().date()} -> {df['Date'].max().date()}"
    )

    print("Preparing indicators per stock...")

    prepared = []

    for code, g in df.groupby("StockCode", sort=False):
        x = prepare(g)
        prepared.append(x)

    df = pd.concat(prepared, ignore_index=True)

    setups = [
        "ALL_LIQUID",
        "MOMENTUM",
        "MOMENTUM_RVOL2",
        "MOMENTUM_FOREIGN",
        "MOMENTUM_SUPPORT",
        "ABSORPTION",
        "ABSORPTION_RVOL2",
        "ABSORPTION_FOREIGN",
        "ABSORPTION_SUPPORT",
        "REVERSAL",
        "REVERSAL_RVOL2",
        "REVERSAL_FOREIGN",
        "REVERSAL_ABSORPTION",
        "PULLBACK",
        "FOREIGN",
        "FOREIGN_RVOL2",
        "FOREIGN_SUPPORT",
    ]

    results = {
        "meta": {
            "version": "V3.1",
            "engine": "NEXT_DAY_AND_SWING_TRADE_MANAGEMENT",
            "data_frequency": "DAILY",
            "intraday": False,
            "stocks": int(df["StockCode"].nunique()),
            "rows": int(len(df)),
            "first_date": str(df["Date"].min()),
            "last_date": str(df["Date"].max()),
            "entry_rule": "T+1 executable entry",
            "no_entry_excluded_from_pnl": True,
            "same_bar_stop_target_rule": "STOP_FIRST",
            "fees_slippage": False,
        },
        "results": {},
    }

    for mode in ["nextday", "swing"]:
        print(f"\n=== {mode.upper()} ===")

        ranked = []

        for setup in setups:
            trades = []

            for code, g in df.groupby("StockCode", sort=False):
                g = g.reset_index(drop=True)

                if setup == "ALL_LIQUID":
                    mask = g["LIQUID"]
                else:
                    mask = g[setup]

                idxs = np.flatnonzero(
                    mask.fillna(False).to_numpy()
                )

                for i in idxs:
                    i = int(i)

                    if i < 60:
                        continue

                    row = g.iloc[i]

                    if not np.isfinite(row["ATR14"]):
                        continue

                    r = simulate(g, i, mode)

                    if r["status"] in ["TRADE", "NO_ENTRY"]:
                        r["StockCode"] = code
                        r["SignalDate"] = str(row["Date"].date())
                        trades.append(r)

            summary = summarize(trades)
            summary["setup"] = setup

            ranked.append(summary)

        ranked.sort(
            key=lambda x: (
                -999999 if x.get("expectancy_pct") is None
                else x["expectancy_pct"],
                -999999 if x.get("profit_factor") in [None, "INF"]
                else x["profit_factor"],
            ),
            reverse=True,
        )

        results["results"][mode] = ranked

        for x in ranked:
            print(
                f'{x["setup"]:24s} '
                f'n={x.get("n",0):6d} '
                f'noentry={x.get("no_entry",0):6d} '
                f'win={x.get("win_rate_pct")} '
                f'exp={x.get("expectancy_pct")} '
                f'PF={x.get("profit_factor")} '
                f'TP1={x.get("tp1_rate_pct")} '
                f'CL={x.get("cl1_rate_pct")} '
                f'DD={x.get("max_drawdown_pct")} '
                f'dur={x.get("median_duration")}'
            )

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print(f"\nBACKTEST V3.1 OK -> {OUT}")


if __name__ == "__main__":
    main()
