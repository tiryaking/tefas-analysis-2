import pandas as pd
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tefas import config, etl, metrics, scoring, holdings

def backfill(fund_type="YAT"):
    paths = config.paths_for(fund_type)
    cfg = {}
    cfg_path = Path("tefas.config.json")
    if cfg_path.exists():
        import json
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    
    rfr = cfg.get("risk_free_rate", config.macro().risk_free_rate)
    include = cfg.get("include") if fund_type == cfg.get("fund_type") else None
    exclude = cfg.get("exclude") if fund_type == cfg.get("fund_type") else None
    active_only = cfg.get("active_only", True)
    keep_suspect = cfg.get("keep_suspect", False)
    min_aum = cfg.get("min_aum")
    min_fund_age = cfg.get("min_fund_age")
    
    print(f"Loading combined data for {fund_type}...")
    try:
        combined = etl.load_combined(fund_type, include=include, exclude=exclude, active_only=active_only)
    except FileNotFoundError:
        print(f"[WARN] Platform status file missing for {fund_type}. Falling back to active_only=False.")
        combined = etl.load_combined(fund_type, include=include, exclude=exclude, active_only=False)
        
    combined["Tarih"] = pd.to_datetime(combined["Tarih"])
    
    # Get all month end dates in combined["Tarih"]
    month_ends = combined.groupby(combined["Tarih"].dt.to_period("M"))["Tarih"].max().sort_values()
    
    # We need enough data for each date, say at least 60 trading days
    min_date = combined["Tarih"].min()
    valid_dates = [d for d in month_ends if (d - min_date).days >= 120]
    max_date = combined["Tarih"].max()
    if max_date not in valid_dates:
        valid_dates.append(max_date)
    
    valid_dates = sorted(list(set(valid_dates)))
    print("Valid dates for backfill:", [d.strftime("%Y-%m-%d") for d in valid_dates])
    
    all_snaps = []
    for d in valid_dates:
        print(f"Processing date: {d.strftime('%Y-%m-%d')}...")
        combined_t = combined[combined["Tarih"] <= d].copy()
        
        # Compute metrics
        met_t = metrics.compute_metrics(combined_t, rfr, keep_suspect=keep_suspect,
                                      min_aum=min_aum, min_fund_age=min_fund_age)
        if met_t.empty:
            continue
            
        # Score funds
        scored_t = scoring.score_funds(met_t, combined_t, rfr)
        if scored_t.empty:
            continue
            
        # Take snapshot
        snap = holdings.score_snapshot(scored_t, d)
        all_snaps.append(snap)
        
    if all_snaps:
        hist = pd.concat(all_snaps, ignore_index=True)
        # Deduplicate and sort
        hist = (hist.drop_duplicates(subset=["Tarih", "Fon Kodu"], keep="last")
                .sort_values(["Tarih", "Fon Kodu"]).reset_index(drop=True))
        hist.to_parquet(paths.score_history_parquet, index=False)
        print(f"Backfill completed! Saved to {paths.score_history_parquet} with {len(hist)} rows, {hist['Tarih'].nunique()} dates.\n")

if __name__ == "__main__":
    backfill("YAT")
    backfill("EMK")
