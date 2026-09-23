from pathlib import Path
import json, math
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data" / "timeseries"
OUT = BASE / "data" / "backtest_lab.json"

def read_ts():
    p = DATA / "stock_summary"
    files = sorted(list(p.glob("*.parquet")) + list(p.glob("*.csv")))
    if not files:
        raise FileNotFoundError(f"Tidak menemukan historical data di {p}")
    frames = []
    for f in files:
        try:
            x = pd.read_parquet(f) if f.suffix.lower()==".parquet" else pd.read_csv(f)
            frames.append(x)
        except Exception:
            pass
    if not frames:
        raise RuntimeError("Historical files ditemukan tetapi gagal dibaca.")
    df = pd.concat(frames, ignore_index=True)
    rename = {}
    for c in df.columns:
        k = str(c).lower().replace("_","").replace(" ","")
        if k == "stockcode": rename[c]="StockCode"
        elif k == "date": rename[c]="Date"
        elif k in ("open","openprice"): rename[c]="Open"
        elif k in ("high","highprice"): rename[c]="High"
        elif k in ("low","lowprice"): rename[c]="Low"
        elif k in ("close","closeprice"): rename[c]="Close"
        elif k == "volume": rename[c]="Volume"
        elif k == "value": rename[c]="Value"
        elif k == "foreignbuy": rename[c]="ForeignBuy"
        elif k == "foreignsell": rename[c]="ForeignSell"
    df=df.rename(columns=rename)
    need=["StockCode","Date","Open","High","Low","Close","Volume","Value"]
    missing=[c for c in need if c not in df.columns]
    if missing: raise RuntimeError(f"Kolom kurang: {missing}")
    df["Date"]=pd.to_datetime(df["Date"], errors="coerce")
    for c in ["Open","High","Low","Close","Volume","Value","ForeignBuy","ForeignSell"]:
        if c in df.columns: df[c]=pd.to_numeric(df[c], errors="coerce")
    if "ForeignBuy" not in df: df["ForeignBuy"]=0.0
    if "ForeignSell" not in df: df["ForeignSell"]=0.0
    df=df.dropna(subset=["StockCode","Date","Open","High","Low","Close","Volume","Value"])
    df=df[(df["Close"]>0)&(df["Open"]>0)&(df["High"]>0)&(df["Low"]>0)&(df["Value"]>0)]
    return df.sort_values(["StockCode","Date"]).reset_index(drop=True)

def prep(g):
    g=g.copy()
    c=g["Close"]; h=g["High"]; l=g["Low"]; o=g["Open"]; v=g["Volume"]
    tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    g["ATR14"]=tr.rolling(14,min_periods=14).mean()
    g["ATRpct"]=100*g["ATR14"]/c
    g["SMA5"]=c.rolling(5).mean()
    g["SMA10"]=c.rolling(10).mean()
    g["SMA20"]=c.rolling(20).mean()
    g["SMA50"]=c.rolling(50).mean()
    g["VOL5"]=v.rolling(5).mean()
    g["VOL20"]=v.rolling(20).mean()
    g["RVOL"]=v/g["VOL20"].replace(0,np.nan)
    g["VOLACC"]=g["VOL5"]/g["VOL20"].replace(0,np.nan)
    g["RET1"]=c.pct_change()*100
    g["RET5"]=c.pct_change(5)*100
    g["RET10"]=c.pct_change(10)*100
    g["RET20"]=c.pct_change(20)*100
    g["RANGE20"]=100*(h.rolling(20).max()-l.rolling(20).min())/c
    g["HIGH20"]=h.rolling(20).max()
    g["LOW20"]=l.rolling(20).min()
    g["HIGH52"]=h.rolling(252,min_periods=40).max()
    g["LOW52"]=l.rolling(252,min_periods=40).min()
    g["CLOSELOC"]=(c-l)/(h-l).replace(0,np.nan)
    g["UPWICK"]=(h-np.maximum(o,c))/(h-l).replace(0,np.nan)
    g["DOWNWICK"]=(np.minimum(o,c)-l)/(h-l).replace(0,np.nan)
    g["EFF5"]=(c-c.shift(5)).abs()/((c.diff().abs()).rolling(5).sum()+1e-9)
    g["EFF10"]=(c-c.shift(10)).abs()/((c.diff().abs()).rolling(10).sum()+1e-9)
    g["FNET1"]=g["ForeignBuy"]-g["ForeignSell"]
    g["FNET5"]=g["FNET1"].rolling(5).sum()
    g["FNET10"]=g["FNET1"].rolling(10).sum()
    g["VALUE20"]=g["Value"].rolling(20).mean()
    g["PRICE_EXT20"]=100*(c-g["SMA20"])/g["SMA20"]
    g["SUPDIST"]=100*(c-g["LOW20"])/c
    g["RESIDIST"]=100*(g["HIGH20"]-c)/c

    # Trend regime known only from T.
    g["UPTREND"]=(c>g["SMA20"])&(g["SMA20"]>g["SMA50"])
    g["DOWNTREND"]=(c<g["SMA20"])&(g["SMA20"]<g["SMA50"])
    g["SIDEWAYS"]=~g["UPTREND"]&~g["DOWNTREND"]

    # Daily signatures. These are NOT true intraday signals.
    g["ABSORPTION"]=(
        (g["RVOL"]>=1.5)&
        (g["CLOSELOC"]>=0.65)&
        (g["RET1"].abs()<=1.5)&
        (g["EFF5"]<=0.45)&
        (g["SUPDIST"]<=8)
    )
    g["DISTRIBUTION"]=(
        (g["RVOL"]>=1.5)&
        (g["CLOSELOC"]<=0.40)&
        (g["RET1"]<=-1.0)&
        (g["UPWICK"]>=0.30)
    )
    g["MOMENTUM"]=(
        (g["RVOL"]>=1.5)&
        (g["RET1"]>=1.0)&
        (g["CLOSELOC"]>=0.65)&
        (c>=g["SMA5"])
    )
    g["PULLBACK"]=(
        (g["UPTREND"])&
        (g["RET5"]<0)&
        (g["SUPDIST"]<=6)&
        (g["CLOSELOC"]>=0.45)&
        (g["RVOL"]>=0.8)
    )
    g["REVERSAL"]=(
        (
            (g["DOWNTREND"])|
            (g["SUPDIST"]<=5)
        )&
        (g["DOWNWICK"]>=0.25)&
        (g["CLOSELOC"]>=0.55)&
        (g["RET1"]>=-1.0)&
        (g["RVOL"]>=1.0)
    )
    g["FOREIGN"]=(
        (g["FNET5"]>0)&
        (g["FNET10"]>0)
    )
    return g

def pct(x):
    if pd.isna(x): return None
    return round(float(x),3)

def summarize(x):
    if not x: return {"samples":0}
    a=pd.DataFrame(x)
    out={
        "samples":int(len(a)),
        "win_rate_pct":pct(100*(a["ret_close"]>0).mean()),
        "median_open_pct":pct(a["ret_open"].median()),
        "median_close_pct":pct(a["ret_close"].median()),
        "median_mfe_pct":pct(a["mfe"].median()),
        "median_mae_pct":pct(a["mae"].median()),
        "mean_close_pct":pct(a["ret_close"].mean()),
        "hit_2_pct":pct(100*(a["mfe"]>=2).mean()),
        "hit_3_pct":pct(100*(a["mfe"]>=3).mean()),
        "hit_4_pct":pct(100*(a["mfe"]>=4).mean()),
        "hit_5_pct":pct(100*(a["mfe"]>=5).mean()),
        "stop_1_pct":pct(100*(a["mae"]<=-1).mean()),
        "stop_2_pct":pct(100*(a["mae"]<=-2).mean()),
        "stop_3_pct":pct(100*(a["mae"]<=-3).mean()),
        "avg_duration_to_2d":pct(a["dur2"].dropna().mean()) if a["dur2"].notna().any() else None,
        "avg_duration_to_3d":pct(a["dur3"].dropna().mean()) if a["dur3"].notna().any() else None,
        "avg_duration_to_5d":pct(a["dur5"].dropna().mean()) if a["dur5"].notna().any() else None,
    }
    return out

def trade_rows(g, horizon, signal_name, mask):
    idx=np.where(mask.fillna(False).values)[0]
    rows=[]
    n=len(g)
    for i in idx:
        # Require enough future bars.
        if horizon=="nextday":
            hs=[1]
        elif horizon=="swing":
            hs=[5,10,20]
        else:
            continue
        if i+max(hs)>=n: continue
        entry=float(g.iloc[i]["Close"])
        if not np.isfinite(entry) or entry<=0: continue

        if horizon=="nextday":
            j=i+1
            op=float(g.iloc[j]["Open"]); cl=float(g.iloc[j]["Close"])
            hi=float(g.iloc[j]["High"]); lo=float(g.iloc[j]["Low"])
            ret_open=100*(op/entry-1)
            ret_close=100*(cl/entry-1)
            mfe=100*(hi/entry-1)
            mae=100*(lo/entry-1)
            d2=d3=d5=np.nan
        else:
            op=float(g.iloc[i+1]["Open"])
            ret_open=100*(op/entry-1)
            close20=float(g.iloc[i+20]["Close"])
            cl=close20
            ret_close=100*(cl/entry-1)
            hi=max(float(g.iloc[i+k]["High"]) for k in hs)
            lo=min(float(g.iloc[i+k]["Low"]) for k in hs)
            mfe=100*(hi/entry-1)
            mae=100*(lo/entry-1)
            d2=d3=d5=np.nan
            for target,name in [(2,"d2"),(3,"d3"),(5,"d5")]:
                for k in hs:
                    if 100*(float(g.iloc[i+k]["High"])/entry-1)>=target:
                        if name=="d2": d2=k
                        elif name=="d3": d3=k
                        else: d5=k
                        break
        rows.append({
            "date":str(g.iloc[i]["Date"].date()),
            "ticker":str(g.iloc[i]["StockCode"]),
            "signal":signal_name,
            "entry":entry,
            "ret_open":ret_open,
            "ret_close":ret_close,
            "mfe":mfe,
            "mae":mae,
            "dur2":d2,
            "dur3":d3,
            "dur5":d5,
            "rvol":float(g.iloc[i]["RVOL"]),
            "atr_pct":float(g.iloc[i]["ATRpct"]),
            "value":float(g.iloc[i]["Value"]),
            "trend":"UPTREND" if bool(g.iloc[i]["UPTREND"]) else ("DOWNTREND" if bool(g.iloc[i]["DOWNTREND"]) else "SIDEWAYS"),
        })
    return rows

def walk_forward(rows):
    if not rows: return {}
    d=pd.DataFrame(rows)
    d["date"]=pd.to_datetime(d["date"])
    windows=[
        ("WF1","2025-09-01","2026-03-31","2026-04-01","2026-06-30"),
        ("WF2","2025-12-01","2026-06-30","2026-07-01","2026-09-18"),
    ]
    out={}
    for name,tr0,tr1,te0,te1 in windows:
        tr=d[(d.date>=tr0)&(d.date<=tr1)]
        te=d[(d.date>=te0)&(d.date<=te1)]
        out[name]={
            "train":summarize(tr.to_dict("records")),
            "test":summarize(te.to_dict("records")),
        }
    return out

def main():
    df=read_ts()
    parts=[]
    for code,g in df.groupby("StockCode",sort=False):
        if len(g)<60: continue
        parts.append(prep(g))
    df=pd.concat(parts,ignore_index=True)

    # Only sufficiently liquid names are evaluated.
    base=df[
        (df["VALUE20"]>=1_000_000_000)&
        (df["ATRpct"]>=0.8)&
        (df["ATRpct"]<=12)&
        (df["RVOL"].notna())
    ].copy()

    signal_defs={
        "ALL_LIQUID":np.ones(len(base),dtype=bool),
        "MOMENTUM":base["MOMENTUM"],
        "ABSORPTION":base["ABSORPTION"]&~base["DISTRIBUTION"],
        "REVERSAL":base["REVERSAL"]&~base["DISTRIBUTION"],
        "PULLBACK":base["PULLBACK"],
        "FOREIGN":base["FOREIGN"]&~base["DISTRIBUTION"],
        "MOMENTUM_FOREIGN":base["MOMENTUM"]&base["FOREIGN"]&~base["DISTRIBUTION"],
        "MOMENTUM_RVOL2":base["MOMENTUM"]&(base["RVOL"]>=2)&~base["DISTRIBUTION"],
        "MOMENTUM_SUPPORT":base["MOMENTUM"]&(base["SUPDIST"]<=6)&~base["DISTRIBUTION"],
        "ABSORPTION_FOREIGN":base["ABSORPTION"]&base["FOREIGN"]&~base["DISTRIBUTION"],
        "ABSORPTION_RVOL2":base["ABSORPTION"]&(base["RVOL"]>=2)&~base["DISTRIBUTION"],
        "ABSORPTION_SUPPORT":base["ABSORPTION"]&(base["SUPDIST"]<=5)&~base["DISTRIBUTION"],
        "REVERSAL_FOREIGN":base["REVERSAL"]&base["FOREIGN"]&~base["DISTRIBUTION"],
        "REVERSAL_ABSORPTION":base["REVERSAL"]&base["ABSORPTION"]&~base["DISTRIBUTION"],
        "REVERSAL_RVOL2":base["REVERSAL"]&(base["RVOL"]>=2)&~base["DISTRIBUTION"],
        "FOREIGN_RVOL2":base["FOREIGN"]&(base["RVOL"]>=2)&~base["DISTRIBUTION"],
        "FOREIGN_SUPPORT":base["FOREIGN"]&(base["SUPDIST"]<=6)&~base["DISTRIBUTION"],
    }

    results={"status":"OK","data_quality":{
        "frequency":"DAILY",
        "intraday_15_00_15_50_available":False,
        "note":"Intraday engine masih memakai daily close-to-next-session proxy sampai data intraday tersedia.",
        "first_date":str(df.Date.min().date()),
        "last_date":str(df.Date.max().date()),
        "stocks":int(df.StockCode.nunique()),
    },"horizons":{}}

    for horizon in ["nextday","swing"]:
        allrows=[]
        for name,mask in signal_defs.items():
            m=pd.Series(mask,index=base.index)
            rr=[]
            for code,g in base.groupby("StockCode",sort=False):
                gm=m.loc[g.index]
                rr.extend(trade_rows(g,horizon,name,gm))
            allrows.extend(rr)

        summaries={}
        for name in signal_defs:
            rr=[r for r in allrows if r["signal"]==name]
            summaries[name]=summarize(rr)

        # Liquidity / RVOL / regime diagnostics on ALL_LIQUID.
        diag={}
        allr=[r for r in allrows if r["signal"]=="ALL_LIQUID"]
        ar=pd.DataFrame(allr)
        if len(ar):
            diag["rvol_buckets"]={}
            for label,lo,hi in [("1.0-1.2",1,1.2),("1.2-1.5",1.2,1.5),("1.5-2.0",1.5,2),("2.0+",2,999)]:
                z=ar[(ar.rvol>=lo)&(ar.rvol<hi)]
                diag["rvol_buckets"][label]=summarize(z.to_dict("records"))
            diag["trend"]={}
            for t in ["UPTREND","SIDEWAYS","DOWNTREND"]:
                z=ar[ar.trend==t]
                diag["trend"][t]=summarize(z.to_dict("records"))

        results["horizons"][horizon]={
            "samples":len(allrows),
            "setups":summaries,
            "diagnostics":diag,
            "walk_forward":{
                name:walk_forward([r for r in allrows if r["signal"]==name])
                for name in signal_defs
            }
        }

    # Candidate rules are intentionally provisional; they will only be promoted
    # after walk-forward evidence.
    results["promotion_rule"]={
        "min_test_samples":100,
        "require_test_hit_3_pct_gt_baseline":True,
        "require_test_median_close_gt_baseline":True,
        "require_no_major_mae_deterioration":True,
        "require_two_walk_forward_windows":True,
        "note":"Belum ada setup yang otomatis dipromosikan sebelum lolos out-of-sample."
    }

    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str),encoding="utf-8")

    print(f"BACKTEST LAB OK -> {OUT}")
    for hz,x in results["horizons"].items():
        print(f"{hz}: samples={x['samples']}")
        ranked=[]
        for k,v in x["setups"].items():
            if v.get("samples",0)>=100:
                ranked.append((v.get("hit_3_pct",0),v.get("median_close_pct",0),v.get("samples",0),k))
        ranked.sort(reverse=True)
        print("TOP HIT+3 / CLOSE:")
        for a,b,c,k in ranked[:8]:
            print(f"  {k:24s} n={c:5d} hit3={a:6.2f}% close_med={b:7.3f}%")

if __name__=="__main__":
    main()

