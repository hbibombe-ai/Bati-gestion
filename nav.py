"""Registre des pages accessibles à l'usager connecté (rempli par app.py)."""
from __future__ import annotations

import streamlit as st

PAGES: dict = {}


def lien(url: str, label: str, icone: str | None = None) -> bool:
    """Lien vers une page de l'application, seulement si l'usager y a accès."""
    p = PAGES.get(url)
    if p is None:
        return False
    st.page_link(p, label=label, icon=icone)
    return True


def aller(url: str) -> None:
    if url in PAGES:
        st.switch_page(PAGES[url])
