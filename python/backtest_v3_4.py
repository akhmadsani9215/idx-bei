import os,json,numpy as np,pandas as pd
from importlib.util import spec_from_file_location,module_from_spec

BASE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.join(BASE,"backtest_v3_2.py")
spec=spec_from_file_location("v32",SRC)
v32=module_from_spec(spec)
spec.loader.exec_module(v32)

OUT=os.path.abspath(os.path.join(BASE,"..","data","backtest_v34_management_lab.json"))

TRAIN_END=pd.Timestamp("2026-03-31")
TEST_START=pd.Timestamp("2026-04-01")

COSTS=[0.0,0.001,0.002,0.003]

SETUPS=[
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

POLICIES=[
    "SL1_TP1",
    "SL1_TP2",
    "SL1_TP3",
    "SL1P5_TP2",
    "LADDER_V32",
    "TRAIL_1ATR"
]

def levels2(r,horizon,policy):
    close=float(r.Close)
    atr=float(r.ATR14)

    if not np.isfinite(atr) or atr<=0 or close<=0:
        return None

    if horizon=="nextday":
        hold=3
    else:
        hold=20

    if policy=="SL1_TP1":
        sl=close-1.0*atr
        tp=close+1.0*atr

    elif policy=="SL1_TP2":
        sl=close-1.0*atr
        tp=close+2.0*atr

    elif policy=="SL1_TP3":
        sl=close-1.0*atr
        tp=close+3.0*atr

    elif policy=="SL1P5_TP2":
        sl=close-1.5*atr
        tp=close+2.0*atr

    elif policy=="LADDER_V32":
        return {
            "mode":"ladder",
            "entry":close+0.15*atr if horizon=="nextday" else close+0.20*atr,
            "cl1":close-0.75*atr,
            "cl2":close-1.15*atr if horizon=="nextday" else close-1.25*atr,
            "cl3":close-1.50*atr if horizon=="nextday" else close-1.75*atr,
            "tp1":close+0.75*atr if horizon=="nextday" else close+1.25*atr,
            "tp2":close+1.50*atr if horizon=="nextday" else close+2.25*atr,
            "tp3":close+2.25*atr if horizon=="nextday" else close+3.25*atr,
            "hold":hold
        }

    elif policy=="TRAIL_1ATR":
        return {
            "mode":"trail",
            "entry":close+0.15*atr if horizon=="nextday" else close+0.20*atr,
            "atr":atr,
            "hold":hold
        }

    else:
        return None

    return {
        "mode":"fixed",
        "entry":close+0.15*atr if horizon=="nextday" else close+0.20*atr,
        "sl":sl,
        "tp":tp,
        "hold":hold
    }

def simulate(g,i,horizon,policy,cost):
    if i+1>=len(g):
        return None

    r=g.iloc[i]
    lv=levels2(r,horizon,policy)

    if lv is None:
        return None

    entry_level=lv["entry"]
    day=g.iloc[i+1]

    if float(day.Open)>=entry_level:
        entry=float(day.Open)
    elif float(day.High)>=entry_level:
        entry=float(entry_level)
    else:
        return None

    mfe=-999.0
    mae=999.0
    pnl=None
    exit_reason=None
    tp_day=None
    sl_day=None
    exit_day=None
    tp_day=None
    sl_day=None

    hold=int(lv["hold"])
    end=min(len(g),i+1+hold)

    if lv["mode"]=="fixed":

        for j in range(i+1,end):
            d=g.iloc[j]
            hi=float(d.High)
            lo=float(d.Low)

            mfe=max(mfe,(hi/entry-1)*100)
            mae=min(mae,(lo/entry-1)*100)

            # conservative stop first
            if lo<=lv["sl"]:
                pnl=(lv["sl"]/entry-1)*100
                sl_day=j-(i+1)+1
                exit_day=j
                exit_reason="SL"
                break

            if hi>=lv["tp"]:
                pnl=(lv["tp"]/entry-1)*100
                tp_day=j-(i+1)+1
                exit_day=j
                exit_reason="TP"
                break

        if pnl is None:
            j=end-1
            pnl=(float(g.iloc[j].Close)/entry-1)*100
            exit_day=j
            exit_reason="TIME"

    elif lv["mode"]=="trail":

        peak=entry
        stop=entry-lv["atr"]

        for j in range(i+1,end):
            d=g.iloc[j]
            hi=float(d.High)
            lo=float(d.Low)

            mfe=max(mfe,(hi/entry-1)*100)
            mae=min(mae,(lo/entry-1)*100)

            peak=max(peak,hi)

            # trailing stop one ATR behind peak
            new_stop=peak-lv["atr"]

            if new_stop>stop:
                stop=new_stop

            if lo<=stop:
                pnl=(stop/entry-1)*100
                sl_day=j-(i+1)+1
                exit_day=j
                exit_reason="TRAIL"
                break

        if pnl is None:
            j=end-1
            pnl=(float(g.iloc[j].Close)/entry-1)*100
            exit_day=j
            exit_reason="TIME"

    else:
        # V3.2 ladder preserved exactly
        remaining=1.0
        pnl=0.0

        for j in range(i+1,end):
            d=g.iloc[j]
            hi=float(d.High)
            lo=float(d.Low)

            mfe=max(mfe,(hi/entry-1)*100)
            mae=min(mae,(lo/entry-1)*100)

            if lo<=lv["cl3"] and remaining>0:
                pnl+=remaining*(lv["cl3"]/entry-1)*100
                remaining=0
                exit_day=j
                exit_reason="CL3"
                sl_day=j-(i+1)+1
                break

            if lo<=lv["cl2"] and remaining>0:
                q=min(0.30,remaining)
                pnl+=q*(lv["cl2"]/entry-1)*100
                remaining-=q
                if sl_day is None:
                    sl_day=j-(i+1)+1

            if lo<=lv["cl1"] and remaining>0:
                q=min(0.40,remaining)
                pnl+=q*(lv["cl1"]/entry-1)*100
                remaining-=q
                if sl_day is None:
                    sl_day=j-(i+1)+1

            if hi>=lv["tp1"] and remaining>0:
                q=min(0.40,remaining)
                pnl+=q*(lv["tp1"]/entry-1)*100
                remaining-=q
                if tp_day is None:
                    tp_day=j-(i+1)+1

            if hi>=lv["tp2"] and remaining>0:
                q=min(0.30,remaining)
                pnl+=q*(lv["tp2"]/entry-1)*100
                remaining-=q

            if hi>=lv["tp3"] and remaining>0:
                pnl+=remaining*(lv["tp3"]/entry-1)*100
                remaining=0
                exit_day=j
                exit_reason="TP3"
                break

            if remaining<=0:
                exit_day=j
                exit_reason="LADDER_DONE"
                break

        if remaining>0:
            j=end-1
            pnl+=remaining*(float(g.iloc[j].Close)/entry-1)*100
            exit_day=j
            exit_reason="TIME"

    pnl-=cost*100

    return {
        "date":str(r.Date.date()),
        "code":str(r.StockCode),
        "pnl":float(pnl),
        "mfe":float(mfe),
        "mae":float(mae),
        "days":int(exit_day-(i+1)+1),
        "exit_reason":exit_reason,
        "tp_day":tp_day,
        "sl_day":sl_day
    }

def summarize(z):
    if len(z)==0:
        return {"n":0}

    gains=z.loc[z.pnl>0,"pnl"].sum()
    losses=abs(z.loc[z.pnl<0,"pnl"].sum())
    pf=gains/losses if losses>0 else None

    tp=z.tp_day.dropna()
    sl=z.sl_day.dropna()

    return {
        "n":int(len(z)),
        "win_rate_pct":round(float((z.pnl>0).mean()*100),3),
        "expectancy_pct":round(float(z.pnl.mean()),4),
        "median_pnl_pct":round(float(z.pnl.median()),4),
        "profit_factor":None if pf is None else round(float(pf),4),
        "median_mfe_pct":round(float(z.mfe.median()),4),
        "median_mae_pct":round(float(z.mae.median()),4),
        "median_duration_days":round(float(z.days.median()),3),
        "tp_rate_pct":round(float(z.tp_day.notna().mean()*100),3),
        "sl_rate_pct":round(float(z.sl_day.notna().mean()*100),3),
        "time_rate_pct":round(float((z.exit_reason=="TIME").mean()*100),3),
        "median_tp_days":round(float(tp.median()),3) if len(tp) else None,
        "median_sl_days":round(float(sl.median()),3) if len(sl) else None
    }

print("=== V3.4 TRADE MANAGEMENT LAB ===")
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
        "version":"V3.4_TRADE_MANAGEMENT_LAB",
        "train_end":str(TRAIN_END.date()),
        "test_start":str(TEST_START.date()),
        "costs":COSTS,
        "policies":POLICIES
    },
    "nextday":{},
    "swing":{}
}

for horizon in ["nextday","swing"]:
    print(f"\n=== {horizon.upper()} ===")

    for setup in SETUPS:

        # only one cost for the full matrix initially; cost sensitivity is run for
        # promising TEST results below.
        rows=[]

        for code,g in df.groupby("StockCode",sort=False):

            mask=g[setup].fillna(False) & g["LIQUID"].fillna(False)
            idx=np.where(mask.values)[0]

            for i in idx:
                r=g.iloc[i]

                x=simulate(g,i,horizon,"SL1_TP2",0.002)

                if x is not None:
                    x["setup"]=setup
                    x["split"]="TRAIN" if r.Date<=TRAIN_END else "TEST"
                    rows.append(x)

        if not rows:
            continue

        zbase=pd.DataFrame(rows)

        # Test all management policies on exactly the same signal dates.
        for policy in POLICIES:
            prow=[]

            for code,g in df.groupby("StockCode",sort=False):

                mask=g[setup].fillna(False) & g["LIQUID"].fillna(False)
                idx=np.where(mask.values)[0]

                for i in idx:
                    r=g.iloc[i]
                    x=simulate(g,i,horizon,policy,0.002)

                    if x is not None:
                        x["setup"]=setup
                        x["policy"]=policy
                        x["split"]="TRAIN" if r.Date<=TRAIN_END else "TEST"
                        prow.append(x)

            z=pd.DataFrame(prow)

            if len(z)==0:
                continue

            key=setup+"|"+policy

            results[horizon][key]={}

            for split in ["TRAIN","TEST"]:
                zz=z[z.split==split]
                results[horizon][key][split]=summarize(zz)

            te=results[horizon][key]["TEST"]

            if te["n"]>=100:
                print(
                    f"{setup:<22} {policy:<14} "
                    f"TEST n={te['n']:5} "
                    f"exp={te['expectancy_pct']:7.3f}% "
                    f"PF={str(te['profit_factor']):>6} "
                    f"win={te['win_rate_pct']:6.2f}% "
                    f"TP={te['tp_rate_pct']:6.2f}% "
                    f"SL={te['sl_rate_pct']:6.2f}% "
                    f"dur={te['median_duration_days']:4.1f}"
                )

print("\n=== TEST MANAGEMENT SURVIVORS ===")

for horizon,items in results.items():

    if horizon=="meta":
        continue

    candidates=[]

    for name,v in items.items():
        te=v["TEST"]

        if te.get("n",0)>=300:
            pf=te.get("profit_factor")
            exp=te.get("expectancy_pct",0)

            if pf is not None and exp>0 and pf>1:
                candidates.append((exp,pf,name,te))

    candidates.sort(reverse=True)

    print(f"\n{horizon.upper()}")

    if not candidates:
        print("NO POSITIVE TEST MANAGEMENT EDGE (n>=300).")
    else:
        for exp,pf,name,te in candidates[:20]:
            print(
                f"{name:<42} "
                f"n={te['n']:5} "
                f"exp={exp:7.3f}% "
                f"PF={pf:6.3f} "
                f"win={te['win_rate_pct']:6.2f}% "
                f"TP={te['tp_rate_pct']:6.2f}% "
                f"SL={te['sl_rate_pct']:6.2f}% "
                f"TPday={str(te['median_tp_days']):>5}"
            )

with open(OUT,"w",encoding="utf-8") as f:
    json.dump(results,f,ensure_ascii=False,indent=2,default=lambda x:None)

print(f"\nV3.4 OK -> {OUT}")

