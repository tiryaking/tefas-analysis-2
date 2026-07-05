"""
Altın-değer testleri: her risk metriği elle hesaplanmış sonuçlara karşı.

Bunlar v1'de eksikti (FINDING #3). Sharpe/Sortino/drawdown/CAGR/volatilite tam
da sessizce yanlış hesaplanabilen fonksiyonlardır; her biri burada bağımsız
doğrulanıyor.
"""
import numpy as np
import pandas as pd
import pytest

from tefas import metrics as m


def test_annualized_volatility():
    # std(ddof=1) of [1,-1,1,-1] = sqrt(4/3); * sqrt(252)
    expected = np.sqrt(4 / 3) * np.sqrt(252)
    assert m.annualized_volatility([1, -1, 1, -1]) == pytest.approx(expected, rel=1e-9)
    assert m.annualized_volatility([5]) is np.nan or np.isnan(m.annualized_volatility([5]))
    assert np.isnan(m.annualized_volatility([0, 0, 0]))   # sıfır std -> NaN


def test_cagr():
    assert m.cagr(100, 200, 252) == pytest.approx(100.0)        # 1 yılda 2x
    assert m.cagr(100, 121, 504) == pytest.approx(10.0)         # 2 yılda %21 -> %10/yıl
    assert np.isnan(m.cagr(100, 110, 10))                       # < min_days
    assert np.isnan(m.cagr(0, 110, 252))                        # geçersiz fiyat
    assert np.isnan(m.cagr(1, 1000, 252))                       # cap (abs >= 500)


def test_max_drawdown():
    assert m.max_drawdown([100, 120, 90, 110]) == pytest.approx(25.0)  # 120 -> 90
    assert m.max_drawdown([100, 101, 102]) == pytest.approx(0.0)       # monoton artış
    assert np.isnan(m.max_drawdown([100]))


def test_sharpe_ratio():
    assert m.sharpe_ratio(50, 20, 10) == pytest.approx(2.0)
    assert np.isnan(m.sharpe_ratio(50, 0, 10))     # sıfır vol
    assert np.isnan(m.sharpe_ratio(np.nan, 20, 10))


def test_sortino_ratio():
    # downside dev of [1,-1,1,-1] vs rf=0: sqrt(mean([0,1,0,1])) * sqrt(252)
    dd = np.sqrt(0.5) * np.sqrt(252)
    assert m.sortino_ratio([1, -1, 1, -1], 50, 0) == pytest.approx(50 / dd, rel=1e-9)
    # downside yok -> annualized_downside ~0 < MIN_DOWNSIDE -> NaN
    assert np.isnan(m.sortino_ratio([1, 1, 1, 1], 50, 0))


def test_calmar_ratio():
    assert m.calmar_ratio(50, 25, 10) == pytest.approx(1.6)
    assert np.isnan(m.calmar_ratio(50, 0.1, 10))   # mdd < MIN_DD
    assert np.isnan(m.calmar_ratio(np.nan, 25, 10))


def test_after_fee_return():
    # Yalnızca yönetim ücreti düşülür; geçersiz stopaj sezgiseli kaldırıldı.
    # Ücret parametresi açık verilir ki test diskteki config'e bağımlı olmasın.
    assert m.after_fee_return(70, fee=1.0) == pytest.approx(69.0)
    assert m.after_fee_return(40, fee=1.0) == pytest.approx(39.0)
    assert np.isnan(m.after_fee_return(np.nan))


def test_real_return():
    assert m.real_return(55, inflation=55) == pytest.approx(0.0)
    assert m.real_return(110, inflation=55) == pytest.approx((2.10 / 1.55 - 1) * 100)


def test_period_return():
    dates = pd.to_datetime(["2025-01-01", "2025-06-01", "2025-07-01"]).to_numpy()
    prices = np.array([100.0, 110.0, 121.0])
    last_ts = pd.Timestamp("2025-07-01")
    assert m.period_return(dates, prices, last_ts, pd.DateOffset(months=1)) == pytest.approx(10.0)


def test_compute_metrics_integration():
    """Sentetik 2-fonlu evrende uçtan uca metrik üretimi."""
    rng = pd.date_range("2025-01-01", periods=120, freq="B")
    rows = []
    for code, drift in [("AAA", 1.002), ("BBB", 1.001)]:
        price = 100.0
        for d in rng:
            price *= drift
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} FON",
                         "Tarih": d, "Fiyat": price, "Fon Toplam Deger": 5e8})
    combined = pd.DataFrame(rows)
    out = m.compute_metrics(combined, risk_free_rate=0.0)
    assert set(out["Fon Kodu"]) == {"AAA", "BBB"}
    assert {"Sharpe_Orani", "Yillik_Getiri", "Max_Drawdown"} <= set(out.columns)
    # Yeni sütunlar: pencere/kuruluş referansları, aylık tutarlılık, uygunluk
    assert {"Yillik_Getiri_Kurulus", "Volatilite_Kurulus", "Skor_Penceresi_Gun",
            "Pozitif_Ay_Orani", "Uygun"} <= set(out.columns)
    # Yükselen seri: pozitif yıllık getiri, drawdown ~0
    assert (out["Yillik_Getiri"] > 0).all()
    assert (out["Max_Drawdown"].fillna(0) < 1).all()
    # 120 gözlem < 253 → pencere tüm seri, kuruluş referansı ile örtüşür
    assert (out["Skor_Penceresi_Gun"] == 120).all()
    assert out["Yillik_Getiri"].to_numpy() == pytest.approx(out["Yillik_Getiri_Kurulus"].to_numpy())


def test_trailing_window_slicing():
    """Uzun geçmişli fonlarda risk metrikleri son SCORING_LOOKBACK_DAYS gözleme kırpılır."""
    from tefas import config
    lb = config.SCORING_LOOKBACK_DAYS
    # İlk yarı düz (getiri yok), son pencere güçlü yükseliş → windowed CAGR yüksek,
    # kuruluş CAGR daha düşük olmalı.
    n = lb + 200
    rng = pd.date_range("2023-01-02", periods=n, freq="B")
    prices, price = [], 100.0
    for i in range(n):
        price *= 1.0 if i < 200 else 1.001
        prices.append(price)
    combined = pd.DataFrame({"Fon Kodu": "AAA", "Fon Adi": "AAA FON",
                             "Tarih": rng, "Fiyat": prices, "Fon Toplam Deger": 5e8})
    out = m.compute_metrics(combined, risk_free_rate=0.0).iloc[0]
    assert out["Skor_Penceresi_Gun"] == lb + 1                 # yalnızca son pencere
    assert out["Yillik_Getiri"] > out["Yillik_Getiri_Kurulus"]  # pencere kuruluşu aşar


def test_short_fund_return_annualized():
    """1 yıldan kısa geçmişli fonda Yillik_Getiri (yıllıklandırılmış) > Getiri_1Y (kümülatif)."""
    rng = pd.date_range("2025-06-01", periods=170, freq="B")   # ~8 ay
    price, rows = 100.0, []
    for d in rng:
        price *= 1.002
        rows.append({"Fon Kodu": "SHT", "Fon Adi": "SHORT FON", "Tarih": d,
                     "Fiyat": price, "Fon Toplam Deger": 5e8})
    out = m.compute_metrics(pd.DataFrame(rows), risk_free_rate=0.0).iloc[0]
    assert out["Skor_Penceresi_Gun"] < 252                     # 1 yıldan kısa
    assert out["Getiri_1Y"] > 0 and out["Yillik_Getiri"] > 0
    assert out["Yillik_Getiri"] > out["Getiri_1Y"]            # yıllıklandırma kümülatifi aşar


def test_eligibility_mask_not_dropped():
    """rf artık uygunluk kriteri değil: satır düşürmez, Uygun'u etkilemez;
    yalnızca bilgilendirici `Rf_Ustu` bayrağını belirler."""
    rng = pd.date_range("2025-01-01", periods=300, freq="B")
    rows = []
    for code, drift in [("HIGH", 1.003), ("LOW", 1.0002)]:
        price = 100.0
        for d in rng:
            price *= drift
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} FON",
                         "Tarih": d, "Fiyat": price, "Fon Toplam Deger": 5e8})
    combined = pd.DataFrame(rows)
    out = m.compute_metrics(combined, risk_free_rate=45.0)
    assert set(out["Fon Kodu"]) == {"HIGH", "LOW"}     # ikisi de KORUNUR
    elig = dict(zip(out["Fon Kodu"], out["Uygun"]))
    assert elig["HIGH"] and elig["LOW"]                # rf uygunluğu etkilemez
    rf_flag = dict(zip(out["Fon Kodu"], out["Rf_Ustu"]))
    assert rf_flag["HIGH"] and not rf_flag["LOW"]      # bayrak doğru ayrışır


def test_aum_age_eligibility():
    """AUM/yaş kriterleri Uygun maskesini belirlemeye devam eder."""
    rng = pd.date_range("2025-01-01", periods=300, freq="B")
    rows = []
    for code, aum in [("BIG", 5e8), ("TINY", 1e6)]:
        price = 100.0
        for d in rng:
            price *= 1.002
            rows.append({"Fon Kodu": code, "Fon Adi": f"{code} FON",
                         "Tarih": d, "Fiyat": price, "Fon Toplam Deger": aum})
    out = m.compute_metrics(pd.DataFrame(rows), risk_free_rate=45.0, min_aum=50.0)
    elig = dict(zip(out["Fon Kodu"], out["Uygun"]))
    assert elig["BIG"] and not elig["TINY"]
