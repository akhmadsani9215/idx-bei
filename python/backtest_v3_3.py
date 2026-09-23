import os, json, numpy as np, pandas as pd
from importlib.util import spec_from_file_location, module_from_spec

BASE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.join(BASE,"backtest_v3_2.py")

spec=spec_from_file_location("v32",SRC)
v32=module_from_spec(spec)
spec.loader.exec_module(v32)

DATA_DIR=os.path.abspath(os.path.join(BASE,"..","data","timeseries","stock_summary"))
OUT=os.path.abspath(os.path.join(BASE,"..","data","backtest_v33_edge_validation.json"))

TRAIN_END=pd.Timestamp("2026-03-31")
TEST_START=pd.Timestamp("2026-04-01")
COST=0.002

CANDIDATES=[
    ("PULLBACK",None),
    ("PULLBACK","ATR_GE_3"),
    ("PULLBACK","SUPPORT_1_2ATR"),
    ("FOREIGN_SUPPORT",None),
    ("FOREIGN_SUPPORT","UPTREND"),
]

def condition(row, cond):
    if cond is None:
        return True

    if cond=="ATR_GE_3":
        return np.isfinite(row.ATR_PCT) and row.ATR_PCT>=0.03

    if cond=="SUPPORT_1_2ATR":
        return np.isfinite(row.DIST_SUPPORT_ATR) and abs(row.DIST_SUPPORT_ATR)>=1 and abs(row.DIST_SUPPORT_ATR)<2

    if cond=="UPTREND":
        return bool(row.UPTREND)

    return False

def simulate_v33(g,i,horizon,cost):
    if i+1>=len(g):
        return None

    r=g.iloc[i]
    lv=v32.levels(r,horizon)
    if not lv:
        return None

    entry_level=float(lv["entry"])
    day=g.iloc[i+1]

    if float(day.Open)>=entry_level:
        entry=float(day.Open)
    elif float(day.High)>=entry_level:
        entry=entry_level
    else:
        return None

    qty=[0.40,0.30,0.30]
    remaining=1.0
    pnl=0.0
    mfe=-999.0
    mae=999.0

    tp_hits=[]
    cl_hits=[]
    tp_days={}
    cl_days={}

    exit_day=None
    exit_reason=None

    end=min(len(g),i+1+int(lv["hold"]))

    for j in range(i+1,end):
        d=g.iloc[j]
        hi=float(d.High)
        lo=float(d.Low)

        mfe=max(mfe,(hi/entry-1)*100)
        mae=min(mae,(lo/entry-1)*100)

        # Preserve V3.2 conservative ordering:
        # stop before target on same bar.
        if lo<=lv["cl3"] and remaining>0:
            pnl += remaining*(lv["cl3"]/entry-1)*100
            if 3 not in cl_hits:
                cl_hits.append(3)
                cl_days[3]=j-(i+1)+1
            remaining=0.0
            exit_day=j
            exit_reason="CL3"
            break

        if lo<=lv["cl2"] and remaining>0:
            q=min(0.30,remaining)
            pnl += q*(lv["cl2"]/entry-1)*100
            remaining-=q
            if 2 not in cl_hits:
                cl_hits.append(2)
                cl_days[2]=j-(i+1)+1

        if lo<=lv["cl1"] and remaining>0:
            q=min(0.40,remaining)
            pnl += q*(lv["cl1"]/entry-1)*100
            remaining-=q
            if 1 not in cl_hits:
                cl_hits.append(1)
                cl_days[1]=j-(i+1)+1

        if hi>=lv["tp1"] and remaining>0:
            q=min(0.40,remaining)
            pnl += q*(lv["tp1"]/entry-1)*100
            remaining-=q
            if 1 not in tp_hits:
                tp_hits.append(1)
                tp_days[1]=j-(i+1)+1

        if hi>=lv["tp2"] and remaining>0:
            q=min(0.30,remaining)
            pnl += q*(lv["tp2"]/entry-1)*100
            remaining-=q
            if 2 not in tp_hits:
                tp_hits.append(2)
                tp_days[2]=j-(i+1)+1

        if hi>=lv["tp3"] and remaining>0:
            pnl += remaining*(lv["tp3"]/entry-1)*100
            remaining=0.0
            if 3 not in tp_hits:
                tp_hits.append(3)
                tp_days[3]=j-(i+1)+1
            exit_day=j
            exit_reason="TP3"
            break

        if remaining<=0:
            exit_day=j
            exit_reason="LADDER_DONE"
            break

    if remaining>0:
        j=min(len(g)-1,i+int(lv["hold"]))
        d=g.iloc[j]
        pnl += remaining*(float(d.Close)/entry-1)*100
        exit_day=j
        exit_reason="TIME"

    pnl-=cost*100

    return {
        "date":str(r.Date.date()),
        "code":str(r.StockCode),
        "entry":entry,
        "pnl":float(pnl),
        "mfe":float(mfe),
        "mae":float(mae),
        "days":int(exit_day-(i+1)+1),
        "tp_hits":tp_hits,
        "cl_hits":cl_hits,
        "tp_days":tp_days,
        "cl_days":cl_days,
        "exit_reason":exit_reason,
        "rvol":float(r.RVOL) if np.isfinite(r.RVOL) else np.nan,
        "atr_pct":float(r.ATR_PCT) if np.isfinite(r.ATR_PCT) else np.nan,
        "fnet5":float(r.FNET5) if np.isfinite(r.FNET5) else np.nan,
        "dist_support":float(r.DIST_SUPPORT_ATR) if np.isfinite(r.DIST_SUPPORT_ATR) else np.nan,
        "uptrend":bool(r.UPTREND),
        "close_loc":float(r.CLOSE_LOC) if np.isfinite(r.CLOSE_LOC) else np.nan
    }

def summarize(z):
    if len(z)==0:
        return {"n":0}

    gains=z.loc[z.pnl>0,"pnl"].sum()
    losses=abs(z.loc[z.pnl<0,"pnl"].sum())
    pf=(gains/losses) if losses>0 else None

    def med_day(col,key):
        vals=[]
        for x in z[col]:
            if isinstance(x,dict) and key in x:
                vals.append(x[key])
        return round(float(np.median(vals)),3) if vals else None

    return {
        "n":int(len(z)),
        "win_rate_pct":round(float((z.pnl>0).mean()*100),3),
        "expectancy_pct":round(float(z.pnl.mean()),4),
        "median_pnl_pct":round(float(z.pnl.median()),4),
        "profit_factor":None if pf is None else round(float(pf),4),
        "median_mfe_pct":round(float(z.mfe.median()),4),
        "median_mae_pct":round(float(z.mae.median()),4),
        "median_duration_days":round(float(z.days.median()),3),

        "tp1_rate_pct":round(float(z.tp_hits.apply(lambda x:1 in x).mean()*100),3),
        "tp2_rate_pct":round(float(z.tp_hits.apply(lambda x:2 in x).mean()*100),3),
        "tp3_rate_pct":round(float(z.tp_hits.apply(lambda x:3 in x).mean()*100),3),

        "cl1_rate_pct":round(float(z.cl_hits.apply(lambda x:1 in x).mean()*100),3),
        "cl2_rate_pct":round(float(z.cl_hits.apply(lambda x:2 in x).mean()*100),3),
        "cl3_rate_pct":round(float(z.cl_hits.apply(lambda x:3 in x).mean()*100),3),

        "tp1_median_days":med_day("tp_days",1),
        "tp2_median_days":med_day("tp_days",2),
        "tp3_median_days":med_day("tp_days",3),

        "cl1_median_days":med_day("cl_days",1),
        "cl2_median_days":med_day("cl_days",2),
        "cl3_median_days":med_day("cl_days",3),
    }

print("=== V3.3 EDGE VALIDATION ===")
print("Loading historical data...")
df=v32.load_data()

print(f"DATA: {len(df):,} rows | {df.StockCode.nunique():,} stocks | {df.Date.min().date()} -> {df.Date.max().date()}")
print("Preparing indicators...")
df=pd.concat(
    [v32.prepare(g) for _,g in df.groupby("StockCode",sort=False)],
    ignore_index=True
)

df=df.sort_values(["StockCode","Date"]).reset_index(drop=True)

results={
    "meta":{
        "version":"V3.3_EDGE_VALIDATION",
        "train_end":str(TRAIN_END.date()),
        "test_start":str(TEST_START.date()),
        "cost_round_trip_pct":COST*100,
        "candidates":[f"{a}+{b}" if b else a for a,b in CANDIDATES],
        "note":"Fixed candidates from V3.2; no parameter optimization on TEST."
    },
    "nextday":{},
    "swing":{}
}

for horizon in ["nextday","swing"]:
    print(f"\n=== {horizon.upper()} ===")

    for setup,cond in CANDIDATES:
        rows=[]

        for code,g in df.groupby("StockCode",sort=False):
            mask=g[setup].fillna(False) & g["LIQUID"].fillna(False)

            idx=np.where(mask.values)[0]

            for i in idx:
                r=g.iloc[i]

                if not condition(r,cond):
                    continue

                x=simulate_v33(g,i,horizon,COST)

                if x is not None:
                    x["setup"]=setup
                    x["condition"]=cond or "BASE"
                    x["horizon"]=horizon
                    x["split"]="TRAIN" if r.Date<=TRAIN_END else "TEST"
                    rows.append(x)

        if not rows:
            continue

        z=pd.DataFrame(rows)
        z=z.replace([np.inf,-np.inf],np.nan)

        results[horizon][
            f"{setup}+{cond}" if cond else setup
        ]={}

        for split in ["TRAIN","TEST","ALL"]:
            zz=z if split=="ALL" else z[z["split"]==split].copy()

            results[horizon][
                f"{setup}+{cond}" if cond else setup
            ][split]=summarize(zz)

        tr=results[horizon][f"{setup}+{cond}" if cond else setup]["TRAIN"]
        te=results[horizon][f"{setup}+{cond}" if cond else setup]["TEST"]

        print(
            f"{setup}+{cond or 'BASE':<18} "
            f"TRAIN n={tr.get('n',0):5} exp={tr.get('expectancy_pct',0):7.3f}% PF={str(tr.get('profit_factor')):>6} | "
            f"TEST n={te.get('n',0):5} exp={te.get('expectancy_pct',0):7.3f}% PF={str(te.get('profit_factor')):>6}"
        )

print("\n=== TEST EDGE SURVIVORS ===")

for horizon,items in results.items():
    if horizon=="meta":
        continue

    print(f"\n{horizon.upper()}")

    for name,v in items.items():
        te=v["TEST"]
        n=te.get("n",0)
        exp=te.get("expectancy_pct",0)
        pf=te.get("profit_factor")

        if n>=100:
            print(
                f"{name:<32} "
                f"n={n:5} exp={exp:7.3f}% PF={str(pf):>6} "
                f"win={te.get('win_rate_pct',0):6.2f}% "
                f"TP1={te.get('tp1_rate_pct',0):6.2f}% "
                f"TP1d={str(te.get('tp1_median_days')):>5}"
            )

with open(OUT,"w",encoding="utf-8") as f:
    json.dump(results,f,ensure_ascii=False,indent=2,default=lambda x:None)

print(f"\nV3.3 OK -> {OUT}")
