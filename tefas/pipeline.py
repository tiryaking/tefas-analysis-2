"""
In-process pipeline orchestrator.

FINDING #1 & #2 — v1 `run_analysis.py` her aşamayı ayrı bir `subprocess` olarak
başlatıyor ve aşamalar ~37 MB'lık bir CSV'yi üç kez tekrar okuyup yazıyordu.
Burada her aşama bir fonksiyon; DataFrame'ler bellekte aktarılır. Ara çıktılar
**parquet** olarak önbelleğe alınır (tipli, küçük, hızlı); insan için ayrıca CSV
yazılır. CSV round-trip'i kalktığı için belirgin biçimde hızlıdır.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config, etl, metrics, scoring, report
from .io_utils import setup_utf8


@dataclass
class Artifacts:
    combined: Path
    metrics_csv: Path
    scored_csv: Path
    report_pdf: Path


def run(fund_type: str = "YAT", risk_free_rate: float = 45.0, *,
        include: list[str] | None = None, exclude: list[str] | None = None,
        active_only: bool = True, keep_suspect: bool = False,
        min_aum: float | None = None, min_fund_age: float | None = None,
        write_report: bool = True) -> Artifacts:
    """Tüm pipeline'ı bellekte çalıştırır; çıktı dosya yollarını döndürür."""
    setup_utf8()
    paths = config.paths_for(fund_type)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*64}\nTEFAS PIPELINE — {paths.fund_name} | rf=%{risk_free_rate:.1f}\n{'='*64}")

    # 1) ETL (bellekte)
    combined = etl.load_combined(fund_type, include=include, exclude=exclude, active_only=active_only)
    combined.to_parquet(paths.combined_parquet, index=False)

    # 2) Metrikler
    met = metrics.compute_metrics(combined, risk_free_rate, keep_suspect=keep_suspect,
                                  min_aum=min_aum, min_fund_age=min_fund_age)
    met.to_parquet(paths.metrics_parquet, index=False)
    met.to_csv(paths.metrics_csv, index=False, encoding=config.OUTPUT_ENCODING)
    print(f"[INFO] Metrikler: {len(met)} fon -> {paths.metrics_csv.name}")

    # 3) Skorlama
    scored = scoring.score_funds(met, combined, risk_free_rate)
    scored.to_parquet(paths.scored_parquet, index=False)
    scored.to_csv(paths.scored_csv, index=False, encoding=config.OUTPUT_ENCODING)
    print(f"[INFO] Skorlu metrikler: {len(scored)} fon -> {paths.scored_csv.name}")

    # 4) Rapor
    if write_report:
        report.generate(scored, met, fund_type, risk_free_rate, combined=combined,
                        include=include, exclude=exclude)

    print(f"\n[DONE] Tamamlandı. Rapor: {paths.report_pdf}")
    return Artifacts(paths.combined_parquet, paths.metrics_csv, paths.scored_csv, paths.report_pdf)


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Önbellek yok: {path} — önce `tefas run` çalıştırın.")
    return pd.read_parquet(path)
