"""
Merkezi konfigürasyon.

v1'de her script kendi yollarını/sabitlerini ve argparse'ını taşıyordu; burada
hepsi tek yerde. Yollar paket köküne göre çözülür ve fon tipine göre çıktı
dosyaları `paths_for()` ile üretilir. Ara çıktılar **parquet** (tipli, küçük,
hızlı); insan-dostu özetler ayrıca CSV olarak da yazılır.
"""
from __future__ import annotations

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

# ─── Analiz parametreleri ─────────────────────────────────────────────────────
MIN_DATA_POINTS = 20
TRADING_DAYS_PER_YEAR = 252

# ─── Veri kalitesi ────────────────────────────────────────────────────────────
DATA_QUALITY_MAX_DAILY_MOVE = 35.0   # tek-günlük mutlak hareket sınırı (%)
DAILY_RETURN_CLIP = 25.0             # volatilite/Sortino için winsorize bandı (%)

# ─── Beta / Treynor ───────────────────────────────────────────────────────────
MIN_BETA_FOR_TREYNOR = 0.15
TREYNOR_CAP = 200.0

# ─── Ücret / stopaj / makro ───────────────────────────────────────────────────
MANAGEMENT_FEE_RATE = 1.0
TUFE_RATE = 55.0
TUFE_PLUS_THRESHOLD = 5.0
STOPAJ_RATE = 0.15
INFLATION_RATE = 55.0
POLICY_RATE = 50.0
REAL_RETURN_ENABLED = True

# ─── AUM / yaş ────────────────────────────────────────────────────────────────
AUM_BONUS_THRESHOLD = 50
MIN_FUND_AGE_YEARS = None

# ─── Benchmark ────────────────────────────────────────────────────────────────
# None => eşit-ağırlıklı fon evreni benchmark olarak kullanılır.
BENCHMARK_CODE = "XU100"

# ─── Rapor / PDF ──────────────────────────────────────────────────────────────
CONSOLIDATED_REPORT_BASENAME = "tefas_premium_rapor"
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
    report_pdf: Path


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
        report_pdf=REPORTS_DIR / f"{CONSOLIDATED_REPORT_BASENAME}_{suffix}.pdf",
    )
