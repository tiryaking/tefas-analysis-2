"""tefas_web modülü için birim testleri."""
import pytest
from tefas import tefas_web


# Yeni Next.js Tailwind tabanlı HTML yapısı
SAMPLE_HTML = """
<html><body>
<p class="text-xs text-primary-muted">ISIN Kodu</p>
<p class="text-xs font-bold text-content-primary">TRYFNG00001</p>
<p class="text-xs text-primary-muted">Platform Durumu</p>
<p class="text-xs font-bold text-content-primary">TEFAS&#x27;ta işlem görüyor</p>
<p class="text-xs text-primary-muted">Fon Risk Değeri</p>
<p class="text-xs font-bold text-content-primary">5</p>
<p class="text-xs text-primary-muted">Son Fiyat (TL)</p>
<p class="text-xs font-bold text-content-primary">12.345678</p>
<p class="text-xs text-primary-muted">Kategorisi</p>
<p class="text-xs font-bold text-content-primary">Hisse Senedi Fonu</p>
<p class="text-xs text-primary-muted">Yatırımcı Sayısı</p>
<p class="text-xs font-bold text-content-primary">12,345</p>
</body></html>
"""


class TestStripTags:
    def test_removes_tags(self):
        assert tefas_web._strip_tags("<div>Hello</div>") == "Hello"

    def test_collapses_whitespace(self):
        assert tefas_web._strip_tags("<p>a   b</p>") == "a b"


class TestBetween:
    def test_extracts_text_between_markers(self):
        result = tefas_web._between(
            "<div>A</div><span>X</span>", "<div>A</div>", "</span>"
        )
        assert result == "X"

    def test_returns_none_if_start_not_found(self):
        assert tefas_web._between("abc", "NOT_THERE", "end") is None


class TestParseAllLabelValuePairs:
    def test_extracts_all_pairs(self):
        result = tefas_web._parse_all_label_value_pairs(SAMPLE_HTML)
        assert result.get("ISIN Kodu") == "TRYFNG00001"
        assert result.get("Fon Risk Değeri") == "5"
        assert result.get("Platform Durumu") == "TEFAS'ta işlem görüyor"
        assert result.get("Kategorisi") == "Hisse Senedi Fonu"

    def test_html_entities_decoded(self):
        """&#x27; gibi HTML entity'leri düzgün decode edilmeli."""
        result = tefas_web._parse_all_label_value_pairs(SAMPLE_HTML)
        assert result.get("Platform Durumu") == "TEFAS'ta işlem görüyor"


class TestFetchFundInfo:
    def test_returns_none_for_invalid_code(self, monkeypatch):
        def mock_fetch(code, timeout=10):
            return None

        monkeypatch.setattr(tefas_web, "_fetch_html", mock_fetch)
        assert tefas_web.fetch_fund_info("INVALID") is None
