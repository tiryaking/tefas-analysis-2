# Plan: Add Monthly Return Heatmap to Fon Detay Page

## Goal
Add an "Aylık Getiri Takvimi" (monthly return heatmap) to the Fon Detay page in the HTML dashboard, showing the selected fund's monthly returns alongside the universe median — just like other pages (`Özet`, `Karşılaştırma`, `Portföy & Risk`) already do via `fig_monthly_heatmap`.

## Current State

The Fon Detay page ([`tefas/dashboard/views/fon_detay.py`](tefas/dashboard/views/fon_detay.py)) currently has a **bar chart** for monthly returns at lines 117–124:

```python
monthly = charts.prep_monthly_returns(pivot)
if not monthly.empty and code in monthly.columns:
    mr = monthly[code].dropna()
    fig_m = go.Figure()
    fig_m.add_bar(x=[str(p) for p in mr.index], y=mr.values,
                  marker_color=["#0f8a6a" if v >= 0 else "#c0392b" for v in mr.values])
    fig_m.update_layout(title="Aylık Getiriler (%)", height=300, margin=dict(t=40, b=10))
    st.plotly_chart(fig_m, width="stretch")
```

This bar chart uses `pivot` which is built from `sub` (the single fund's data filtered by date range). So it only shows that one fund — no comparison context.

## The Heatmap Approach

The other pages use a **heatmap** via [`figures.fig_monthly_heatmap()`](tefas/dashboard/figures.py:132). This function:

1. Takes a `monthly` DataFrame (output of `charts.prep_monthly_returns`) — a pivot with dates as rows, fund codes as columns
2. Takes a list of `codes` to display
3. Computes `monthly.median(axis=1)` as an extra "Evren medyanı" row
4. Draws a RdYlGn heatmap centered at 0

### Key Change Needed

The current `pivot` variable (line 110) is scoped to a single fund (`sub = combined[combined["Fon Kodu"] == code]`). This means `charts.prep_monthly_returns(pivot)` returns a DataFrame with only one column — the selected fund.

To show a meaningful "Evren medyanı" row, we need the **full universe** monthly data. The dashboard already has a cached version of this:

```python
data.monthly_returns(ft)  # tefas/dashboard/data.py:107
```

This loads the full-universe monthly data from the combined parquet (cached with `@st.cache_data`).

## Proposed Change

Modify [`tefas/dashboard/views/fon_detay.py`](tefas/dashboard/views/fon_detay.py) to **replace** the existing bar chart (lines 117–124) with a heatmap using the full-universe monthly data.

### What to add (replacing lines 117–124)

```python
# ── Aylık getiri takvimi (heatmap, tüm evren medyanı ile) ─────────────
monthly_hm = data.monthly_returns(ft)
if monthly_hm is not None and not monthly_hm.empty and code in monthly_hm.columns:
    st.plotly_chart(
        figures.fig_monthly_heatmap(monthly_hm, [code],
                                    median_label="Evren medyanı"),
        width="stretch")
```

### Why this works

| Aspect | Detail |
|--------|--------|
| Data source | `data.monthly_returns(ft)` — cached full-universe monthly data |
| Displayed fund(s) | `[code]` — just the selected fund |
| Median row | Auto-added by `fig_monthly_heatmap` as "Evren medyanı" |
| Visual | RdYlGn heatmap, 0-centered, shows monthly return magnitude/color |
| Caching | Already cached in `data.py:107`, no performance concern |

### No other files need changes

- `figures.fig_monthly_heatmap` already handles single-fund lists correctly
- `data.monthly_returns` already exists and is cached

## Files Modified

| File | Change |
|------|--------|
| [`tefas/dashboard/views/fon_detay.py`](tefas/dashboard/views/fon_detay.py) | Replace lines 117–124 (bar chart) with heatmap call using `data.monthly_returns(ft)` + `figures.fig_monthly_heatmap` |

## Visual Result

The heatmap will show:
- **1 row**: the selected fund (colored by monthly return)
- **1 row**: "Evren medyanı" — the median of all funds in that month
- **Columns**: each month (e.g., 2024-01, 2024-02, ...)
- **Color**: green = positive, red = negative, intensity scales with magnitude
- **Tooltip**: hover shows exact percentage
