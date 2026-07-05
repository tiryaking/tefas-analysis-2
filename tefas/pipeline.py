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


def run(fund_type: str = "YAT", risk_free_rate: float | None = None, *,
        include: list[str] | None = None, exclude: list[str] | None = None,
        active_only: bool = True, keep_suspect: bool = False,
        min_aum: float | None = None, min_fund_age: float | None = None,
        write_report: bool = True) -> Artifacts:
    """Tüm pipeline'ı bellekte çalıştırır; çıktı dosya yollarını döndürür.

    `risk_free_rate=None` → `tefas.config.json`'daki `risk_free_rate` (yoksa
    `config.DEFAULT_MACRO` değeri) kullanılır.
    """
    setup_utf8()
    if risk_free_rate is None:
        risk_free_rate = config.macro().risk_free_rate
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


def run_comparison(fund_type: str, risk_free_rate: float, codes: list[str]) -> int:
    """
    Karşılaştırma modu: verilen fon kodlarını "olduğu gibi" (aktiflik/rf/AUM/yaş
    filtresi UYGULAMADAN) yükler, ortak pencerede metriklerini hesaplar ve
    karşılaştırma PDF'i üretir. Yalnızca verisi kullanılamayacak kadar az olan
    (< MIN_DATA_POINTS gözlem) fonlar atlanır.
    """
    setup_utf8()
    paths = config.paths_for(fund_type)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*64}\nTEFAS KARŞILAŞTIRMA — {paths.fund_name} | rf=%{risk_free_rate:.1f}\n{'='*64}")
    print(f"[INFO] İstenen kodlar: {', '.join(codes)}")

    # Tüm fonları yükle (filtre yok) — kodlar olduğu gibi karşılaştırılacak.
    combined = etl.load_combined(fund_type, active_only=False)
    present = set(combined["Fon Kodu"].astype(str).unique())
    found = [c for c in codes if c in present]
    missing = [c for c in codes if c not in present]
    if missing:
        print(f"[WARN] Veri setinde bulunamayan kodlar atlandı: {', '.join(missing)}")
    if len(found) < 2:
        raise SystemExit(f"[HATA] Karşılaştırılabilir en az 2 fon bulunamadı (bulunan: {found or 'yok'}).")

    subset = combined[combined["Fon Kodu"].astype(str).isin(found)].copy()
    met = metrics.compute_metrics(subset, risk_free_rate, keep_suspect=True)

    # Verisi yetersiz fonları at (anlamlı metrik üretilemez).
    thin = met["Veri_Noktasi_Sayisi"] < config.MIN_DATA_POINTS
    if thin.any():
        print(f"[WARN] Yetersiz veri ({config.MIN_DATA_POINTS} gözlemden az) nedeniyle atlanan: "
              f"{', '.join(met.loc[thin, 'Fon Kodu'])}")
        met = met[~thin].copy()
    if len(met) < 2:
        raise SystemExit("[HATA] Yeterli veriye sahip en az 2 fon kalmadı.")

    order = {c: i for i, c in enumerate(found)}
    met["_order"] = met["Fon Kodu"].map(order)
    met = met.sort_values("_order").drop(columns="_order").reset_index(drop=True)

    out = report.generate_comparison(met, subset, fund_type, risk_free_rate,
                                     met["Fon Kodu"].tolist())
    print(f"\n[DONE] Karşılaştırma raporu: {out}")
    return 0


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Önbellek yok: {path} — önce `tefas run` çalıştırın.")
    return pd.read_parquet(path)
