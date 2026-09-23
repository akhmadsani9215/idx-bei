from pathlib import Path
import json, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "timeseries" / "stock_summary"
OUT = ROOT / "data" / "backtest_v32_diagnostic.json"

ROUND_TRIP_COSTS = [0.0, 0.001, 0.002, 0.003]
MAX_HOLD_NEXTDAY = 3
MAX_HOLD_SWING = 20

def load_data():
    files = sorted(DATA.rglob("*.parquet"))
    print(f"FOUND PARQUET: {len(files):,} files")
    if not files:
        raise RuntimeError(f"Tidak menemukan parquet di: {DATA}")

    frames=[]
    errors=[]

    for n,f in enumerate(files,1):
        try:
            x=pd.read_parquet(f)
            if len(x):
                frames.append(x)
            if n%50==0 or n==len(files):
                print(f"READ: {n:,}/{len(files):,} | rows={sum(len(z) for z in frames):,}")
        except Exception as e:
            errors.append((str(f),repr(e)))

    if errors:
        print(f"READ ERRORS: {len(errors):,}")
        for f,e in errors[:10]:
            print(f"  {f} -> {e}")

    if not frames:
        raise RuntimeError("Semua parquet gagal dibaca.")

    df=pd.concat(frames,ignore_index=True)

    if "OpenPrice" in df.columns and "Open" not in df.columns:
        df["Open"]=df["OpenPrice"]

    need=[
        "StockCode","Date","Open","High","Low","Close",
        "Volume","Value","ForeignBuy","ForeignSell"
    ]

    miss=[c for c in need if c not in df.columns]
    if miss:
        raise RuntimeError(f"Kolom kurang: {miss}")

    for c in need:
        if c not in ("StockCode","Date"):
            df[c]=pd.to_numeric(df[c],errors="coerce")

    df["Date"]=pd.to_datetime(df["Date"],errors="coerce")

    print(f"BEFORE CLEAN: {len(df):,} rows | Date valid={df['Date'].notna().sum():,} | StockCode valid={df['StockCode'].notna().sum():,}")

    df=df.dropna(subset=[
        "StockCode","Date","Open","High","Low","Close"
    ])

    df=df.sort_values(
        ["StockCode","Date"]
    ).reset_index(drop=True)

    return df
def prepare(g):
    g = g.sort_values("Date").copy()
    c = g["Close"]
    h = g["High"]
    l = g["Low"]
    v = g["Volume"].fillna(0)
    prev = c.shift(1)

    tr = pd.concat([
        h-l,
        (h-prev).abs(),
        (l-prev).abs()
    ], axis=1).max(axis=1)

    g["ATR14"] = tr.rolling(14, min_periods=14).mean()
    g["SMA5"] = c.rolling(5).mean()
    g["SMA20"] = c.rolling(20).mean()
    g["SMA50"] = c.rolling(50).mean()
    g["VOL20"] = v.rolling(20).mean()
    g["RVOL"] = v / g["VOL20"].replace(0,np.nan)
    g["RET1"] = c.pct_change()
    g["RET5"] = c.pct_change(5)
    g["HIGH20"] = h.rolling(20).max().shift(1)
    g["LOW20"] = l.rolling(20).min().shift(1)
    g["FNET1"] = g["ForeignBuy"].fillna(0) - g["ForeignSell"].fillna(0)
    g["FNET5"] = g["FNET1"].rolling(5).sum()
    g["FNET10"] = g["FNET1"].rolling(10).sum()
    rng = (h-l).replace(0,np.nan)
    g["CLOSE_LOC"] = (c-l)/rng
    g["UPPER_WICK"] = (h-np.maximum(g["Open"],c))/rng
    g["LOWER_WICK"] = (np.minimum(g["Open"],c)-l)/rng
    g["DIST_SUPPORT_ATR"] = (c-g["LOW20"])/g["ATR14"].replace(0,np.nan)
    g["ATR_PCT"] = g["ATR14"]/c.replace(0,np.nan)
    g["UPTREND"] = (c>g["SMA20"]) & (g["SMA20"]>g["SMA50"])
    g["DOWNTREND"] = (c<g["SMA20"]) & (g["SMA20"]<g["SMA50"])
    g["BREAKOUT"] = c > g["HIGH20"]
    g["ABSORPTION"] = (
        (g["RET1"].abs()<0.015) &
        (g["RVOL"]>1.2) &
        (g["CLOSE_LOC"]>0.55) &
        (g["LOWER_WICK"]>g["UPPER_WICK"])
    )
    g["MOMENTUM"] = (
        (g["RET1"]>0.01) &
        (g["RVOL"]>1.2) &
        (g["CLOSE_LOC"]>0.65)
    )
    g["PULLBACK"] = (
        (c>g["SMA20"]) &
        (g["RET5"]<0) &
        (g["DIST_SUPPORT_ATR"].abs()<1.5) &
        (g["CLOSE_LOC"]>0.45)
    )
    g["REVERSAL"] = (
        (g["RET1"]<0) &
        (g["LOWER_WICK"]>0.30) &
        (g["CLOSE_LOC"]>0.55)
    )
    g["FOREIGN"] = g["FNET5"]>0
    g["LIQUID"] = g["Value"].rolling(20).mean()>=1_000_000_000

    g["FOREIGN_SUPPORT"] = g["FOREIGN"] & (g["DIST_SUPPORT_ATR"].abs()<1.5)
    g["MOMENTUM_FOREIGN"] = g["MOMENTUM"] & g["FOREIGN"]
    g["MOMENTUM_RVOL2"] = g["MOMENTUM"] & (g["RVOL"]>=2)
    g["ABSORPTION_FOREIGN"] = g["ABSORPTION"] & g["FOREIGN"]
    g["ABSORPTION_RVOL2"] = g["ABSORPTION"] & (g["RVOL"]>=2)
    g["REVERSAL_FOREIGN"] = g["REVERSAL"] & g["FOREIGN"]
    g["REVERSAL_RVOL2"] = g["REVERSAL"] & (g["RVOL"]>=2)

    return g

def tick(px):
    if px < 200: return 1
    if px < 500: return 2
    if px < 2000: return 5
    if px < 5000: return 10
    return 25

def round_tick(px):
    t=tick(px)
    return round(px/t)*t

def levels(row, horizon):
    px=float(row.Close)
    atr=float(row.ATR14)
    if not np.isfinite(atr) or atr<=0:
        return None

    if horizon=="nextday":
        entry=px+0.15*atr
        cl1=px-0.75*atr
        cl2=px-1.15*atr
        cl3=px-1.50*atr
        tp1=px+0.75*atr
        tp2=px+1.50*atr
        tp3=px+2.25*atr
        hold=MAX_HOLD_NEXTDAY
    else:
        support=float(row.LOW20) if np.isfinite(row.LOW20) else px-atr
        entry=px+0.20*atr
        cl1=px-0.75*atr
        cl2=px-1.25*atr
        cl3=min(px-1.75*atr,support*0.99)
        tp1=px+1.25*atr
        tp2=px+2.25*atr
        tp3=px+3.25*atr
        hold=MAX_HOLD_SWING

    return {
        "entry":round_tick(entry),
        "cl1":round_tick(cl1),
        "cl2":round_tick(cl2),
        "cl3":round_tick(cl3),
        "tp1":round_tick(tp1),
        "tp2":round_tick(tp2),
        "tp3":round_tick(tp3),
        "hold":hold
    }

def simulate(g, i, horizon, cost):
    if i+1 >= len(g):
        return None

    r=g.iloc[i]
    lv=levels(r,horizon)
    if not lv:
        return None

    e=lv["entry"]
    day=g.iloc[i+1]

    if day["Open"]>=e:
        entry=float(day["Open"])
    elif day["High"]>=e:
        entry=float(e)
    else:
        return {
            "status":"NO_ENTRY",
            "date":str(r.Date.date()),
            "code":str(r.StockCode)
        }

    qty=[0.40,0.30,0.30]
    remaining=1.0
    pnl=0.0
    mfe=-999.0
    mae=999.0
    exit_day=None
    exit_reason=None
    tp_hits=[]
    cl_hits=[]

    for j in range(i+1,min(len(g),i+1+lv["hold"])):
        d=g.iloc[j]
        hi=float(d.High)
        lo=float(d.Low)

        mfe=max(mfe,(hi/entry-1)*100)
        mae=min(mae,(lo/entry-1)*100)

        # Conservative ordering: stop before target when both occur.
        if lo<=lv["cl3"]:
            pnl += remaining*(lv["cl3"]/entry-1)*100
            cl_hits.append(3)
            remaining=0
            exit_day=j
            exit_reason="CL3"
            break

        if lo<=lv["cl2"] and remaining>0.0:
            q=min(0.30,remaining)
            pnl += q*(lv["cl2"]/entry-1)*100
            remaining-=q
            cl_hits.append(2)

        if lo<=lv["cl1"] and remaining>0.0:
            q=min(0.40,remaining)
            pnl += q*(lv["cl1"]/entry-1)*100
            remaining-=q
            cl_hits.append(1)

        if hi>=lv["tp1"] and remaining>0:
            q=min(0.40,remaining)
            pnl += q*(lv["tp1"]/entry-1)*100
            remaining-=q
            tp_hits.append(1)

        if hi>=lv["tp2"] and remaining>0:
            q=min(0.30,remaining)
            pnl += q*(lv["tp2"]/entry-1)*100
            remaining-=q
            tp_hits.append(2)

        if hi>=lv["tp3"] and remaining>0:
            q=remaining
            pnl += q*(lv["tp3"]/entry-1)*100
            remaining=0
            tp_hits.append(3)
            exit_day=j
            exit_reason="TP3"
            break

        if remaining<=0:
            exit_day=j
            exit_reason="LADDER_DONE"
            break

    if remaining>0:
        d=g.iloc[min(len(g)-1,i+lv["hold"])]
        pnl += remaining*(float(d.Close)/entry-1)*100
        exit_day=min(len(g)-1,i+lv["hold"])
        exit_reason="TIME"

    pnl -= cost*100
    return {
        "status":"TRADE",
        "date":str(r.Date.date()),
        "code":str(r.StockCode),
        "entry":entry,
        "pnl":pnl,
        "mfe":mfe,
        "mae":mae,
        "days":int(exit_day-(i+1)+1),
        "tp_hits":tp_hits,
        "cl_hits":cl_hits,
        "exit_reason":exit_reason,
        "rvol":float(r.RVOL) if np.isfinite(r.RVOL) else np.nan,
        "atr_pct":float(r.ATR_PCT) if np.isfinite(r.ATR_PCT) else np.nan,
        "fnet5":float(r.FNET5) if np.isfinite(r.FNET5) else np.nan,
        "dist_support":float(r.DIST_SUPPORT_ATR) if np.isfinite(r.DIST_SUPPORT_ATR) else np.nan,
        "uptrend":bool(r.UPTREND),
        "downtrend":bool(r.DOWNTREND),
        "close_loc":float(r.CLOSE_LOC) if np.isfinite(r.CLOSE_LOC) else np.nan
    }

def run():
    print("Loading historical data...")
    df=load_data()
    print(f"DATA: {len(df):,} rows | {df.StockCode.nunique():,} stocks | {df.Date.min().date()} -> {df.Date.max().date()}")
    print("Preparing indicators...")
    df=pd.concat([prepare(g) for _,g in df.groupby("StockCode",sort=False)],ignore_index=True)

    setups=[
        "FOREIGN_SUPPORT","FOREIGN","MOMENTUM_FOREIGN","MOMENTUM_RVOL2",
        "ABSORPTION_FOREIGN","ABSORPTION_RVOL2","REVERSAL_FOREIGN",
        "REVERSAL_RVOL2","PULLBACK","MOMENTUM","ABSORPTION","REVERSAL"
    ]

    results={}
    trades_all=[]

    for horizon in ["nextday","swing"]:
        results[horizon]={}
        for setup in setups:
            rows=[]
            for code,g in df.groupby("StockCode",sort=False):
                mask=g[setup].fillna(False) & g["LIQUID"].fillna(False)
                idx=np.where(mask.values)[0]
                for i in idx:
                    x=simulate(g,i,horizon,0.002)
                    if x and x["status"]=="TRADE":
                        x["setup"]=setup
                        x["horizon"]=horizon
                        rows.append(x)

            z=pd.DataFrame(rows)
            if len(z)==0:
                continue

            z=z.replace([np.inf,-np.inf],np.nan)
            win=(z.pnl>0).mean()*100
            avg=z.pnl.mean()
            med=z.pnl.median()
            gains=z.loc[z.pnl>0,"pnl"].sum()
            losses=abs(z.loc[z.pnl<0,"pnl"].sum())
            pf=gains/losses if losses else None

            results[horizon][setup]={
                "n":int(len(z)),
                "win_rate_pct":round(float(win),3),
                "expectancy_pct":round(float(avg),4),
                "median_pnl_pct":round(float(med),4),
                "profit_factor":None if pf is None else round(float(pf),4),
                "median_mfe_pct":round(float(z.mfe.median()),4),
                "median_mae_pct":round(float(z.mae.median()),4),
                "median_duration":round(float(z.days.median()),2),
                "tp1_rate_pct":round(float(z.tp_hits.apply(lambda x:1 in x).mean()*100),3),
                "tp2_rate_pct":round(float(z.tp_hits.apply(lambda x:2 in x).mean()*100),3),
                "tp3_rate_pct":round(float(z.tp_hits.apply(lambda x:3 in x).mean()*100),3),
                "cl1_rate_pct":round(float(z.cl_hits.apply(lambda x:1 in x).mean()*100),3),
                "cl2_rate_pct":round(float(z.cl_hits.apply(lambda x:2 in x).mean()*100),3),
                "cl3_rate_pct":round(float(z.cl_hits.apply(lambda x:3 in x).mean()*100),3)
            }

            trades_all.append(z)

            # condition matrix
            conds={
                "UPTREND":z.uptrend,
                "DOWNTREND":z.downtrend,
                "RVOL_LT_1":z.rvol<1,
                "RVOL_1_1_5":(z.rvol>=1)&(z.rvol<1.5),
                "RVOL_1_5_2":(z.rvol>=1.5)&(z.rvol<2),
                "RVOL_2_3":(z.rvol>=2)&(z.rvol<3),
                "RVOL_GE_3":z.rvol>=3,
                "ATR_LT_1P5":z.atr_pct<0.015,
                "ATR_1P5_3":(z.atr_pct>=0.015)&(z.atr_pct<0.03),
                "ATR_GE_3":z.atr_pct>=0.03,
                "FOREIGN_POS":z.fnet5>0,
                "FOREIGN_NEG":z.fnet5<=0,
                "SUPPORT_LT_1ATR":z.dist_support.abs()<1,
                "SUPPORT_1_2ATR":(z.dist_support.abs()>=1)&(z.dist_support.abs()<2),
                "CLOSE_HIGH":z.close_loc>=0.70,
                "CLOSE_MID":(z.close_loc>=0.40)&(z.close_loc<0.70),
                "CLOSE_LOW":z.close_loc<0.40
            }
            matrix=[]
            for name,m in conds.items():
                q=z[m.fillna(False)]
                if len(q)>=100:
                    gg=q.loc[q.pnl>0,"pnl"].sum()
                    ll=abs(q.loc[q.pnl<0,"pnl"].sum())
                    matrix.append({
                        "condition":name,
                        "n":int(len(q)),
                        "win_rate_pct":round(float((q.pnl>0).mean()*100),3),
                        "expectancy_pct":round(float(q.pnl.mean()),4),
                        "profit_factor":None if ll==0 else round(float(gg/ll),4),
                        "median_mfe_pct":round(float(q.mfe.median()),4),
                        "median_mae_pct":round(float(q.mae.median()),4),
                        "median_days":round(float(q.days.median()),2)
                    })
            results[horizon][setup]["conditions"]=sorted(matrix,key=lambda x:x["expectancy_pct"],reverse=True)

    output={
        "status":"OK",
        "version":"V3.2",
        "methodology":{
            "ladder_exit":True,
            "tp_weights":[0.40,0.30,0.30],
            "round_trip_cost":0.002,
            "cost_note":"2 bps? No: 0.20% total stress assumption, not claimed as actual broker fee.",
            "daily_ohlc_limitation":True,
            "intraday_engine":False
        },
        "results":results
    }

    OUT.write_text(json.dumps(output,indent=2,default=lambda o:None),encoding="utf-8")

    print("\n=== V3.2 DIAGNOSTIC ===")
    for horizon in results:
        print(f"\n=== {horizon.upper()} ===")
        arr=[]
        for s,v in results[horizon].items():
            arr.append((s,v["n"],v["expectancy_pct"],v["profit_factor"],v["win_rate_pct"],v["median_mfe_pct"],v["median_mae_pct"]))
        arr.sort(key=lambda x:x[2],reverse=True)
        for a in arr:
            print(f"{a[0]:24s} n={a[1]:6d} exp={a[2]:8.4f}% PF={str(a[3]):>6s} win={a[4]:6.2f}% MFE={a[5]:6.2f}% MAE={a[6]:7.2f}%")

        print("\nTOP CONDITIONS:")
        shown=0
        allc=[]
        for s,v in results[horizon].items():
            for c in v.get("conditions",[]):
                if c["expectancy_pct"]>0 and c["profit_factor"] is not None and c["profit_factor"]>1 and c["n"]>=300:
                    allc.append((s,c))
        allc.sort(key=lambda x:x[1]["expectancy_pct"],reverse=True)
        for s,c in allc[:15]:
            print(f"{s:20s} + {c['condition']:18s} n={c['n']:5d} exp={c['expectancy_pct']:7.4f}% PF={c['profit_factor']:5.2f} win={c['win_rate_pct']:6.2f}%")
            shown+=1
        if shown==0:
            print("Belum ada kondisi tunggal yang lolos exp>0, PF>1, n>=300.")

    print(f"\nV3.2 OK -> {OUT}")

if __name__=="__main__":
    run()


