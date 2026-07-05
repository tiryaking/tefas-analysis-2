"""
Skorlama: yüzdelik-sıra tabanlı composite skor ve risk profilleri.

FINDING #5 — v1 `advanced_portfolio_analyzer.py` 1300+ satırdı ve çoğu ölü koddu
(opsiyonel optimizer/stress/rebalancing dalları, hiç kurulu olmayan scipy'ye
bağımlı). Burada yalnızca raporun gerçekten kullandığı skorlama mantığı
(percentile-rank, üçgensel volatilite bandı).

NOT — Alpha/Beta/Treynor/Information Ratio metrikleri kaldırıldı: geçerli bir
piyasa benchmark'ı (örn. XU100) fon veri setinde bulunmadığından bunlar sessizce
eşit-ağırlıklı fon-ortalamasına göre hesaplanıyordu; bu CAPM/aktif-getiri
yorumunu geçersiz kılıyordu. Yanlış güven vermemek için tamamen çıkarıldı.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, themes


def shrunk_annual_return(df: pd.DataFrame, full_days: int | None = None) -> pd.Series:
    """Kısa geçmiş gürültüsüne karşı güvenilirlik-ağırlıklı getiri (shrinkage).

    63 işlem gününden yıllıklandırılan bir CAGR çok gürültülüdür; sert bir gün
    eşiği ise uçurum etkisi yaratır (188. gün ile 189. gün arasında skor
    sıçrar). Bunun yerine aktüeryal güvenilirlik yaklaşımı:

        w = clip(Skor_Penceresi_Gun / full_days, 0, 1)
        hedef = tema medyan getirisi (temada >= THEME_MIN_FUNDS fon varsa),
                yoksa evren medyanı
        düzeltilmiş = w * Yillik_Getiri + (1 - w) * hedef

    Tam pencereli fonlarda (w=1) getiri değişmez; kısa geçmişliler akran
    medyanına doğru çekilir. Yalnızca SKORLAMA girdisidir — raporda gösterilen
    `Yillik_Getiri` değişmez. NaN getiri NaN kalır. `Skor_Penceresi_Gun`
    sütunu yoksa (kısmi tablo) w=1 kabul edilir.
    """
    if full_days is None:
        full_days = config.RETURN_FULL_CREDIBILITY_DAYS
    ret = pd.to_numeric(_col(df, "Yillik_Getiri"), errors="coerce")
    days = pd.to_numeric(_col(df, "Skor_Penceresi_Gun"), errors="coerce")
    w = (days / float(full_days)).clip(0.0, 1.0).fillna(1.0)

    theme_col = df["Tema"] if "Tema" in df.columns else pd.Series("Diğer", index=df.index)
    grp = ret.groupby(theme_col)
    theme_med = grp.transform("median")
    theme_n = grp.transform("count")
    universe_med = ret.median()
    target = theme_med.where(theme_n >= config.THEME_MIN_FUNDS, universe_med)
    target = target.fillna(ret)   # hedef üretilemiyorsa getiri olduğu gibi kalır
    return w * ret + (1.0 - w) * target


def _pct_rank(s: pd.Series, ascending: bool = True, fill: float = 50.0) -> pd.Series:
    """Bir metriği evren içindeki yüzdelik sırasına (0–100) çevirir. Outlier'a dayanıklı."""
    s = pd.to_numeric(s, errors="coerce")
    return (s.rank(pct=True, ascending=ascending) * 100.0).fillna(fill)


def _triangular(pct_series: pd.Series, peak: float = 50.0) -> pd.Series:
    """Tepe noktada 100, uçlara doğru lineer azalan bant-uyum skoru."""
    dist = (pct_series - peak).abs()
    return (1.0 - dist / max(peak, 100.0 - peak)) * 100.0


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Sütun yoksa nötr (NaN) seri döndürür — skorlama kısmi tablolarda çökmesin."""
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index)


def _consistency(df: pd.DataFrame) -> pd.Series:
    """
    Tutarlılık skoru — Overall'daki metrikleri (drawdown/Sortino) TEKRAR
    KULLANMAZ (çifte sayımı önler). Gürültülü günlük çarpıklık da çıkarıldı.
    Bunun yerine getiri tutarlılığının doğrudan ölçüleri:
        %45 pozitif GÜN oranı, %35 pozitif AY oranı, %20 düşük aylık dağılım.
    Aylık ölçüler yoksa (kısmi tablo) günlük orana geri düşer.
    """
    return (_pct_rank(_col(df, "Pozitif_Gun_Orani")) * 0.45 +
            _pct_rank(_col(df, "Pozitif_Ay_Orani")) * 0.35 +
            _pct_rank(_col(df, "Aylik_Getiri_Std"), ascending=False) * 0.20).fillna(50)


def _momentum(df: pd.DataFrame) -> pd.Series:
    return df["Getiri_1A"].fillna(0) * 0.6 + df["Getiri_3A"].fillna(0) * 0.4


def _risk_profiles(df: pd.DataFrame, consistency: pd.Series) -> dict[str, pd.Series]:
    vol_low = _pct_rank(df["Yillik_Volatilite"], ascending=False)
    vol_pct = _pct_rank(df["Yillik_Volatilite"])
    dd_low = _pct_rank(df["Max_Drawdown"], ascending=False)
    sharpe = _pct_rank(df["Sharpe_Orani"])
    sortino = _pct_rank(df["Sortino_Orani"])
    calmar = _pct_rank(df["Calmar_Orani"])
    # Getiri ekseni yıllıklandırılmış (CAGR) getiriyi kullanır; böylece 1 yıldan
    # kısa geçmişli fonlar da aynı (yıllık) bazda kıyaslanır. Kısa geçmiş
    # gürültüsüne karşı güvenilirlik-düzeltilmiş getiri (shrinkage) esas alınır
    # — composite ile tutarlı (bkz. shrunk_annual_return).
    ret_src = df["Yillik_Getiri_Duzeltilmis"] if "Yillik_Getiri_Duzeltilmis" in df.columns else df["Yillik_Getiri"]
    ret_1y = _pct_rank(ret_src)
    pos_days = _pct_rank(df["Pozitif_Gun_Orani"])
    momentum_rank = _pct_rank(_momentum(df))
    vol_band_mid = _triangular(vol_pct, peak=50.0)

    # NOT: Eski `rf_gate` kaldırıldı: kalan tüm fonlara 100 verip yalnızca genç
    # (getirisi NaN) fonları kasıtsız cezalandırıyordu. Boşalan %10 düşük-vol ve
    # istikrara dağıtıldı. (rf artık uygunluk filtresi de değil; compute_metrics
    # yalnızca bilgilendirici `Rf_Ustu` bayrağı üretir.)
    calmar_gate = pd.Series(np.where((df["Calmar_Orani"] > 0).fillna(False), 100.0, 40.0), index=df.index)

    return {
        "Conservative": vol_low * 0.40 + dd_low * 0.30 + pos_days * 0.15 +
                        consistency * 0.15,
        "Balanced": sortino * 0.30 + calmar * 0.25 + vol_band_mid * 0.20 +
                    ret_1y * 0.15 + consistency * 0.10,
        "Moderate": sharpe * 0.40 + ret_1y * 0.25 + vol_band_mid * 0.20 +
                    consistency * 0.15,
        "Aggressive": ret_1y * 0.40 + momentum_rank * 0.25 + vol_pct * 0.15 +
                      calmar * 0.10 + calmar_gate * 0.10,
    }


def score_funds(metrics: pd.DataFrame, combined: pd.DataFrame | None = None,
                risk_free_rate: float = 0.0) -> pd.DataFrame:
    """
    Metrik tablosuna composite skor, risk-profili skorları, Consistency ve
    Momentum ekler. Skorlu DataFrame döndürür.

    `combined` parametresi geriye-uyum için korunuyor; skorlama artık tamamen
    metrik tablosundan hesaplandığı için kullanılmıyor.
    """
    df = metrics[metrics["Veri_Noktasi_Sayisi"] >= config.MIN_DATA_POINTS].copy().reset_index(drop=True)
    if df.empty:
        return df

    # Tema ataması (akran kıyası ve rapor için çıktıda kalıcı) + güvenilirlik-
    # düzeltilmiş getiri: kısa geçmişli fonların gürültülü yıllıklandırılmış
    # getirisi tema/evren medyanına doğru çekilir (yalnızca skorlama girdisi).
    df = themes.add_theme(df)
    df["Yillik_Getiri_Duzeltilmis"] = shrunk_annual_return(df).round(4)

    consistency = _consistency(df)

    df["Consistency_Score"] = consistency.round(1)
    df["Momentum_Score"] = _momentum(df).round(2)
    for profile, scores in _risk_profiles(df, consistency).items():
        df[f"{profile}_Score"] = scores.round(1)

    # Tema-içi akran yüzdeliği (0–100): fon, KENDİ temasındaki fonlara göre
    # nerede? Küçük temalarda (< THEME_MIN_FUNDS) NaN — raporda "—" gösterilir;
    # composite'te ise fonun evren getiri yüzdeliğiyle doldurulur ki niş temada
    # olmak ne ceza ne de ödül olsun.
    df["Tema_Rel_Skor"] = themes.theme_relative_percentile(
        df, value_col="Yillik_Getiri_Duzeltilmis").round(1)

    # Composite (Overall) skor — yüzdelik-sıra ağırlıklı. Tek ve merkezi ağırlık
    # tanımı: Sharpe %25, Sortino %15, düşük drawdown %20, yıllık getiri %20,
    # tema-içi getiri %5, tutarlılık %7,5, likidite %7,5. Getiri etkisi toplamda
    # %25'te sabit kaldı (%20 mutlak + %5 akran-göreli). Sharpe/Sortino yüksek
    # korelasyonlu olduğundan toplam ağırlıkları sınırlı; drawdown ve Sortino
    # YALNIZCA burada yer alır (Consistency onları tekrar kullanmaz → çifte
    # sayım yok).
    liq = (_pct_rank(df["Fon_Toplam_Deger_Milyon_TL"])
           if "Fon_Toplam_Deger_Milyon_TL" in df.columns
           else pd.Series(50.0, index=df.index))
    # Güvenilirlik-düzeltilmiş getiri yüzdeliği. Çok kısa geçmişte NaN olabilir
    # (cagr min_days=63); nötr (50) yerine düşük yüzdelikle (25) doldurulur ki
    # kısa geçmiş yapay avantaj sağlamasın.
    ret_pct = _pct_rank(df["Yillik_Getiri_Duzeltilmis"], fill=25.0)
    tema_rel = pd.to_numeric(df["Tema_Rel_Skor"], errors="coerce").fillna(ret_pct)
    df["Overall_Score"] = (
        0.25 * _pct_rank(df["Sharpe_Orani"]) +
        0.15 * _pct_rank(df["Sortino_Orani"]) +
        0.20 * _pct_rank(df["Max_Drawdown"], ascending=False) +
        0.20 * ret_pct +
        0.05 * tema_rel +
        0.075 * consistency +
        0.075 * liq
    ).round(1)

    return df
