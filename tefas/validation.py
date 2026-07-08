"""Walk-forward model validation summaries shared by report and dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config

REQUIRED_BACKTEST_COLUMNS = {"Ufuk_Ay", "Portfoy_Getiri", "Evren_Ort", "Fark"}
TURNOVER_COLUMNS = ("Turnover", "Devir", "Portfoy_Devir")


@dataclass(frozen=True)
class WalkForwardSummary:
    """Controlled validation result: table plus status for user-facing surfaces."""

    table: pd.DataFrame
    status: str
    message: str
    source: Path
    missing_columns: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "ok" and not self.table.empty


def summarize_walk_forward_csv(path: Path) -> WalkForwardSummary:
    """Load a walk-forward CSV and return a product-ready validation summary.

    Status values:
    - ``ok``: summary table is available.
    - ``missing``: CSV was not found.
    - ``empty``: CSV exists but has no fold rows.
    - ``invalid``: CSV cannot be read or lacks required columns.
    """
    p = Path(path)
    if not p.exists():
        return WalkForwardSummary(
            table=pd.DataFrame(),
            status="missing",
            message=f"Validasyon dosyası bulunamadı: {p.name}",
            source=p,
        )

    try:
        folds = pd.read_csv(p, encoding=config.OUTPUT_ENCODING)
    except Exception as exc:  # noqa: BLE001
        return WalkForwardSummary(
            table=pd.DataFrame(),
            status="invalid",
            message=f"Validasyon dosyası okunamadı: {p.name} ({exc})",
            source=p,
        )

    if folds.empty:
        return WalkForwardSummary(
            table=pd.DataFrame(),
            status="empty",
            message=f"Validasyon dosyası boş: {p.name}",
            source=p,
        )

    missing = tuple(sorted(REQUIRED_BACKTEST_COLUMNS - set(folds.columns)))
    if missing:
        return WalkForwardSummary(
            table=pd.DataFrame(),
            status="invalid",
            message=f"Validasyon dosyasında eksik kolon var: {', '.join(missing)}",
            source=p,
            missing_columns=missing,
        )

    folds = folds.copy()
    for col in REQUIRED_BACKTEST_COLUMNS:
        folds[col] = pd.to_numeric(folds[col], errors="coerce")
    folds = folds.dropna(subset=["Ufuk_Ay", "Fark"])
    if folds.empty:
        return WalkForwardSummary(
            table=pd.DataFrame(),
            status="empty",
            message=f"Validasyon dosyasında özetlenebilir kat yok: {p.name}",
            source=p,
        )

    agg = {
        "Kat_Sayisi": ("Fark", "size"),
        "Portfoy_Ort": ("Portfoy_Getiri", "mean"),
        "Evren_Ort": ("Evren_Ort", "mean"),
        "Ort_Fark": ("Fark", "mean"),
        "Medyan_Fark": ("Fark", "median"),
        "Isabet_Orani": ("Fark", lambda s: float((s > 0).mean())),
    }
    turnover_col = next((c for c in TURNOVER_COLUMNS if c in folds.columns), None)
    if turnover_col:
        folds[turnover_col] = pd.to_numeric(folds[turnover_col], errors="coerce")
        agg["Turnover"] = (turnover_col, "mean")

    table = folds.groupby("Ufuk_Ay").agg(**agg).round(4).reset_index()
    if "Model_Version" in folds.columns:
        versions = folds.groupby("Ufuk_Ay")["Model_Version"].agg(
            lambda s: ", ".join(sorted({str(v) for v in s.dropna().unique()})))
        table = table.merge(versions.rename("Model_Version"), on="Ufuk_Ay", how="left")
    return WalkForwardSummary(
        table=table,
        status="ok",
        message=f"Walk-forward validasyon özeti hazır: {p.name}",
        source=p,
    )


def backtest_summary_from_csv(path: Path) -> pd.DataFrame:
    """Backward-compatible table-only wrapper for older call sites/tests."""
    return summarize_walk_forward_csv(path).table
