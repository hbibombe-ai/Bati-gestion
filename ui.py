"""Éléments d'interface communs : style Bâti Gestion, champs monétaires, tableaux, messages."""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import streamlit as st

import regles as R

DOSSIER = os.path.dirname(os.path.abspath(__file__))
STATIQUE = os.path.join(DOSSIER, "static")
_SVG = {
    "icone.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64"><rect width="64" height="64" rx="12" fill="#112740"/><path fill="#FFB347" d="M20 16h12v10h12v22H20z"/><g fill="#112740"><rect x="24" y="22" width="3" height="3"/><rect x="24" y="32" width="3" height="3"/><rect x="24" y="41" width="3" height="3"/><rect x="37" y="32" width="3" height="3"/><rect x="37" y="41" width="3" height="3"/></g></svg>""",
    "logo_sombre.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 40" width="210" height="40"><path fill="#FFB347" d="M3 6h11v9h11v21H3z"/><g fill="#112740"><rect x="6.5" y="11" width="3" height="3"/><rect x="6.5" y="20" width="3" height="3"/><rect x="6.5" y="29" width="3" height="3"/><rect x="18" y="20" width="3" height="3"/><rect x="18" y="29" width="3" height="3"/></g><text x="34" y="29" font-family="'Archivo','Helvetica Neue',Arial,sans-serif" font-size="23" font-weight="800" fill="#FFFFFF" letter-spacing="-0.5">Bâti Gestion</text></svg>""",
    "logo_clair.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 58" width="300" height="58"><path fill="#EFA63A" d="M3 8h14v12h14v28H3z"/><g fill="#FFFFFF"><rect x="7.5" y="14" width="4" height="4"/><rect x="7.5" y="26" width="4" height="4"/><rect x="7.5" y="38" width="4" height="4"/><rect x="22.5" y="26" width="4" height="4"/><rect x="22.5" y="38" width="4" height="4"/></g><text x="42" y="34" font-family="'Archivo','Helvetica Neue',Arial,sans-serif" font-size="27" font-weight="800" fill="#112740" letter-spacing="-0.6">Bâti Gestion</text><text x="43" y="52" font-family="'Archivo','Helvetica Neue',Arial,sans-serif" font-size="12" fill="#5B6E83">MY DESTINY SARL · gestion de chantier</text></svg>""",
}


def _statique() -> str:
    import tempfile
    for dossier in (STATIQUE, os.path.join(tempfile.gettempdir(), "bati_gestion_static")):
        try:
            os.makedirs(dossier, exist_ok=True)
            for nom, contenu in _SVG.items():
                chemin = os.path.join(dossier, nom)
                if not os.path.exists(chemin):
                    with open(chemin, "w", encoding="utf-8") as f:
                        f.write(contenu)
            return dossier
        except OSError:
            continue
    return STATIQUE


_S = _statique()
ICONE = os.path.join(_S, "icone.svg")
LOGO_SOMBRE = os.path.join(_S, "logo_sombre.svg")
LOGO_CLAIR = os.path.join(_S, "logo_clair.svg")

STYLE = """
<style>
/* ===== Jetons de couleur : bleu roi + orange chantier (logo Bâti Gestion inchangé) ===== */
:root{--bg-navy:#0f1a6e;--bg-navy-2:#1a27b5;--bleu:#1a27b5;--bleu-vif:#3d5afe;--ciel:#22b8f0;--ambre:#ff9f1c;--ambre-clair:#ffbe55;
 --vert:#12b886;--violet:#7048e8;--rose:#f0507a;--bord:#dde3ef;--texte:#16204d;--doux:#5a6684;--fond:#f4f6fb}
.stApp{background:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 620 260'%3E%3Ctext x='310' y='190' text-anchor='middle' transform='rotate%28-12 310 130%29' font-family='Archivo,Arial Black,Arial,Helvetica,sans-serif' font-weight='900' font-size='210' letter-spacing='8' fill='%231a27b5' fill-opacity='.05'%3EMDY%3C/text%3E%3C/svg%3E") no-repeat right 3vw bottom 6vh/min(48vw,640px) auto fixed,
 radial-gradient(1200px 500px at 100% 0,rgba(61,90,254,.07),transparent 60%),radial-gradient(900px 420px at 0 100%,rgba(255,159,28,.06),transparent 60%),#f4f6fb}
/* Filigrane « MDY » dans le bandeau */
.bg-bandeau::before{content:"";position:absolute;right:2vw;top:-6%;width:380px;height:112%;pointer-events:none;
 background:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 620 260'%3E%3Ctext x='310' y='190' text-anchor='middle' transform='rotate%28-12 310 130%29' font-family='Archivo,Arial Black,Arial,Helvetica,sans-serif' font-weight='900' font-size='210' letter-spacing='8' fill='%23ffffff' fill-opacity='.14'%3EMDY%3C/text%3E%3C/svg%3E") no-repeat center/contain}
.bg-bandeau .in{position:relative;z-index:1}

/* ===== En-tête blanc : logo + menu horizontal ===== */
[data-testid="stHeader"]{background:#fff;border-bottom:0;box-shadow:0 2px 10px rgba(15,26,110,.06);height:5rem}
[data-testid="stHeader"]::after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:linear-gradient(90deg,var(--ambre),var(--rose) 35%,var(--bleu-vif) 70%,var(--ciel))}
[data-testid="stHeader"] a,[data-testid="stHeader"] button{font-weight:600;color:var(--bg-navy)}
[data-testid="stHeader"] [aria-current="page"],[data-testid="stHeader"] [aria-selected="true"]{color:var(--bleu) !important;box-shadow:inset 0 -3px 0 var(--ambre)}
[data-testid="stHeaderLogo"],[data-testid="stLogo"]{height:3.4rem !important;max-width:18rem !important;width:auto !important}

/* ===== Mise en page et apparition douce ===== */
[data-testid="stMain"]{overflow-x:hidden}
.block-container{padding-top:5rem;padding-bottom:3rem;max-width:1320px}
@keyframes bgApparition{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
[data-testid="stMainBlockContainer"]{animation:bgApparition .4s cubic-bezier(.2,.7,.2,1) both}
@media (prefers-reduced-motion: reduce){[data-testid="stMainBlockContainer"]{animation:none}*{transition:none !important}}

/* ===== Barre d'outils sous l'en-tête : recherche, alertes, compte ===== */
.st-key-bg_barre{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:6px 10px;margin:.4rem 0 .2rem 0;
 box-shadow:0 1px 2px rgba(15,26,110,.04);align-items:center}
.st-key-bg_barre [data-testid="stCaptionContainer"],.st-key-bg_barre [data-testid="stCaptionContainer"] p{margin:0 !important;padding-left:6px}
.st-key-bg_barre [data-testid="stPageLink"] a{border:1px solid var(--bord);border-radius:10px;padding:4px 12px;background:#f7f8fc}
.st-key-bg_barre [data-testid="stPageLink"] a:hover{border-color:var(--bleu);background:#eef1fd}
.st-key-bg_alerte [data-testid="stPageLink"] a{background:var(--ambre);border-color:var(--ambre)}
.st-key-bg_alerte [data-testid="stPageLink"] a *{color:#fff !important;font-weight:700}
.st-key-bg_alerte [data-testid="stPageLink"] a:hover{background:#e0861a;border-color:#e0861a}

/* ===== Bandeau de page : bleu roi pleine largeur, titre et vague ===== */
.bg-bandeau{position:relative;width:100vw;margin:.6rem 0 1.4rem calc(50% - 50vw);background:var(--bleu);color:#fff;overflow:hidden;
 background-image:radial-gradient(circle at 88% 10%,rgba(34,184,240,.55) 0,rgba(34,184,240,0) 38%),
 radial-gradient(circle at 12% 120%,rgba(255,159,28,.35) 0,rgba(255,159,28,0) 40%),linear-gradient(115deg,#1a27b5 0%,#3d5afe 60%,#5b3fe0 100%)}
.bg-bandeau .in{max-width:1320px;margin:0 auto;padding:2.1rem 5rem 3.6rem 5rem;display:flex;gap:1.5rem;align-items:flex-end;justify-content:space-between;flex-wrap:wrap}
.bg-bandeau h1{color:#fff;font-size:2.35rem;font-weight:800;letter-spacing:-.6px;margin:0;padding:0;line-height:1.15}
.bg-bandeau p{color:rgba(255,255,255,.86);font-size:1.02rem;margin:.5rem 0 0 0;max-width:760px;line-height:1.5}
.bg-bandeau .badge{display:inline-flex;align-items:center;gap:.5rem;background:rgba(15,26,110,.72);backdrop-filter:blur(4px);border:1px solid rgba(255,255,255,.25);color:#fff;border-radius:999px;padding:.55rem 1.1rem;
 font-weight:700;font-size:.95rem;box-shadow:0 6px 18px rgba(0,0,0,.18);white-space:nowrap}
.bg-bandeau .badge i{width:.6rem;height:.6rem;border-radius:50%;background:var(--ambre-clair);box-shadow:0 0 0 4px rgba(255,179,71,.28)}
.bg-bandeau::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:42px;background:url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 42' preserveAspectRatio='none'%3E%3Cpath d='M0 26 C240 4 480 42 720 22 C960 2 1200 40 1440 18 L1440 42 L0 42 Z' fill='%23ffffff' fill-opacity='.18'/%3E%3Cpath d='M0 22 C240 44 480 0 720 22 C960 44 1200 0 1440 22 L1440 42 L0 42 Z' fill='%23f4f6fb'/%3E%3C/svg%3E") no-repeat center/100% 100%}

/* ===== Titres ===== */
h1{font-size:2.05rem;font-weight:800;letter-spacing:-.6px;color:var(--bg-navy)}
h2,h3{color:var(--bg-navy);letter-spacing:-.3px}
.bg-sous{font-size:1rem;color:var(--doux);margin:.85rem 0 1.5rem 0;max-width:820px;line-height:1.5}

/* ===== Barre latérale (petits écrans) ===== */
[data-testid="stNavSectionHeader"]{padding:0 14px;margin:1.1rem 0 .25rem 0 !important}
[data-testid="stNavSectionHeader"] p,[data-testid="stNavSectionHeader"] span{font-size:.7rem !important;font-weight:700 !important;letter-spacing:.12em;text-transform:uppercase;color:#9aa6d6 !important}
[data-testid="stSidebarNavLink"]{border-radius:10px;margin:2px 8px;transition:background .15s ease,color .15s ease}
[data-testid="stSidebarNavLink"]:hover{background:rgba(255,179,71,.10)}
[data-testid="stSidebarNavLink"][aria-current="page"]{background:rgba(255,179,71,.14);box-shadow:inset 3px 0 0 var(--ambre-clair)}

/* ===== Onglets : pastille orange sous l'onglet actif ===== */
[data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--bord)}
[data-baseweb="tab"]{background:transparent;border-radius:10px 10px 0 0;padding:.6rem 1.05rem;color:var(--doux);font-weight:600;transition:color .15s ease,background .15s ease}
[data-baseweb="tab"]:hover{color:var(--bleu);background:rgba(26,39,181,.05)}
[data-baseweb="tab"][aria-selected="true"]{color:var(--bg-navy);font-weight:700;box-shadow:inset 0 -3px 0 var(--ambre)}
[data-baseweb="tab-highlight"]{background:var(--ambre) !important;height:3px !important}
[data-baseweb="tab-border"]{display:none}

/* ===== Boutons : principal bleu roi, secondaire contour ===== */
[data-testid^="stBaseButton"]{border-radius:10px;font-weight:600;transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,transform .18s ease}
[data-testid="stBaseButton-primary"]{background:linear-gradient(120deg,var(--bleu),var(--bleu-vif));border-color:var(--bleu);color:#fff;box-shadow:0 4px 14px rgba(61,90,254,.30)}
[data-testid="stBaseButton-primary"]:hover{background:linear-gradient(120deg,var(--bg-navy),var(--bleu));border-color:var(--bg-navy);box-shadow:0 8px 22px rgba(61,90,254,.38);transform:translateY(-1px)}
[data-testid="stBaseButton-primary"]:active{transform:translateY(0)}
[data-testid="stBaseButton-secondary"]{background:#fff;border-color:#c8d0e4;color:var(--bleu)}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--bleu);background:#f3f5fe;box-shadow:0 2px 8px rgba(15,26,110,.08)}
[data-testid^="stBaseButton"]:disabled{opacity:.45;transform:none}
:focus-visible{outline:2px solid var(--ambre) !important;outline-offset:2px}

/* ===== Raccourcis (« Actions courantes ») en pastilles ===== */
.st-key-bg_actions [data-testid="stPageLink"] a{background:#fff;border:1px solid var(--bord);border-radius:12px;padding:8px 14px;
 box-shadow:0 1px 2px rgba(15,26,110,.04);transition:border-color .15s ease,box-shadow .15s ease,transform .15s ease}
.st-key-bg_actions [data-testid="stPageLink"] a:hover{border-color:var(--bleu);box-shadow:0 6px 16px rgba(15,26,110,.10);transform:translateY(-1px)}

/* ===== Champs de saisie ===== */
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]{border-radius:10px !important;border-color:#c8d0e4 !important;background:#fff}
[data-baseweb="input"]:focus-within,[data-baseweb="select"]>div:focus-within,[data-baseweb="textarea"]:focus-within{border-color:var(--bleu) !important;box-shadow:0 0 0 3px rgba(26,39,181,.14)}

/* ===== Cartes : métriques, formulaires, blocs repliables ===== */
[data-testid="stMetric"]{background:#fff;border:1px solid var(--bord);border-radius:16px;padding:16px 18px;box-shadow:0 1px 2px rgba(15,26,110,.04),0 8px 22px rgba(15,26,110,.06);transition:transform .2s ease,box-shadow .2s ease}
[data-testid="stMetric"]:hover{transform:translateY(-2px);box-shadow:0 2px 4px rgba(15,26,110,.06),0 14px 28px rgba(15,26,110,.10)}
[data-testid="stMetricLabel"]{color:var(--doux);font-weight:600}
[data-testid="stMetricValue"]{font-size:1.45rem;letter-spacing:-.5px;color:var(--bg-navy)}
[data-testid="stForm"]{border:1px solid var(--bord);border-radius:16px;background:#fff;padding:1rem 1.15rem;box-shadow:0 1px 2px rgba(15,26,110,.04)}
[data-testid="stExpander"]{border:1px solid var(--bord);border-radius:16px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(15,26,110,.03)}
[data-testid="stExpander"] summary{font-weight:600;color:var(--bg-navy)}

/* ===== Tableaux et messages ===== */
[data-testid="stDataFrame"]{border:1px solid var(--bord);border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 1px 2px rgba(15,26,110,.04),0 8px 22px rgba(15,26,110,.05)}
[data-testid="stDataFrame"] [role="columnheader"]{background:#e9eeff;color:var(--bg-navy);font-weight:700}
[data-testid="stAlert"]{border-radius:14px;border:1px solid var(--bord);box-shadow:0 1px 2px rgba(15,26,110,.03)}
[data-testid="stAlert"] p{font-size:.95rem}

/* ===== Repères de statut (chiffres clés et étiquettes) ===== */
.bg-tag{display:inline-block;background:#fff;border:1px solid var(--bord);border-radius:999px;padding:5px 12px;font-size:.84rem;color:var(--texte);margin:2px 6px 2px 0;box-shadow:0 1px 2px rgba(15,26,110,.04)}
.bg-tag b{color:var(--bg-navy)}
.bg-tag.ok{background:#e6f6ee;border-color:#bfe6cf;color:#176846}
.bg-tag.alerte{background:#fdeeec;border-color:#f3c4bf;color:#a62d25}
.bg-carte{background:#fff;border:1px solid var(--bord);border-radius:16px;padding:18px 20px;height:100%;box-shadow:0 1px 2px rgba(15,26,110,.04),0 8px 22px rgba(15,26,110,.06)}
.bg-carte.accent{border-top:4px solid var(--ambre)}
.bg-carte .t{font-size:.9rem;color:var(--doux);margin-bottom:.35rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.bg-carte .n{font-size:1.7rem;font-weight:800;letter-spacing:-1px;color:var(--bleu)}
.bg-carte .m{color:var(--doux);font-size:.85rem}
.bg-montants{font-variant-numeric:tabular-nums;line-height:1.55}
.bg-montants b{font-size:1.25rem;letter-spacing:-.3px}


/* ===== Couleurs vives : une teinte par carte de chiffres clés ===== */
[data-testid="stColumn"]:nth-child(1) .bg-carte{border-top:4px solid var(--ambre);background:linear-gradient(180deg,#fff7ea 0,#fff 55%)}
[data-testid="stColumn"]:nth-child(1) .bg-carte .n{color:#e07f00}
[data-testid="stColumn"]:nth-child(2) .bg-carte{border-top:4px solid var(--bleu-vif);background:linear-gradient(180deg,#eef1ff 0,#fff 55%)}
[data-testid="stColumn"]:nth-child(2) .bg-carte .n{color:var(--bleu)}
[data-testid="stColumn"]:nth-child(3) .bg-carte{border-top:4px solid var(--vert);background:linear-gradient(180deg,#e7f8f1 0,#fff 55%)}
[data-testid="stColumn"]:nth-child(3) .bg-carte .n{color:#0b8a63}
[data-testid="stColumn"]:nth-child(4) .bg-carte{border-top:4px solid var(--violet);background:linear-gradient(180deg,#f1edff 0,#fff 55%)}
[data-testid="stColumn"]:nth-child(4) .bg-carte .n{color:var(--violet)}
[data-testid="stMetric"]{border-top:4px solid var(--bleu-vif)}

/* ===== Raccourcis : icônes en couleur ===== */
.st-key-bg_actions [data-testid="stPageLink"] a [data-testid="stIconMaterial"]{font-size:1.35rem}
.st-key-bg_actions [data-testid="stPageLink"]:nth-of-type(5n+1) [data-testid="stIconMaterial"]{color:var(--bleu-vif) !important}
.st-key-bg_actions [data-testid="stPageLink"]:nth-of-type(5n+2) [data-testid="stIconMaterial"]{color:var(--ambre) !important}
.st-key-bg_actions [data-testid="stPageLink"]:nth-of-type(5n+3) [data-testid="stIconMaterial"]{color:var(--vert) !important}
.st-key-bg_actions [data-testid="stPageLink"]:nth-of-type(5n+4) [data-testid="stIconMaterial"]{color:var(--violet) !important}
.st-key-bg_actions [data-testid="stPageLink"]:nth-of-type(5n+5) [data-testid="stIconMaterial"]{color:var(--ciel) !important}
.st-key-bg_actions [data-testid="stElementContainer"]:nth-child(5n+1) [data-testid="stIconMaterial"]{color:var(--bleu-vif) !important}
.st-key-bg_actions [data-testid="stElementContainer"]:nth-child(5n+2) [data-testid="stIconMaterial"]{color:var(--ambre) !important}
.st-key-bg_actions [data-testid="stElementContainer"]:nth-child(5n+3) [data-testid="stIconMaterial"]{color:var(--vert) !important}
.st-key-bg_actions [data-testid="stElementContainer"]:nth-child(5n+4) [data-testid="stIconMaterial"]{color:var(--violet) !important}
.st-key-bg_actions [data-testid="stElementContainer"]:nth-child(5n+5) [data-testid="stIconMaterial"]{color:var(--ciel) !important}

/* ===== Messages en couleurs franches ===== */
[data-testid="stAlertContentInfo"]{color:#1a27b5}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){border-left:4px solid var(--ambre)}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){border-left:4px solid var(--bleu-vif)}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){border-left:4px solid var(--vert)}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){border-left:4px solid var(--rose)}


/* ===== Carte des chantiers : légende et compteur ===== */
.bg-carte-tete{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.6rem;margin:.2rem 0 .5rem 0}
.bg-carte-tete .g{display:flex;flex-wrap:wrap;gap:.4rem}
.bg-legende{display:inline-flex;align-items:center;gap:.4rem;background:#fff;border:1px solid var(--bord);border-radius:999px;padding:4px 10px;font-size:.84rem;color:var(--texte)}
.bg-legende i{width:.7rem;height:.7rem;border-radius:50%;display:inline-block}
.bg-compteur{display:inline-flex;align-items:center;gap:.5rem;background:var(--bg-navy);color:#fff;border-radius:999px;padding:.5rem 1rem;font-weight:700;font-size:.92rem;box-shadow:0 6px 18px rgba(15,26,110,.22)}
.bg-compteur i{width:.6rem;height:.6rem;border-radius:50%;background:var(--ambre-clair);box-shadow:0 0 0 4px rgba(255,179,71,.28)}
[data-testid="stDeckGlJsonChart"]{border-radius:18px;overflow:hidden;border:1px solid var(--bord);box-shadow:0 8px 22px rgba(15,26,110,.08)}

/* ===== Petits écrans : marges de 16 px, pas de défilement horizontal ===== */
@media (max-width: 760px){
 [data-testid="stMainBlockContainer"].block-container{padding-left:16px;padding-right:16px;padding-top:4.8rem}
 .bg-bandeau .in{padding:1.4rem 16px 3rem 16px}
 .bg-bandeau h1{font-size:1.65rem}
 h1{font-size:1.6rem}
 [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
 [data-testid="stMetricValue"]{font-size:1.2rem}
}
</style>
"""
STYLE_CONNEXION = """
.stApp,[data-testid="stAppViewContainer"]{background:
 url("data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 42' preserveAspectRatio='none'%3E%3Cpath d='M0 22 C240 44 480 0 720 22 C960 44 1200 0 1440 22 L1440 42 L0 42 Z' fill='%23f4f6fb'/%3E%3C/svg%3E") no-repeat 0 calc(42vh - 41px)/100% 42px,
 linear-gradient(180deg,#1a27b5 0,#2434d6 42vh,#f4f6fb 42vh) !important}
[data-testid="stHeader"]{background:transparent !important;border:0 !important;box-shadow:none !important}
[data-testid="stForm"]{background:#fff;border:1px solid #dde3ef;border-top:4px solid #f39a2e;border-radius:16px;padding:10px 8px;
 box-shadow:0 18px 40px rgba(15,26,110,.18)}
[data-testid="stImage"] img{background:#fff;border-radius:14px;padding:10px 14px;box-shadow:0 10px 30px rgba(15,26,110,.22)}
"""

def appliquer_style(connexion: bool = False) -> None:
    # Une seule balise <style> : Streamlit n'en conserve qu'une par bloc HTML.
    st.html(STYLE.replace("</style>", (STYLE_CONNEXION if connexion else "") + "</style>"))


def en_tete(titre: str, sous_titre: str = "", badge: str = "") -> None:
    """Bandeau bleu pleine largeur : titre de la page, sous-titre et, au besoin, un badge (ex. « 3 chantiers en cours »)."""
    pastille = f'<span class="badge"><i></i>{_esc(badge)}</span>' if badge else ""
    sous = f"<p>{_esc(sous_titre)}</p>" if sous_titre else ""
    st.html(f'<section class="bg-bandeau"><div class="in"><div><h1>{_esc(titre)}</h1>{sous}</div>{pastille}</div>'
            '</section>')
    flash()


def barre_haut(utilisateur: dict, poste: str) -> None:
    """Barre d'outils commune sous l'en-tête : usager connecté, recherche, alertes, compte et déconnexion."""
    import auth
    import nav
    with st.container(horizontal=True, key="bg_barre", gap="small", vertical_alignment="center",
                      horizontal_alignment="distribute"):
        st.caption(f"Connecté : **{utilisateur['nom']}** · {poste}")
        with st.container(horizontal=True, gap="small", vertical_alignment="center", width="content"):
            nav.lien("recherche", "Rechercher", ":material/search:")
            with st.container(key="bg_alerte", width="content"):
                nav.lien("rapports", "Alertes", ":material/campaign:")
            nav.lien("mon-compte", "Mon compte", ":material/person:")
            if st.button("Se déconnecter", icon=":material/logout:", key="bg_deconnexion"):
                auth.deconnecter()
                st.rerun()


def _esc(t) -> str:
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def flash() -> None:
    for niveau in ("succes", "erreur", "info"):
        msg = st.session_state.pop(f"flash_{niveau}", None)
        if msg:
            {"succes": st.success, "erreur": st.error, "info": st.info}[niveau](msg)


def mime_fichier(contenu: bytes) -> str | None:
    """Type réel du fichier, d'après son contenu (PDF, JPEG ou PNG)."""
    if contenu[:4] == b"%PDF":
        return "application/pdf"
    if contenu[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if contenu[:4] == b"\x89PNG":
        return "image/png"
    return None


def pieces_jointes(entite: str, entite_id: str, peut_ajouter: bool, titre: str = "Documents joints") -> None:
    """Liste les documents joints à une fiche ; ajoute ou retire selon les droits de l'usager."""
    import hashlib
    import re

    import auth
    import db

    rows = db.requete("select id, nom, libelle, taille, mime, ajoute_par, ajoute_le from pieces_jointes "
                      "where entite = :e and entite_id = :i order by ajoute_le", e=entite, i=entite_id)
    with st.expander(f"{titre} ({len(rows)})", expanded=bool(rows)):
        if not rows:
            st.caption("Aucun document joint à cette fiche.")
        moi = (auth.utilisateur() or {}).get("id")
        dg = auth.droit("approbation_dg") == "w"
        for r in rows[:50]:
            a, b, c = st.columns([5, 2, 2])
            a.markdown(f"**{r['nom']}**  \n{r['libelle'] or '—'}")
            b.caption(f"{r['taille'] // 1024} Ko · {str(r['ajoute_le'])[:10]}")
            with c:
                contenu = db.requete("select contenu from pieces_jointes where id = :i", i=r["id"])[0]["contenu"]
                telecharger("Ouvrir", contenu, r["nom"], r["mime"], key=f"pj_dl_{r['id']}")
                if peut_ajouter and (dg or r["ajoute_par"] == moi) and st.button("Retirer", key=f"pj_del_{r['id']}",
                                                                                   icon=":material/delete:"):
                    with db.transaction(f"Retrait du document {r['nom']}") as t:
                        t.supprimer("pieces_jointes", r["id"])
                    succes("Document retiré.")
        if peut_ajouter:
            with st.form(f"pj_form_{entite}_{entite_id}", clear_on_submit=True):
                st.markdown("**Joindre un document** — PDF, JPEG ou PNG, 5 Mo au plus")
                libelle = st.text_input("Libellé", placeholder="ex. Contrat signé, Permis, Attestation fiscale")
                fichiers = st.file_uploader("Fichier(s)", type=["pdf", "jpg", "jpeg", "png"],
                                            accept_multiple_files=True)
                ok = st.form_submit_button("Joindre", type="primary")
            if ok:
                try:
                    if not fichiers:
                        raise ValueError("Choisissez au moins un fichier.")
                    for f in fichiers:
                        contenu = f.getvalue()
                        if not contenu or len(contenu) > R.PIECE_MAX:
                            raise ValueError(f"« {f.name} » : fichier vide ou plus de 5 Mo.")
                        mime = mime_fichier(contenu)
                        if not mime:
                            raise ValueError(f"« {f.name} » : seuls les PDF, JPEG et PNG sont acceptés.")
                        empreinte = hashlib.sha256(contenu).hexdigest()
                        if db.requete("select id from pieces_jointes where entite = :e and entite_id = :i and sha256 = :h",
                                      e=entite, i=entite_id, h=empreinte):
                            raise ValueError(f"« {f.name} » est déjà joint à cette fiche.")
                        nom = re.sub(r'[\\/:*?"<>|]+', "_", f.name)[:280] or "document"
                        with db.transaction(f"Document joint : {nom}") as t:
                            t.inserer("pieces_jointes", {"id": db.nouvel_id(), "entite": entite, "entite_id": entite_id,
                                                        "libelle": (libelle or "").strip()[:200], "nom": nom, "mime": mime,
                                                        "taille": len(contenu), "sha256": empreinte, "contenu": contenu,
                                                        "ajoute_par": moi, "ajoute_le": db.maintenant()})
                except ValueError as e:
                    st.error(str(e))
                else:
                    succes("Document(s) joint(s).")


def succes(msg: str, rerun: bool = True) -> None:
    st.session_state["flash_succes"] = msg
    if rerun:
        st.rerun()


def carte(titre: str, valeur_html: str, note: str = "", accent: bool = False) -> None:
    st.html(f'<div class="bg-carte{" accent" if accent else ""}"><div class="t">{_esc(titre)}</div>'
            f'<div class="n">{valeur_html}</div><div class="m">{_esc(note)}</div></div>')


def consolide(totaux: dict[str, int]) -> str:
    """Total converti au dernier taux du jour (affichage seulement) ; vide si inutile ou indisponible."""
    try:
        import devises
        return devises.texte_consolide(totaux)
    except Exception:  # noqa: BLE001 — l'affichage consolidé ne doit jamais empêcher l'affichage des totaux
        return ""


def montants_html(totaux: dict[str, int]) -> str:
    """Totaux séparés par monnaie, sans conversion, puis le total consolidé indicatif."""
    c = consolide(totaux)
    return '<div class="bg-montants">' + "<br>".join(
        f"<b>{_esc(R.money(totaux.get(c_, 0), c_))}</b>" for c_ in R.CURRENCIES) + (
        f'<br><span style="font-size:.8em;opacity:.75">{_esc(c)}</span>' if c else "") + "</div>"


def montants_texte(totaux: dict[str, int], seulement_non_nuls: bool = False, consolide_aussi: bool = False) -> str:
    parts = [R.money(totaux.get(c, 0), c) for c in R.CURRENCIES if not seulement_non_nuls or totaux.get(c)]
    texte = " · ".join(parts) or R.money(0, R.company().get("defaultCurrency", "USD"))
    if consolide_aussi and (c := consolide(totaux)):
        texte += f" ({c})" if not c.startswith("≈") else f" · {c}"
    return texte


# ------------------------------------------------------------------ champs
def devise(label: str, key: str, valeur: str | None = None, disabled: bool = False) -> str:
    valeur = valeur or R.company().get("defaultCurrency", "USD")
    return st.selectbox(label, R.CURRENCIES, index=R.CURRENCIES.index(valeur), key=key,
                        format_func=lambda c: R.CURRENCY_LABELS[c], disabled=disabled)


def montant(label: str, key: str, cents: int | None = 0, aide: str | None = None, disabled: bool = False,
            minimum: float = 0.0, maximum: float | None = None) -> float:
    return st.number_input(label, min_value=minimum, max_value=maximum, value=(cents or 0) / 100, step=1.0,
                           format="%.2f", key=key, help=aide, disabled=disabled)


def date_txt(label: str, key: str, valeur: str | None = None, vide_ok: bool = False, max_aujourdhui: bool = False,
             aide: str | None = None) -> str:
    """Champ date renvoyant AAAA-MM-JJ (ou « » si vide autorisé)."""
    v = dt.date.fromisoformat(valeur) if valeur and R.is_date(valeur) else (None if vide_ok else dt.date.today())
    d = st.date_input(label, value=v, key=key, format="DD/MM/YYYY",
                      max_value=dt.date.today() if max_aujourdhui else None, help=aide,
                      min_value=dt.date(1990, 1, 1))
    return d.isoformat() if d else ""


def choix(label: str, options: dict, key: str, valeur=None, vide: str | None = None, aide: str | None = None,
          disabled: bool = False):
    """Liste déroulante à partir d'un dict {valeur: libellé}. « vide » ajoute une option sans valeur ("")."""
    opts = ([""] if vide is not None else []) + list(options)
    if valeur not in opts:
        valeur = opts[0] if opts else None
    return st.selectbox(label, opts, index=opts.index(valeur) if opts else None, key=key, help=aide, disabled=disabled,
                        format_func=lambda k: (vide if k == "" and vide is not None else options.get(k, k)))


def options_chantiers(s: dict) -> dict:
    return {p["id"]: p["name"] for p in s["projects"]}


def options_clients(s: dict, courant: str = "") -> dict:
    return {c["id"]: c["name"] + (" (archivé)" if c.get("archived") else "") for c in s["clients"]
            if "client" in R.party_roles(c) and (not c.get("archived") or c["id"] == courant)}


def options_fournisseurs(s: dict, courant: str = "") -> dict:
    return {c["id"]: c["name"] + (" (archivé)" if c.get("archived") else "") for c in s["clients"]
            if set(R.party_roles(c)) & {"supplier", "subcontractor"} and (not c.get("archived") or c["id"] == courant)}


# ------------------------------------------------------------------ tableaux
def tableau(lignes: list[dict], colonnes: dict, key: str | None = None, selection: bool = False,
            hauteur: int | None = None):
    """Affiche un tableau. Avec selection=True, renvoie l'index de la ligne choisie (ou None)."""
    df = pd.DataFrame(lignes, columns=list(colonnes) + (["_id"] if lignes and "_id" in lignes[0] else []))
    cfg = {k: (v if not isinstance(v, str) else st.column_config.TextColumn(v)) for k, v in colonnes.items()}
    kwargs = {"hide_index": True, "column_order": list(colonnes), "column_config": cfg, "width": "stretch"}
    if hauteur:
        kwargs["height"] = hauteur
    if selection:
        ev = st.dataframe(df, key=key, on_select="rerun", selection_mode="single-row", **kwargs)
        rows = ev.selection.rows if ev and ev.selection else []
        return rows[0] if rows and rows[0] < len(df) else None
    st.dataframe(df, key=key, **kwargs)
    return None


def col_montant(titre: str):
    return st.column_config.TextColumn(titre)


def telecharger(label: str, data: bytes, nom: str, mime: str, key: str | None = None, principal: bool = False) -> None:
    st.download_button(label, data=data, file_name=nom, mime=mime, key=key, on_click="ignore",
                       type="primary" if principal else "secondary", icon=":material/download:")


MIME_CSV = "text/csv"
MIME_PDF = "application/pdf"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def lecture_seule(module_label: str = "") -> None:
    st.caption("Consultation seulement : votre rôle ne permet pas de modifier cette rubrique.")


def rangee(n: int = 1):
    """Rangée de boutons alignés à gauche ; renvoie n références au même conteneur horizontal
    (utilisable comme st.columns pour placer les boutons dans l'ordre)."""
    c = st.container(horizontal=True, gap="small", vertical_alignment="center")
    return [c] * n
