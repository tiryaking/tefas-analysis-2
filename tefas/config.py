"""
Merkezi konfigürasyon.

v1'de her script kendi yollarını/sabitlerini ve argparse'ını taşıyordu; burada
hepsi tek yerde. Yollar paket köküne göre çözülür ve fon tipine göre çıktı
dosyaları `paths_for()` ile üretilir. Ara çıktılar **parquet** (tipli, küçük,
hızlı); insan-dostu özetler ayrıca CSV olarak da yazılır.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# ─── Yollar ───────────────────────────────────────────────────────────────────
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DATASET_DIR = PROJECT_ROOT / "Dataset"
OUTPUT_DIR = PROJECT_ROOT / "Output"
REPORTS_DIR = PROJECT_ROOT / "Reports"

FUND_TYPE_MAP = {"YAT": "Yatirim", "EMK": "Emeklilik"}

# Varsayılan çalıştırma-ayarı dosyası (proje kökünde). İnteraktif sihirbaz ve
# `--config` / `--save-config` Enter'a basıldığında bu yolu kullanır.
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "tefas.config.json"

# Varsayılan filtre dosyası ([INCLUDE]/[EXCLUDE] bölümlü düz metin). Sihirbaz
# filtreleri bu dosyadan yükleyebilir; `--config filter_config.txt` ile de okunur.
DEFAULT_FILTER_PATH = PROJECT_ROOT / "filter_config.txt"

# Karşılaştırma modu: karşılaştırılacak fon kodlarının listelendiği düz-metin
# dosyası (satır başına bir kod; `#` yorum). `tefas compare` bunu okur.
DEFAULT_COMPARISON_PATH = PROJECT_ROOT / "comparison_config.txt"

# ─── Analiz parametreleri ─────────────────────────────────────────────────────
MIN_DATA_POINTS = 20
TRADING_DAYS_PER_YEAR = 252

# Skorlamada kullanılan risk metrikleri (volatilite, Sharpe, Sortino, Calmar,
# drawdown, VaR) tüm fonlarda **ortak, gerilemeli (trailing) pencerede**
# hesaplanır ki farklı geçmiş uzunluğundaki fonlar aynı dönem üzerinden
# kıyaslanabilsin. Varsayılan ~1 işlem yılı (252 gözlem). Bundan uzun geçmişli
# fonlar son bu kadar gözleme kırpılır; daha kısa geçmişliler tüm geçmişini
# kullanır ve tablolarda `*` ile işaretlenir.
SCORING_LOOKBACK_DAYS = 252

# Kısa geçmişli fonların yıllıklandırılmış getirisi gürültülüdür; skorlamada
# getiri, `Skor_Penceresi_Gun / RETURN_FULL_CREDIBILITY_DAYS` güvenilirlik
# ağırlığıyla akran (tema) medyanına doğru çekilir (bkz. scoring.shrunk_annual_return).
RETURN_FULL_CREDIBILITY_DAYS = 189   # ~%75 × 252: tam güvenilirlik eşiği

# Tema-içi akran kıyası (medyan/yüzdelik) için temada bulunması gereken
# asgari fon sayısı; altındaki temalar akran istatistiği üretmez.
THEME_MIN_FUNDS = 5

# ─── Veri kalitesi ────────────────────────────────────────────────────────────
DATA_QUALITY_MAX_DAILY_MOVE = 35.0   # tek-günlük mutlak hareket sınırı (%)
DAILY_RETURN_CLIP = 25.0             # volatilite/Sortino için winsorize bandı (%)

# ─── Ücret / makro ────────────────────────────────────────────────────────────
# NOT: Eski `net_return` stopaj sezgiseli (yıllıklandırılmış CAGR üzerinden
# enflasyon+5 eşiği aşımına %15) hem Türk fon vergilendirmesini yanlış modelliyor
# hem de bir *orana* vergi uygulayarak boyutsal olarak hatalıydı; kaldırıldı.
# `Net_Getiri_1Y` artık yalnızca yönetim ücreti düşülmüş getiridir; işlem
# vergileri modellenmez (reel getiri için `Reel_Getiri_1Y` kullanılır).
#
# Makro oranlar artık modül sabiti DEĞİL: `tefas.config.json`'daki düz
# anahtarlardan okunur (`macro()`); dosya/anahtar yoksa DEFAULT_MACRO devreye
# girer ve hangi anahtarların varsayılan kaldığı `defaults_used`'da izlenir
# (raporda "(varsayılan)" işareti için).
REAL_RETURN_ENABLED = True

DEFAULT_MACRO = {
    "risk_free_rate": 45.0,
    "inflation_rate": 55.0,
    "policy_rate": 50.0,
    "management_fee_rate": 1.0,
}


@dataclass(frozen=True)
class MacroRates:
    """Çalıştırma-zamanı makro oranları (yüzde) + varsayılana düşen anahtarlar."""
    risk_free_rate: float
    inflation_rate: float
    policy_rate: float
    management_fee_rate: float
    defaults_used: frozenset


def load_macro(path: Path | None = None) -> MacroRates:
    """`tefas.config.json`'dan makro oranları oku; asla exception fırlatmaz.

    Eksik dosya / bozuk JSON / eksik veya sayı-olmayan anahtar → DEFAULT_MACRO
    değeri kullanılır ve anahtar `defaults_used`'a eklenir.
    """
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:  # noqa: BLE001 — pipeline config yüzünden asla çökmesin
        raw = {}
    values, defaulted = {}, set()
    for key, fallback in DEFAULT_MACRO.items():
        v = raw.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values[key] = float(v)
        else:
            values[key] = fallback
            defaulted.add(key)
    return MacroRates(defaults_used=frozenset(defaulted), **values)


_MACRO: MacroRates | None = None


def macro() -> MacroRates:
    """Varsayılan config dosyasından okunan, önbelleklenmiş makro oranlar."""
    global _MACRO
    if _MACRO is None:
        _MACRO = load_macro()
    return _MACRO


def reset_macro_cache() -> None:
    """Test izolasyonu için önbelleği sıfırlar."""
    global _MACRO
    _MACRO = None

# ─── AUM / yaş ────────────────────────────────────────────────────────────────
AUM_BONUS_THRESHOLD = 50
MIN_FUND_AGE_YEARS = None

# ─── Rapor / PDF ──────────────────────────────────────────────────────────────
CONSOLIDATED_REPORT_BASENAME = "tefas_premium_rapor"
COMPARISON_REPORT_BASENAME = "tefas_karsilastirma"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\ARIALUNI.TTF",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BOLD_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# ─── Encoding ─────────────────────────────────────────────────────────────────
CSV_READ_ENCODINGS = ["utf-8-sig", "utf-8", "cp1254", "iso-8859-9"]
OUTPUT_ENCODING = "utf-8-sig"


@dataclass(frozen=True)
class Paths:
    """Bir fon tipi için tüm girdi/çıktı yolları."""
    fund_type: str          # "YAT" | "EMK"
    fund_name: str          # "Yatirim" | "Emeklilik"
    suffix: str             # "yatirim" | "emeklilik"
    dataset_dir: Path
    platform_status: Path
    combined_parquet: Path
    metrics_parquet: Path
    metrics_csv: Path
    scored_parquet: Path
    scored_csv: Path
    backtest_csv: Path
    report_pdf: Path
    comparison_pdf: Path


def paths_for(fund_type: str) -> Paths:
    ft = (fund_type or "YAT").upper()
    name = FUND_TYPE_MAP.get(ft, "Yatirim")
    suffix = name.lower()
    return Paths(
        fund_type=ft,
        fund_name=name,
        suffix=suffix,
        dataset_dir=DATASET_DIR / name,
        platform_status=DATASET_DIR / "platform_status" / f"platform_status_{suffix}.json",
        combined_parquet=OUTPUT_DIR / f"combined_tefas_data_{suffix}.parquet",
        metrics_parquet=OUTPUT_DIR / f"tefas_financial_metrics_{suffix}.parquet",
        metrics_csv=OUTPUT_DIR / f"tefas_financial_metrics_{suffix}.csv",
        scored_parquet=OUTPUT_DIR / f"advanced_portfolio_recommendations_{suffix}.parquet",
        scored_csv=OUTPUT_DIR / f"advanced_portfolio_recommendations_{suffix}.csv",
        backtest_csv=OUTPUT_DIR / f"backtest_walkforward_{suffix}.csv",
        report_pdf=REPORTS_DIR / f"{CONSOLIDATED_REPORT_BASENAME}_{suffix}.pdf",
        comparison_pdf=REPORTS_DIR / f"{COMPARISON_REPORT_BASENAME}_{suffix}.pdf",
    )
