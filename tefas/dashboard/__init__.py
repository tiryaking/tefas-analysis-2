"""Interaktif yerel web dashboard (Streamlit) - `tefas dashboard` ile acilir.

Salt-okuma BI analiz paneli: yalnizca Output/*.parquet OKUR ve
tefas.charts `prep_*` / tefas.comparison / tefas.allocation / tefas.narrative
saf fonksiyonlarini kullanir. Kisisel portfoy (holdings) ozellikleri BILEREK
dashboard'da yoktur; onlar yalnizca `tefas holdings` CLI'sindedir. Streamlit +
plotly opsiyoneldir: `pip install -e .[dashboard]`.
"""

