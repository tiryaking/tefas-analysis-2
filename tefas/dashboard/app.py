"""TEFAS Analiz Merkezi — çok sayfalı yönlendirici (st.navigation).

Sidebar başlıkları/ikonları burada tanımlanır (dosya adı yerine) — böylece
"app" gibi ham dosya adları görünmez. Sayfa içerikleri `views/` altında;
her biri AppTest ile tek tek de çalıştırılabilir.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

st.set_page_config(page_title="TEFAS Analiz Merkezi", page_icon="📊", layout="wide")

_VIEWS = Path(__file__).parent / "views"
_PAGES = [
    st.Page(str(_VIEWS / "ozet.py"), title="Özet", icon="📊", default=True),
    st.Page(str(_VIEWS / "fon_kesif.py"), title="Fon Keşif", icon="🔎"),
    st.Page(str(_VIEWS / "fon_detay.py"), title="Fon Detay", icon="🔬"),
    st.Page(str(_VIEWS / "karsilastirma.py"), title="Karşılaştırma", icon="⚖️"),
    st.Page(str(_VIEWS / "portfoy_risk.py"), title="Portföy & Risk", icon="🏦"),
    st.Page(str(_VIEWS / "model.py"), title="Model & Metodoloji", icon="📜"),
]

st.navigation(_PAGES).run()
