"""
Tek giriş noktalı CLI.

FINDING #4 — v1'de ~8 ayrı script'in her birinin kendi argparse'ı vardı. Burada
tek `tefas` komutu ve alt-komutlar: `run` (tüm pipeline), ayrıca her aşama
bağımsız çalıştırılabilir (`etl`, `metrics`, `score`, `report`) — önceki aşamanın
parquet önbelleğini okuyarak.

    tefas run --fund-type YAT --risk-free-rate 45
    tefas metrics --fund-type YAT --risk-free-rate 45   # ETL önbelleğinden
    python -m tefas run ...
"""
from __future__ import annotations

import argparse

from . import config, etl, holdings, metrics, scoring, report, pipeline
from .io_utils import setup_utf8


def _common(p):
    # default=None: config dosyası override edebilsin; etkin değer main()'de belirlenir.
    p.add_argument("--fund-type", default=None, choices=["YAT", "EMK"])
    p.add_argument("--risk-free-rate", type=float, default=None)


def _parse_filter_file(text):
    """`[INCLUDE]`/`[EXCLUDE]` bölümlü düz-metin filtre dosyasını ayrıştır.

    Her satıra bir kelime; boş satırlar ve `#` ile başlayanlar yok sayılır.
    Boş bölüm None döner (yani filtre uygulanmaz / override etmez).
    """
    include, exclude = [], []
    section = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        up = s.upper()
        if up == "[INCLUDE]":
            section = "inc"
            continue
        if up == "[EXCLUDE]":
            section = "exc"
            continue
        if s.startswith("[") and s.endswith("]"):
            section = None
            continue
        if section == "inc":
            include.append(s)
        elif section == "exc":
            exclude.append(s)
    return {"include": include or None, "exclude": exclude or None}


def _parse_comparison_file(text):
    """Karşılaştırma dosyasından fon kodlarını ayrıştır.

    Satır başına bir kod; boş satırlar, `#` yorumları ve `[...]` bölüm başlıkları
    (örn. `[COMPARE]`) yok sayılır. Kodlar büyük harfe çevrilir; sıra korunur,
    yinelenenler atlanır.
    """
    codes, seen = [], set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or (s.startswith("[") and s.endswith("]")):
            continue
        code = s.split()[0].upper()   # olası açıklamaları at, ilk token = kod
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _load_config(path):
    """Çalıştırma ayarlarını dosyadan oku.

    Uzantıya göre: `.json` / `.toml` tam ayar dosyası; `.txt` ise yalnızca
    include/exclude içeren filtre dosyası ([INCLUDE]/[EXCLUDE] bölümleri).
    Desteklenen anahtarlar: fund_type, risk_free_rate, include, exclude,
    active_only, keep_suspect, min_aum, min_fund_age, write_report.
    """
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[HATA] Config dosyası bulunamadı: {p}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix == ".txt":
        return _parse_filter_file(text)
    if suffix == ".toml":
        import tomllib
        return tomllib.loads(text)
    import json
    return json.loads(text)


def _save_config(path, settings):
    """Etkin çalıştırma ayarlarını JSON dosyasına yaz."""
    import json
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Ayarlar kaydedildi: {p}")


def _ask_choice(prompt, choices, default):
    """choices: [(value, label), ...]; default: value. Boş giriş -> default."""
    print(f"\n{prompt}")
    for i, (val, label) in enumerate(choices, 1):
        mark = " (varsayılan)" if val == default else ""
        print(f"  {i}) {label}{mark}")
    while True:
        raw = input(f"Seçim [1-{len(choices)}] (Enter={default}): ").strip()
        if not raw:
            return default
        # hem numara hem değer kabul et
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][0]
        for val, _ in choices:
            if raw.upper() == val.upper():
                return val
        print("  Geçersiz seçim, tekrar deneyin.")


def _ask_float(prompt, default):
    while True:
        raw = input(f"{prompt} (Enter={default}): ").strip()
        if not raw:
            return default
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            print("  Sayı girin, örn. 45 veya 45.5")


def _ask_yes_no(prompt, default=True):
    d = "E/h" if default else "e/H"
    while True:
        raw = input(f"{prompt} [{d}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("e", "evet", "y", "yes"):
            return True
        if raw in ("h", "hayir", "hayır", "n", "no"):
            return False
        print("  e/h girin.")


def _interactive() -> int:
    """Argümansız çalıştırıldığında soru-cevap sihirbazı."""
    print("=" * 60)
    print("  TEFAS Fon Analiz Sistemi — interaktif mod")
    print("=" * 60)

    source = _ask_choice(
        "Ayarlar nereden gelsin?",
        [
            ("manual", "Adım adım soru-cevap"),
            ("config", "Config dosyasından yükle (JSON/TOML, run)"),
        ],
        default="manual",
    )
    if source == "config":
        default_cfg = str(config.DEFAULT_CONFIG_PATH)
        path = input(f"\nConfig dosyası yolu (Enter={config.DEFAULT_CONFIG_PATH.name}): ").strip().strip('"') or default_cfg
        print(f"\n>>> Çalıştırılıyor: tefas run --config {path}\n")
        return main(["run", "--config", path])

    cmd = _ask_choice(
        "Hangi işlemi çalıştıralım?",
        [
            ("run", "Tüm pipeline (ETL -> metrik -> skor -> rapor)"),
            ("compare", "Fon karşılaştırma (belirli kodları yan yana)"),
            ("holdings", "Portföyüm (pozisyonlar + XIRR/TWR getiri)"),
            ("dashboard", "İnteraktif web paneli (tarayıcıda açılır)"),
            ("etl", "Yalnızca ETL (combined parquet)"),
            ("metrics", "Yalnızca metrik hesabı"),
            ("score", "Yalnızca skorlama"),
            ("report", "Yalnızca PDF rapor"),
        ],
        default="run",
    )

    if cmd == "dashboard":
        print("\n>>> Çalıştırılıyor: tefas dashboard\n")
        return main(["dashboard"])

    fund_type = _ask_choice(
        "Hangi fon tipi?",
        [("YAT", "Yatırım fonları (YAT)"), ("EMK", "Emeklilik fonları (EMK)")],
        default="YAT",
    )

    if cmd == "holdings":
        action = _ask_choice(
            "Ne gösterelim?",
            [("show", "Pozisyonlar ve kar/zarar"), ("returns", "Getiri (XIRR + TWR)"),
             ("check", "Denge kontrolü (model sapması + sinyaller)")],
            default="show",
        )
        argv = ["holdings", action, "--fund-type", fund_type]
        print("\n>>> Çalıştırılıyor: tefas " + " ".join(argv) + "\n")
        return main(argv)

    argv = [cmd, "--fund-type", fund_type]

    if cmd != "etl":
        rfr = _ask_float("Risksiz faiz oranı (%)", config.macro().risk_free_rate)
        argv += ["--risk-free-rate", str(rfr)]

    if cmd == "compare":
        csrc = _ask_choice(
            "Karşılaştırılacak fon kodları nereden gelsin?",
            [("file", f"Dosyadan yükle ({config.DEFAULT_COMPARISON_PATH.name})"),
             ("manual", "Elle gir (virgülle)")],
            default="file",
        )
        if csrc == "file":
            path = input(f"Karşılaştırma dosyası yolu (Enter={config.DEFAULT_COMPARISON_PATH.name}): ").strip().strip('"') \
                or str(config.DEFAULT_COMPARISON_PATH)
            argv += ["--config", path]
        else:
            raw = input("Fon kodları (virgülle, örn. PRY,PBR,BMU): ").strip()
            if raw:
                argv += ["--codes", raw]
        print("\n>>> Çalıştırılıyor: tefas " + " ".join(argv) + "\n")
        return main(argv)

    if cmd in ("run", "etl"):
        if not _ask_yes_no("Yalnızca aktif fonlar (platform_status filtresi)?", default=True):
            argv.append("--no-active-only")

    if cmd in ("run", "metrics"):
        if _ask_yes_no("Veri-kalitesi şüpheli fonları tut?", default=False):
            argv.append("--keep-suspect")

    if cmd == "run":
        fsrc = _ask_choice(
            "Filtreler (include/exclude) nasıl belirlensin?",
            [
                ("file", f"Dosyadan yükle ({config.DEFAULT_FILTER_PATH.name})"),
                ("manual", "Elle gir"),
                ("none", "Filtre yok"),
            ],
            default="file",
        )
        if fsrc == "file":
            path = input(f"Filtre dosyası yolu (Enter={config.DEFAULT_FILTER_PATH.name}): ").strip().strip('"') \
                or str(config.DEFAULT_FILTER_PATH)
            argv += ["--config", path]
        elif fsrc == "manual":
            inc = input("Include (dahil edilecek) kelimeler — boşlukla ayır (Enter=yok): ").strip()
            if inc:
                argv += ["--filter"] + inc.split()
            exc = input("Exclude (hariç tutulacak) kelimeler — boşlukla ayır (Enter=yok): ").strip()
            if exc:
                argv += ["--exclude"] + exc.split()
        if not _ask_yes_no("PDF rapor üretilsin mi?", default=True):
            argv.append("--no-report")
        if _ask_yes_no("Bu ayarları config dosyasına kaydedeyim mi?", default=False):
            path = input(f"Kayıt yolu (Enter={config.DEFAULT_CONFIG_PATH.name}): ").strip().strip('"')
            argv += ["--save-config", path] if path else ["--save-config"]

    print("\n>>> Çalıştırılıyor: tefas " + " ".join(argv) + "\n")
    return main(argv)


def _fmt_tl(v) -> str:
    """1234567.89 -> '1.234.568 TL' (Türkçe binlik ayraç, tam sayıya yuvarlı)."""
    try:
        return f"{float(v):,.0f}".replace(",", ".") + " TL"
    except (TypeError, ValueError):
        return "—"


def _run_holdings(args) -> int:
    """`tefas holdings show|returns` — kişisel portföy pozisyonları ve getirisi."""
    from pathlib import Path
    fund_type = (args.fund_type or "YAT").upper()
    paths = config.paths_for(fund_type)
    txn_path = Path(args.file) if args.file else config.DEFAULT_TRANSACTIONS_PATH

    try:
        txns = holdings.load_transactions(txn_path)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(f"[HATA] {e}")
    combined = pipeline._read_parquet(paths.combined_parquet)
    as_of = combined["Tarih"].max()

    pos = holdings.positions(txns)
    val = holdings.valuation(pos, combined)
    open_pos = val[val["Adet"] > 0]
    total_value = float(open_pos["Deger"].sum())
    total_cost = float(open_pos["Maliyet"].sum())
    realized = float(val["Realize_KZ"].sum())

    print(f"\n{'='*64}\nPORTFÖYÜM — {paths.fund_name} | veri sonu: {as_of.date()} "
          f"| {len(txns)} işlem\n{'='*64}")

    if args.action == "show":
        if open_pos.empty:
            print("[INFO] Açık pozisyon yok.")
        else:
            cols = ["Fon Kodu", "Adet", "Ortalama_Maliyet", "Son_Fiyat", "Son_Tarih",
                    "Deger", "Deger_KZ", "Getiri_Pct", "Agirlik", "Realize_KZ"]
            show = open_pos[cols].copy()
            show["Son_Tarih"] = show["Son_Tarih"].dt.date
            show["Agirlik"] = (show["Agirlik"] * 100).round(1)
            print(show.to_string(index=False))
            stale = open_pos[open_pos["Veri_Bayat"]]
            if not stale.empty:
                print(f"\n[WARN] Bayat/eksik NAV (> {holdings.STALE_NAV_DAYS} gün): "
                      f"{', '.join(stale['Fon Kodu'])} — değerleri güncel olmayabilir.")
        closed = val[(val["Adet"] <= 0) & (val["Realize_KZ"] != 0)]
        if not closed.empty:
            print(f"\nKapanmış pozisyonlar (realize K/Z): "
                  + ", ".join(f"{r['Fon Kodu']} {_fmt_tl(r['Realize_KZ'])}"
                              for _, r in closed.iterrows()))
        print(f"\nToplam değer : {_fmt_tl(total_value)}   (maliyet {_fmt_tl(total_cost)})")
        print(f"Açık K/Z     : {_fmt_tl(total_value - total_cost)}   "
              f"Realize K/Z: {_fmt_tl(realized)}")
        return 0

    if args.action == "returns":
        flows = holdings.xirr_cashflows(txns, total_value, as_of)
        mwr = holdings.xirr(flows)
        t = holdings.twr(txns, combined)
        print(f"Toplam değer          : {_fmt_tl(total_value)}")
        print(f"XIRR (para-ağırlıklı) : " + (f"%{mwr*100:.1f} / yıl" if mwr == mwr else "hesaplanamadı"))
        if t["twr"] == t["twr"]:
            ann = f" (yıllık %{t['twr_yillik']*100:.1f})" if t["twr_yillik"] == t["twr_yillik"] else ""
            print(f"TWR (zaman-ağırlıklı) : %{t['twr']*100:.1f} / {t['gun']} gün{ann}")
        else:
            print("TWR (zaman-ağırlıklı) : hesaplanamadı (yetersiz seri)")
        print("\nNot: XIRR 'benim param ne kazandı' sorusunun; TWR fon/benchmark "
              "kıyasının doğru ölçüsüdür.")
        return 0

    # check — model sapması, risk özeti, rebalans önerileri, sinyaller
    import pandas as pd
    from . import allocation, portfolio as pf_mod
    scored = pipeline._read_parquet(paths.scored_parquet)
    elig = scored[scored["Uygun"]].copy() if "Uygun" in scored.columns else scored.copy()
    if elig.empty:
        elig = scored.copy()
    model = allocation.build_portfolio(elig)
    if open_pos.empty or total_value <= 0:
        raise SystemExit("[HATA] Açık pozisyon yok — kontrol edilecek portföy bulunamadı.")
    current_weights = {str(r["Fon Kodu"]): float(r["Agirlik"]) * 100
                       for _, r in open_pos.iterrows()}

    # Gerçek portföyün kovaryans-temelli risk özeti
    port = [{"Fon Kodu": c, "Agirlik": w} for c, w in current_weights.items()]
    risk = pf_mod.portfolio_risk(combined, port)
    if risk is not None:
        print(f"Portföy volatilitesi (kovaryans) : %{risk['portfolio_vol']:.1f}")
        print(f"Çeşitlendirme kazancı            : %{risk['diversification_gain']:.1f} "
              f"(ort. korelasyon {risk['avg_correlation']:.2f}, {risk['n_used']} fon)")
        rc = risk.get("risk_contributions") or {}
        if rc:
            print("Risk katkıları                   : "
                  + ", ".join(f"{c} %{v*100:.0f}" for c, v in
                              sorted(rc.items(), key=lambda kv: -kv[1])))
    else:
        print("[WARN] Kovaryans hesaplanamadı (yetersiz ortak veri).")

    # Model sapması + rebalans önerileri
    suggestions = allocation.rebalance(current_weights, model, total_value)
    print(f"\nModel portföy ({len(model)} fon): "
          + ", ".join(f"{p['Fon Kodu']} %{p['Agirlik']:.0f}" for p in model))
    if not suggestions:
        print("[OK] Portföy model dağılıma yeterince yakın — işlem önerisi yok "
              "(eşik: 5 puan sapma).")
    else:
        print("\nÖnerilen işlemler (model dağılıma dönüş, kendi kendini finanse eder):")
        for s in suggestions:
            print(f"  {s['Islem']:<3} {s['Fon Kodu']:<5} "
                  f"%{s['Mevcut_Pct']:.1f} → %{s['Hedef_Pct']:.1f} "
                  f"({s['Fark_Puan']:+.1f} puan) ≈ {_fmt_tl(abs(s['Tutar_TL']))}")

    # Sinyaller (skor geçmişinden)
    history = pd.read_parquet(paths.score_history_parquet) \
        if paths.score_history_parquet.exists() else None
    sigs = holdings.signals(list(current_weights), scored, history)
    if sigs:
        print("\nSinyaller:")
        for s in sigs:
            print(f"  [{s['Tip']}] {s['Fon Kodu']}: {s['Mesaj']}")
    else:
        print("\nSinyal yok — pozisyonlar skor tablosunda ve trend stabil.")
    print("\nNot: Model portföy kantitatif bir örnektir, yatırım tavsiyesi değildir.")
    return 0


def _run_dashboard(args) -> int:
    """`tefas dashboard` — Streamlit panelini başlatır (opsiyonel bağımlılık)."""
    import importlib.util
    import subprocess
    import sys
    from pathlib import Path
    if importlib.util.find_spec("streamlit") is None:
        raise SystemExit("[HATA] streamlit kurulu değil. Kurulum:\n"
                         "       pip install -e .[dashboard]")
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path),
           "--server.port", str(args.port), "--server.headless", "false"]
    print(f"[INFO] Dashboard başlatılıyor: http://localhost:{args.port} (durdurmak için Ctrl+C)")
    return subprocess.run(cmd).returncode


def _run_compare(args) -> int:
    """`tefas compare` — belirli fon kodlarını karşılaştıran PDF üretir."""
    from pathlib import Path
    fund_type = (args.fund_type or "YAT").upper()
    rfr = args.risk_free_rate if args.risk_free_rate is not None else config.macro().risk_free_rate

    if args.codes:
        codes = _parse_comparison_file(args.codes.replace(",", "\n"))
    else:
        cfg_path = Path(args.config) if args.config else config.DEFAULT_COMPARISON_PATH
        if not cfg_path.exists():
            raise SystemExit(
                f"[HATA] Karşılaştırma dosyası bulunamadı: {cfg_path}\n"
                f"        Kodları --codes PRY,PBR,BMU ile de verebilirsin.")
        codes = _parse_comparison_file(cfg_path.read_text(encoding="utf-8"))

    if len(codes) < 2:
        raise SystemExit(f"[HATA] Karşılaştırma için en az 2 fon kodu gerekir (bulunan: {codes or 'yok'}).")

    return pipeline.run_comparison(fund_type, rfr, codes)


def main(argv=None) -> int:
    setup_utf8()
    # Hiç argüman verilmeden çalıştırıldıysa interaktif sihirbaza geç.
    import sys
    if argv is None and len(sys.argv) <= 1:
        return _interactive()
    parser = argparse.ArgumentParser(prog="tefas", description="TEFAS fon analiz sistemi (v2)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Tüm pipeline'ı çalıştır (ETL -> metrik -> skor -> rapor)")
    _common(pr)
    pr.add_argument("--config", nargs="?", default=None, const=str(config.DEFAULT_CONFIG_PATH),
                    help=f"Ayarları JSON/TOML dosyasından yükle (CLI argümanları config'i ezer). "
                         f"Değer verilmezse varsayılan: {config.DEFAULT_CONFIG_PATH.name}")
    pr.add_argument("--save-config", nargs="?", default=None, const=str(config.DEFAULT_CONFIG_PATH),
                    metavar="PATH",
                    help=f"Etkin ayarları dosyaya kaydet (değer verilmezse: {config.DEFAULT_CONFIG_PATH.name})")
    pr.add_argument("--filter", nargs="+", default=None, help="Dahil edilecek fon anahtar kelimeleri")
    pr.add_argument("--exclude", nargs="+", default=None, help="Hariç tutulacak fon anahtar kelimeleri")
    pr.add_argument("--no-active-only", action="store_true", help="platform_status aktiflik filtresini kapat")
    pr.add_argument("--keep-suspect", action="store_true", help="Veri-kalitesi şüpheli fonları tut")
    pr.add_argument("--min-aum", type=float, default=None)
    pr.add_argument("--min-fund-age", type=float, default=None)
    pr.add_argument("--no-report", action="store_true", help="PDF üretme (yalnızca CSV/parquet)")

    pe = sub.add_parser("etl", help="Yalnızca ETL — combined parquet üret")
    pe.add_argument("--fund-type", default="YAT", choices=["YAT", "EMK"])
    pe.add_argument("--no-active-only", action="store_true")

    pm = sub.add_parser("metrics", help="Metrikleri hesapla (combined parquet'ten)")
    _common(pm)
    pm.add_argument("--keep-suspect", action="store_true")

    ps = sub.add_parser("score", help="Skorla (metrik + combined parquet'ten)")
    _common(ps)

    prep = sub.add_parser("report", help="PDF rapor üret (skorlu + metrik parquet'ten)")
    _common(prep)

    pb = sub.add_parser("backtest", help="Walk-forward doğrulama: skorlar ileriye dönük sinyal taşıyor mu?")
    _common(pb)
    pb.add_argument("--horizons", nargs="+", type=int, default=[1, 3], metavar="AY",
                    help="İleri getiri ufukları (ay), örn. --horizons 1 3")
    pb.add_argument("--step-months", type=int, default=1, help="Katlar arası adım (ay)")
    pb.add_argument("--min-history-days", type=int, default=140,
                    help="İlk kat için gereken asgari geçmiş (takvim günü)")
    pb.add_argument("--no-active-only", action="store_true")

    ph = sub.add_parser("holdings", help="Kişisel portföy: pozisyonlar ve getiri (işlem defterinden)")
    ph.add_argument("action", choices=["show", "returns", "check"],
                    help="show: pozisyon/K-Z tablosu; returns: XIRR + TWR; "
                         "check: model sapması + rebalans önerisi + sinyaller")
    ph.add_argument("--fund-type", default=None, choices=["YAT", "EMK"])
    ph.add_argument("--file", default=None, metavar="PATH",
                    help=f"İşlem defteri CSV (varsayılan: {config.DEFAULT_TRANSACTIONS_PATH.name})")

    pd_ = sub.add_parser("dashboard", help="İnteraktif web paneli (Streamlit; pip install -e .[dashboard])")
    pd_.add_argument("--port", type=int, default=8501)

    pc = sub.add_parser("compare", help="Belirli fonları karşılaştır (tablo + grafik PDF)")
    _common(pc)
    pc.add_argument("--codes", default=None,
                    help="Karşılaştırılacak fon kodları, virgülle: PRY,PBR,BMU (dosyayı ezer)")
    pc.add_argument("--config", nargs="?", default=None, const=str(config.DEFAULT_COMPARISON_PATH),
                    metavar="PATH",
                    help=f"Kod listesi dosyası (varsayılan: {config.DEFAULT_COMPARISON_PATH.name})")

    args = parser.parse_args(argv)

    if args.cmd == "compare":
        return _run_compare(args)
    if args.cmd == "holdings":
        return _run_holdings(args)
    if args.cmd == "dashboard":
        return _run_dashboard(args)

    # Config dosyası (yalnızca run destekler); CLI argümanları config'i ezer.
    cfg = _load_config(args.config) if getattr(args, "config", None) else {}

    fund_type = (args.fund_type or cfg.get("fund_type") or "YAT").upper()
    # getattr: `etl` alt-komutu rf argümanı taşımaz (ETL rf kullanmaz)
    rfr_arg = getattr(args, "risk_free_rate", None)
    rfr = rfr_arg if rfr_arg is not None else cfg.get("risk_free_rate", config.macro().risk_free_rate)
    paths = config.paths_for(fund_type)

    if args.cmd == "run":
        include = args.filter if args.filter is not None else cfg.get("include")
        exclude = args.exclude if args.exclude is not None else cfg.get("exclude")
        active_only = False if args.no_active_only else cfg.get("active_only", True)
        keep_suspect = True if args.keep_suspect else cfg.get("keep_suspect", False)
        write_report = False if args.no_report else cfg.get("write_report", True)
        min_aum = args.min_aum if args.min_aum is not None else cfg.get("min_aum")
        min_fund_age = args.min_fund_age if args.min_fund_age is not None else cfg.get("min_fund_age")
        if args.save_config:
            _save_config(args.save_config, {
                "fund_type": fund_type, "risk_free_rate": rfr,
                "include": include, "exclude": exclude,
                "active_only": active_only, "keep_suspect": keep_suspect,
                "min_aum": min_aum, "min_fund_age": min_fund_age,
                "write_report": write_report,
            })
        pipeline.run(fund_type, rfr, include=include, exclude=exclude,
                     active_only=active_only, keep_suspect=keep_suspect,
                     min_aum=min_aum, min_fund_age=min_fund_age, write_report=write_report)
        return 0

    if args.cmd == "etl":
        df = etl.load_combined(fund_type, active_only=not args.no_active_only)
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(paths.combined_parquet, index=False)
        print(f"[OK] {paths.combined_parquet}")
        return 0

    if args.cmd == "metrics":
        combined = pipeline._read_parquet(paths.combined_parquet)
        met = metrics.compute_metrics(combined, rfr, keep_suspect=args.keep_suspect)
        met.to_parquet(paths.metrics_parquet, index=False)
        met.to_csv(paths.metrics_csv, index=False, encoding=config.OUTPUT_ENCODING)
        print(f"[OK] {paths.metrics_csv}")
        return 0

    if args.cmd == "score":
        combined = pipeline._read_parquet(paths.combined_parquet)
        met = pipeline._read_parquet(paths.metrics_parquet)
        scored = scoring.score_funds(met, combined, rfr)
        scored.to_parquet(paths.scored_parquet, index=False)
        scored.to_csv(paths.scored_csv, index=False, encoding=config.OUTPUT_ENCODING)
        print(f"[OK] {paths.scored_csv}")
        return 0

    if args.cmd == "report":
        met = pipeline._read_parquet(paths.metrics_parquet)
        scored = pipeline._read_parquet(paths.scored_parquet)
        combined = pipeline._read_parquet(paths.combined_parquet)
        report.generate(scored, met, fund_type, rfr, combined=combined)
        return 0

    if args.cmd == "backtest":
        from . import backtest as bt
        # Önce ETL önbelleği; yoksa taze yükle.
        if paths.combined_parquet.exists() and not args.no_active_only:
            combined = pipeline._read_parquet(paths.combined_parquet)
            print(f"[INFO] ETL önbelleği kullanılıyor: {paths.combined_parquet.name}")
        else:
            combined = etl.load_combined(fund_type, active_only=not args.no_active_only)
        result = bt.run_backtest(combined, rfr, horizons=tuple(args.horizons),
                                 min_history_days=args.min_history_days,
                                 step_months=args.step_months)
        if result is None:
            return 1
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result.folds.to_csv(paths.backtest_csv, index=False, encoding=config.OUTPUT_ENCODING)
        print(f"\n[OK] Kat detayı: {paths.backtest_csv}")
        bt.print_summary(result, rfr)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
