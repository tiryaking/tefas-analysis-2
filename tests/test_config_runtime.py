"""`config.load_macro` / `config.macro` — makro oranların JSON'dan okunması.

Kritik sözleşme: loader ASLA exception fırlatmaz (bozuk/eksik config pipeline'ı
çökertmemeli); varsayılana düşen anahtarlar `defaults_used`'da raporlanır
(PDF kapağındaki "(varsayılan)" işareti buradan beslenir).
"""
import json

from tefas import config


def test_missing_file_all_defaults(tmp_path):
    mac = config.load_macro(tmp_path / "yok.json")
    assert mac.risk_free_rate == config.DEFAULT_MACRO["risk_free_rate"]
    assert mac.inflation_rate == config.DEFAULT_MACRO["inflation_rate"]
    assert mac.policy_rate == config.DEFAULT_MACRO["policy_rate"]
    assert mac.management_fee_rate == config.DEFAULT_MACRO["management_fee_rate"]
    assert mac.defaults_used == frozenset(config.DEFAULT_MACRO)


def test_overrides_picked_up(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"inflation_rate": 40, "risk_free_rate": 38.5}), encoding="utf-8")
    mac = config.load_macro(p)
    assert mac.inflation_rate == 40.0
    assert mac.risk_free_rate == 38.5
    assert "inflation_rate" not in mac.defaults_used
    assert "risk_free_rate" not in mac.defaults_used
    assert {"policy_rate", "management_fee_rate"} <= set(mac.defaults_used)


def test_corrupt_json_no_exception(tmp_path):
    p = tmp_path / "bozuk.json"
    p.write_text("{ bu json değil", encoding="utf-8")
    mac = config.load_macro(p)   # fırlatmamalı
    assert mac.defaults_used == frozenset(config.DEFAULT_MACRO)


def test_non_numeric_values_fall_back(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"inflation_rate": "elli", "policy_rate": True}), encoding="utf-8")
    mac = config.load_macro(p)
    assert mac.inflation_rate == config.DEFAULT_MACRO["inflation_rate"]
    assert mac.policy_rate == config.DEFAULT_MACRO["policy_rate"]  # bool sayı değildir
    assert {"inflation_rate", "policy_rate"} <= set(mac.defaults_used)


def test_macro_cache_reset():
    config.reset_macro_cache()
    first = config.macro()
    assert config.macro() is first          # önbellekli
    config.reset_macro_cache()
    assert config.macro() is not first      # sıfırlama yeni nesne üretir
