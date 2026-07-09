"""
Paylaşılan metin/biçimlendirme yardımcıları (report.py'den ayrıldı).

Sayı biçimlendirme (`fmt`/`pct`), ad kısaltma, fon yatırım-gerekçesi
(`build_rationale`) ve config'den üretilen metodoloji metinleri burada saf
fonksiyonlar olarak yaşar — böylece dashboard bunları reportlab'ı import
etmeden kullanabilir. report.py bu adları geri import eder (PDF çıktısı birebir
aynı kalır).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config


def fmt(x, dec=2, suffix="", dash="—"):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return dash
    try:
        return f"{float(x):,.{dec}f}{suffix}"
    except (ValueError, TypeError):
        return str(x)


def pct(x, dec=1):
    return fmt(x, dec, "%") if pd.notna(x) else "—"


def short_name(name, maxlen=46):
    s = str(name)
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def build_rationale(row):
    bits = []
    sharpe = row.get("Sharpe_Orani")
    if pd.notna(sharpe):
        if sharpe >= 3:
            bits.append(f"çok güçlü risk-ayarlı getiri (Sharpe {fmt(sharpe,2)})")
        elif sharpe >= 1:
            bits.append(f"sağlam risk-ayarlı getiri (Sharpe {fmt(sharpe,2)})")
    vol = row.get("Yillik_Volatilite")
    if pd.notna(vol):
        if vol < 5:
            bits.append(f"çok düşük volatilite (%{fmt(vol,1)})")
        elif vol < 15:
            bits.append(f"düşük volatilite (%{fmt(vol,1)})")
        elif vol >= 30:
            bits.append(f"yüksek volatilite (%{fmt(vol,1)})")
    dd = row.get("Max_Drawdown")
    if pd.notna(dd) and dd < 5:
        bits.append(f"kontrollü kayıp (Max DD %{fmt(dd,1)})")
    ret = row.get("Yillik_Getiri")
    if pd.notna(ret) and ret >= 60:
        bits.append(f"yüksek yıllık getiri (%{fmt(ret,1)})")
    aum = row.get("Fon_Toplam_Deger_Milyon_TL")
    if pd.notna(aum) and aum >= config.AUM_BONUS_THRESHOLD:
        bits.append("güçlü büyüklük/likidite")
    if not bits:
        bits.append("dengeli genel profil")
    txt = "; ".join(bits[:3])
    return txt[0].upper() + txt[1:] + "."


# ─── Metodoloji (model_config + config sabitlerinden üretilir) ────────────────

_OVERALL_LABELS = {
    "sharpe": "Sharpe", "sortino": "Sortino", "drawdown": "düşük drawdown",
    "return": "yıllık getiri", "theme_relative": "tema-içi getiri",
    "consistency": "tutarlılık", "liquidity": "likidite/AUM",
}


def _weight_phrase(weights: dict[str, float], labels: dict[str, str] | None = None) -> str:
    """{anahtar: ağırlık} → 'Sharpe (%25), Sortino (%15), …' (azalan sırada)."""
    items = sorted(weights.items(), key=lambda kv: -kv[1])
    parts = []
    for key, w in items:
        name = (labels or {}).get(key, key.replace("_", " "))
        parts.append(f"{name} (%{w * 100:g})")   # 0.25→%25, 0.075→%7.5
    return ", ".join(parts)


def methodology_sections(model_cfg=None, mac=None, rf: float | None = None
                         ) -> list[tuple[str, str]]:
    """(başlık, markdown gövde) listesi — ağırlıklar/sabitler değişince metin de
    değişir. Hem dashboard Metodoloji sayfası hem de (istenirse) PDF kullanabilir.
    """
    from . import model_config as _mc
    cfg = model_cfg if model_cfg is not None else _mc.current()
    macro = mac if mac is not None else config.macro()
    rf = rf if rf is not None else macro.risk_free_rate

    overall = _weight_phrase(cfg.overall_weights, _OVERALL_LABELS)
    prof_lines = []
    for name, weights in cfg.profile_weights.items():
        prof_lines.append(f"- **{name}**: {_weight_phrase(weights)}")
    settings = cfg.recommendation_settings

    return [
        ("Model Sürümü & Denetim",
         f"Aktif model: **{cfg.version}** (kaynak: {cfg.source}). Skorlu çıktılar "
         f"`Model_Version` sütununu taşır; ağırlıklar `tefas.model.json` ile "
         f"sürümlenebilir. Bu sayfadaki metinler doğrudan aktif ağırlıklardan üretilir."),
        ("Ortak Değerlendirme Penceresi",
         f"Volatilite, Sharpe, Sortino, Calmar, drawdown ve VaR gibi risk metrikleri "
         f"tüm fonlarda ortak, gerilemeli ~1 işlem yılı (son {config.SCORING_LOOKBACK_DAYS} "
         f"gözlem) penceresinde hesaplanır; farklı geçmiş uzunluğundaki fonlar aynı dönem "
         f"üzerinden kıyaslanır. Daha kısa geçmişliler tüm geçmişini kullanır ve '*' ile "
         f"işaretlenir."),
        ("Composite Skor Ağırlıkları",
         f"Yüzdelik-sıra ağırlıklı bileşim: {overall}. Yüzdelik-sıra skorları uç değerlere "
         f"dayanıklıdır ve tüm evren üzerinden hesaplanır."),
        ("Risk Profili Ağırlıkları",
         "Dört profil skoru şu ağırlıklarla hesaplanır:\n" + "\n".join(prof_lines)),
        ("Öneri Seçim Kuralları",
         f"Tema tavanı: bir temadan portföye en çok **{settings.get('theme_cap', 1)}** fon "
         f"(walk-forward ile seçildi — çeşitlilik sinyalin taşıyıcısı). "
         f"1 yıldan kısa geçmişli fonlar ana öneriden {'çıkarılır' if settings.get('exclude_young', True) else 'çıkarılmaz'} "
         f"ve izleme listesine ayrılır (young_history_days="
         f"{settings.get('young_history_days', config.TRADING_DAYS_PER_YEAR)}). AUM bir getiri "
         f"skoru değil, likidite/ölçek sinyalidir."),
        ("Kısa Geçmiş Düzeltmesi (Shrinkage)",
         f"1 yıldan kısa pencereden yıllıklandırılan getiri gürültülüdür; skorlamada getiri, "
         f"güvenilirlik ağırlığı w = pencere günü / {config.RETURN_FULL_CREDIBILITY_DAYS} ile "
         f"akran (tema, en az {config.THEME_MIN_FUNDS} fon) medyanına çekilir. Tablolardaki "
         f"getiriler HAM değerlerdir; düzeltme yalnızca skor girdisidir."),
        ("Risksiz Faiz & Winsorizasyon",
         f"Rf = %{rf:.1f} (tefas.config.json). Volatilite/Sortino ±%{config.DAILY_RETURN_CLIP:.0f} "
         f"winsorize edilmiş günlük getirilerle; VaR/CVaR, çarpıklık ve en iyi/kötü gün ise "
         f"HAM getirilerle hesaplanır — kuyruk metrikleri gerçek kuyrukları görmelidir."),
        ("Veri Kalitesi & Survivorship",
         f"Tek günde > %{config.DATA_QUALITY_MAX_DAILY_MOVE:.0f} hareket eden fonlar şüpheli "
         f"kabul edilip analizden çıkarılır. Analiz yalnızca aktif fonları kapsar; kapanmış "
         f"fonlar veri setinde olmadığından geçmiş istatistikler iyimser yönde sapabilir "
         f"(survivorship bias)."),
    ]
