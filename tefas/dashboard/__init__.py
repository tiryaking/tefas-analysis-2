"""İnteraktif yerel web dashboard (Streamlit) — `tefas dashboard` ile açılır.

Pipeline'a sıfır bağımlılık: sayfalar yalnızca Output/*.parquet OKUR ve
tefas.charts `prep_*` / tefas.holdings / tefas.allocation saf fonksiyonlarını
kullanır. Streamlit + plotly opsiyoneldir: `pip install -e .[dashboard]`.
"""
