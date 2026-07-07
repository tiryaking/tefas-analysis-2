"""
Kişisel portföy takibi (tefas/holdings.py) için altın-değer testleri.

FIFO, XIRR ve TWR elle doğrulanmış küçük senaryolarla test edilir; değerleme
delist edilmiş (NAV'sız) kodda çökmek yerine bayrak üretmelidir.
"""
import numpy as np
import pandas as pd
import pytest

from tefas import holdings as h


def _txns(rows):
    df = pd.DataFrame(rows, columns=["Tarih", "Fon Kodu", "Islem", "Adet", "Fiyat"])
    df["Tarih"] = pd.to_datetime(df["Tarih"])
    df["Not"] = ""
    return df.sort_values(["Tarih", "Fon Kodu"]).reset_index(drop=True)


# ─── FIFO ─────────────────────────────────────────────────────────────────────

def test_fifo_partial_sell_golden():
    # 100@10 + 100@20 al; 150@30 sat.
    # Realize = 100*(30-10) + 50*(30-20) = 2500; açık: 50 adet @20 (maliyet 1000).
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 100, 10.0),
        ("2025-02-03", "AAA", "ALIS", 100, 20.0),
        ("2025-03-03", "AAA", "SATIS", 150, 30.0),
    ])
    pos = h.positions(txns)
    row = pos.iloc[0]
    assert row["Adet"] == pytest.approx(50)
    assert row["Maliyet"] == pytest.approx(1000.0)
    assert row["Ortalama_Maliyet"] == pytest.approx(20.0)
    assert row["Realize_KZ"] == pytest.approx(2500.0)


def test_fifo_full_close_keeps_realized():
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 10, 5.0),
        ("2025-01-10", "AAA", "SATIS", 10, 7.0),
    ])
    pos = h.positions(txns)
    assert pos.iloc[0]["Adet"] == 0
    assert pos.iloc[0]["Realize_KZ"] == pytest.approx(20.0)
    assert np.isnan(pos.iloc[0]["Ortalama_Maliyet"])


def test_fifo_oversell_raises():
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 10, 5.0),
        ("2025-01-10", "AAA", "SATIS", 15, 7.0),
    ])
    with pytest.raises(ValueError, match="eldekinden fazla"):
        h.positions(txns)


# ─── Değerleme ────────────────────────────────────────────────────────────────

def _combined(prices_by_code):
    """{kod: [(tarih, fiyat), ...]} -> combined benzeri uzun frame."""
    rows = []
    for code, series in prices_by_code.items():
        for d, p in series:
            rows.append({"Tarih": pd.Timestamp(d), "Fon Kodu": code, "Fiyat": p})
    return pd.DataFrame(rows)


def test_valuation_golden_and_delisted_flag():
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 100, 10.0),
        ("2025-01-02", "GONE", "ALIS", 10, 50.0),
    ])
    combined = _combined({
        "AAA": [("2025-01-02", 10.0), ("2025-06-02", 12.0)],
        # GONE veri setinde yok (delist / yazım hatası senaryosu)
        "ZZZ": [("2025-06-02", 1.0)],
    })
    val = h.valuation(h.positions(txns), combined)
    aaa = val[val["Fon Kodu"] == "AAA"].iloc[0]
    gone = val[val["Fon Kodu"] == "GONE"].iloc[0]

    assert aaa["Deger"] == pytest.approx(1200.0)
    assert aaa["Deger_KZ"] == pytest.approx(200.0)
    assert aaa["Getiri_Pct"] == pytest.approx(20.0)
    assert not aaa["Veri_Bayat"]
    assert np.isnan(gone["Son_Fiyat"])
    assert gone["Veri_Bayat"]
    # Ağırlık yalnızca değeri bilinen açık pozisyonlardan (AAA) hesaplanır
    assert aaa["Agirlik"] == pytest.approx(1.0)


def test_valuation_stale_nav_flagged():
    txns = _txns([("2025-01-02", "AAA", "ALIS", 1, 10.0),
                  ("2025-01-02", "BBB", "ALIS", 1, 10.0)])
    combined = _combined({
        "AAA": [("2025-06-02", 12.0)],
        "BBB": [("2025-01-15", 11.0)],   # veri sonundan ~5 ay eski
    })
    val = h.valuation(h.positions(txns), combined)
    assert not val.set_index("Fon Kodu").loc["AAA", "Veri_Bayat"]
    assert val.set_index("Fon Kodu").loc["BBB", "Veri_Bayat"]


# ─── XIRR ─────────────────────────────────────────────────────────────────────

def test_xirr_single_flow_matches_cagr():
    # -1000 -> +1210 tam 730 gün (2×365) sonra: (1210/1000)^(1/2)-1 = %10
    flows = [(pd.Timestamp("2023-01-01"), -1000.0),
             (pd.Timestamp("2024-12-31"), 1210.0)]
    assert h.xirr(flows) == pytest.approx(0.10, abs=1e-6)


def test_xirr_sign_convention_negative_return():
    flows = [(pd.Timestamp("2024-01-01"), -1000.0),
             (pd.Timestamp("2025-01-01"), 900.0)]
    r = h.xirr(flows)
    assert r == pytest.approx(-0.0997, abs=2e-3)


def test_xirr_no_sign_change_is_nan():
    flows = [(pd.Timestamp("2024-01-01"), -1000.0),
             (pd.Timestamp("2025-01-01"), -500.0)]
    assert np.isnan(h.xirr(flows))
    assert np.isnan(h.xirr([(pd.Timestamp("2024-01-01"), -1.0)]))


def test_xirr_cashflows_builder():
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 100, 10.0),
        ("2025-02-03", "AAA", "SATIS", 40, 12.0),
    ])
    flows = h.xirr_cashflows(txns, current_value=800.0,
                             as_of=pd.Timestamp("2025-03-01"))
    assert flows[0][1] == pytest.approx(-1000.0)
    assert flows[1][1] == pytest.approx(480.0)
    assert flows[-1] == (pd.Timestamp("2025-03-01"), 800.0)


# ─── TWR ──────────────────────────────────────────────────────────────────────

def test_twr_ignores_deposit_timing():
    # Birim fiyat 10 -> 12.1 (%21). Ara katkı (d1'de 100 adet daha) TWR'ı
    # DEĞİŞTİRMEMELİ: zincir (1.1)(1.0)(1.1) - 1 = %21.
    combined = _combined({"AAA": [
        ("2025-01-02", 10.0), ("2025-01-03", 11.0),
        ("2025-01-06", 11.0), ("2025-01-07", 12.1),
    ]})
    txns = _txns([
        ("2025-01-02", "AAA", "ALIS", 100, 10.0),
        ("2025-01-03", "AAA", "ALIS", 100, 11.0),
    ])
    out = h.twr(txns, combined)
    assert out["twr"] == pytest.approx(0.21, abs=1e-9)


def test_twr_weekend_transaction_snaps_forward():
    # Cumartesi girilen işlem pazartesi NAV gününe yapışır; seri yine hesaplanır.
    combined = _combined({"AAA": [
        ("2025-01-03", 10.0), ("2025-01-06", 10.5), ("2025-01-07", 11.0),
    ]})
    txns = _txns([("2025-01-04", "AAA", "ALIS", 10, 10.0)])   # cumartesi
    series = h.portfolio_value_series(txns, combined)
    # Izgara ilk işlem tarihinden başlar; cumartesi işlemi pazartesiye yapışır.
    assert series.index[0] == pd.Timestamp("2025-01-06")
    assert series.loc[pd.Timestamp("2025-01-06"), "Deger"] == pytest.approx(105.0)
    assert series.loc[pd.Timestamp("2025-01-06"), "Net_Akis"] == pytest.approx(100.0)
    out = h.twr(txns, combined)
    assert out["twr"] == pytest.approx(11.0 / 10.5 - 1.0, abs=1e-9)


# ─── İşlem defteri G/Ç ───────────────────────────────────────────────────────

def test_load_transactions_turkish_decimals_and_dates(tmp_path):
    p = tmp_path / "portfolio_transactions.csv"
    p.write_text(
        "Tarih,Fon Kodu,Islem,Adet,Fiyat,Not\n"
        "2025-03-10,pry,ALIS,\"1.250,5\",\"4,8210\",ilk alım\n"
        "02.06.2025,PRY,satis,400,\"5,9105\",\n",
        encoding="utf-8-sig")
    txns = h.load_transactions(p)
    assert list(txns["Fon Kodu"]) == ["PRY", "PRY"]
    assert txns.loc[0, "Adet"] == pytest.approx(1250.5)
    assert txns.loc[0, "Fiyat"] == pytest.approx(4.8210)
    assert txns.loc[0, "Tarih"] == pd.Timestamp("2025-03-10")
    assert txns.loc[1, "Tarih"] == pd.Timestamp("2025-06-02")   # DD.MM.YYYY
    assert txns.loc[1, "Islem"] == "SATIS"


def test_load_transactions_reports_all_errors(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text(
        "Tarih,Fon Kodu,Islem,Adet,Fiyat,Not\n"
        "2025-13-99,AAA,ALIS,10,5.0,\n"        # geçersiz tarih
        "2025-01-02,AAA,TRANSFER,10,5.0,\n"    # geçersiz işlem
        "2025-01-03,AAA,ALIS,-5,5.0,\n",       # negatif adet
        encoding="utf-8-sig")
    with pytest.raises(ValueError) as exc:
        h.load_transactions(p)
    msg = str(exc.value)
    assert "satır 2" in msg and "satır 3" in msg and "satır 4" in msg


def test_load_transactions_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        h.load_transactions(tmp_path / "yok.csv")


# ─── Skor geçmişi ────────────────────────────────────────────────────────────

def test_score_history_append_dedupes(tmp_path):
    scored = pd.DataFrame({
        "Fon Kodu": ["AAA", "BBB"],
        "Overall_Score": [80.0, 40.0],
        "Conservative_Score": [70.0, 30.0],
        "Balanced_Score": [75.0, 35.0],
        "Moderate_Score": [72.0, 33.0],
        "Aggressive_Score": [68.0, 31.0],
    })
    path = tmp_path / "score_history.parquet"
    snap1 = h.score_snapshot(scored, pd.Timestamp("2025-06-30"))
    h.append_score_history(snap1, path)
    # Aynı tarihe tekrar yazmak güncellemedir (satır sayısı artmaz)
    scored2 = scored.assign(Overall_Score=[85.0, 45.0])
    hist = h.append_score_history(h.score_snapshot(scored2, pd.Timestamp("2025-06-30")), path)
    assert len(hist) == 2
    assert hist.loc[hist["Fon Kodu"] == "AAA", "Overall_Score"].iloc[0] == 85.0
    # Yeni tarih eklenir
    hist = h.append_score_history(h.score_snapshot(scored, pd.Timestamp("2025-07-31")), path)
    assert hist["Tarih"].nunique() == 2 and len(hist) == 4
    # Persentil: yüksek skor yüksek yüzdelik
    top = hist[(hist["Fon Kodu"] == "AAA")]["Overall_Persentil"]
    bot = hist[(hist["Fon Kodu"] == "BBB")]["Overall_Persentil"]
    assert (top > bot.max()).all()
