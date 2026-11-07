"""Composants d'interface façon ERP (inspirés d'Odoo).

- grille d'applications (page d'accueil des modules) et barre de module en haut de chaque page ;
- vue « kanban / liste » avec recherche, filtres, regroupements et vues supplémentaires (carte…) ;
- fiche ouverte avec fil d'Ariane, barre d'étapes cliquable et fil d'activité (historique + notes internes).

Les notes internes sont écrites dans le journal d'audit (action « Note ») : aucune table supplémentaire.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from typing import Callable, Iterable

import streamlit as st

import db
import ui

# ------------------------------------------------------------------ applications (une par section du menu)
# section : (nom affiché, icône Material, couleur 1, couleur 2, description courte)
APPS: dict[str, tuple[str, str, str, str, str]] = {
    "Accueil": ("Tableau de bord", "dashboard", "#1a27b5", "#3d5afe", "Vue d’ensemble, recherche, alertes"),
    "Commercial": ("Commercial", "request_quote", "#ff8a00", "#ffb84d", "Devis, factures, prospects"),
    "Projets & Chantiers": ("Chantiers", "construction", "#f76707", "#ffa94d", "Chantiers, DQE, situations"),
    "Achats & Stocks": ("Achats & Stocks", "inventory", "#0ca678", "#38d9a9", "Demandes, commandes, magasin"),
    "RH & Paie": ("RH & Paie", "badge", "#7048e8", "#9775fa", "Personnel, pointage, paie"),
    "Finance": ("Finance", "account_balance", "#0b7285", "#22b8cf", "Dépenses, caisse, trésorerie"),
    "Tiers": ("Contacts", "contacts", "#d6336c", "#f783ac", "Clients, fournisseurs, comptes"),
    "Comptabilité & Documents": ("Comptabilité", "calculate", "#364fc7", "#748ffc", "Écritures, documents, imports"),
    "Administration": ("Paramètres", "settings", "#495057", "#868e96", "Société, utilisateurs, audit"),
}
URL_APPLICATIONS = "applications"


def _norm(t) -> str:
    """Minuscules sans accents, pour une recherche tolérante (« Évaluation » = « evaluation »)."""
    return unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()


def initiales(nom: str) -> str:
    mots = [m for m in str(nom or "").replace("-", " ").split() if m[:1].isalnum()]
    return ("".join(m[0] for m in mots[:2]) or "?").upper()


def couleur_nom(nom: str) -> str:
    """Couleur stable pour un nom (avatars)."""
    teintes = ["#1a27b5", "#f76707", "#0ca678", "#7048e8", "#0b7285", "#d6336c", "#364fc7", "#e8590c"]
    return teintes[int(hashlib.md5(str(nom or "").encode()).hexdigest(), 16) % len(teintes)]


def _url(p) -> str:
    return getattr(p, "url_path", "") or ""


STYLE_APPS = """
<style>
.stApp{background:radial-gradient(1000px 520px at 85% -10%,rgba(34,184,240,.45),transparent 60%),
 radial-gradient(900px 500px at -10% 110%,rgba(255,138,0,.35),transparent 60%),linear-gradient(135deg,#0f1a6e 0%,#1a27b5 45%,#5b3fe0 100%) fixed !important}
.bg-accueil-apps{color:#fff;text-align:center;margin:1.2rem 0 .6rem}
.bg-accueil-apps h1{color:#fff;font-size:2.1rem;margin:0}
.bg-accueil-apps p{color:rgba(255,255,255,.82);margin:.3rem 0 0}
.st-key-bg_apps_q{max-width:520px;margin:0 auto}
.st-key-bg_apps{max-width:980px;margin:1.4rem auto 0 auto;row-gap:1.6rem !important}
[class*="st-key-bg_app_"] [data-testid="stPageLink"] a{display:flex;flex-direction:column;align-items:center;gap:.55rem;background:transparent !important;
 border:0;padding:6px;border-radius:18px;text-decoration:none;transition:transform .15s ease}
[class*="st-key-bg_app_"] [data-testid="stPageLink"] a:hover{transform:translateY(-3px)}
[class*="st-key-bg_app_"] [data-testid="stPageLink"] a p,[class*="st-key-bg_app_"] [data-testid="stPageLink"] a span{color:#fff !important;font-weight:700;font-size:.95rem;text-align:center;text-shadow:0 1px 2px rgba(0,0,0,.25)}
[class*="st-key-bg_app_"] [data-testid="stElementContainer"],[class*="st-key-bg_app_"] [data-testid="stPageLink"]>div{width:100% !important}
[class*="st-key-bg_app_"] [data-testid="stPageLink"] a>span:first-child{width:84px !important;height:84px !important;min-width:84px;border-radius:22px;display:grid !important;
 place-items:center;margin:0 !important;box-shadow:0 10px 24px rgba(0,0,0,.25),inset 0 -4px 0 rgba(0,0,0,.12)}
[class*="st-key-bg_app_"] [data-testid="stIconMaterial"]{font-size:44px !important;color:#fff !important;line-height:1}
[class*="st-key-bg_app_"] .bg-app-desc{color:rgba(255,255,255,.72);font-size:.78rem;text-align:center;line-height:1.25;margin-top:-.2rem}
.st-key-bg_apps_res{background:#fff;border-radius:16px;padding:10px 14px;max-width:620px;margin:1rem auto 0 auto;box-shadow:0 14px 34px rgba(0,0,0,.25)}
.st-key-bg_odoo{background:rgba(255,255,255,.96) !important}
</style>
"""

STYLE_ERP = """
<style>
/* ===== Barre de module (façon Odoo) ===== */
.st-key-bg_odoo{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:6px 10px;margin:.3rem 0 .4rem 0;
 box-shadow:0 1px 2px rgba(15,26,110,.04),0 6px 18px rgba(15,26,110,.05);row-gap:6px}
.st-key-bg_odoo [data-testid="stPageLink"] a{border-radius:10px;padding:4px 10px;border:1px solid transparent}
.st-key-bg_odoo [data-testid="stPageLink"] a:hover{background:#eef1fd;border-color:#d6ddfb}
.st-key-bg_odoo .bg-mod{font-weight:800;font-size:1.08rem;color:var(--bg-navy);padding:0 .5rem 0 .2rem;white-space:nowrap;display:inline-flex;align-items:center;gap:.45rem}
.st-key-bg_odoo .bg-mod i{width:26px;height:26px;border-radius:8px;display:inline-block}
.st-key-bg_appsbtn [data-testid="stPageLink"] a{background:var(--bg-navy) !important;border-color:var(--bg-navy) !important}
.st-key-bg_appsbtn [data-testid="stPageLink"] a *{color:#fff !important}
.st-key-bg_cur [data-testid="stPageLink"] a{background:#eef1fd;border-color:#c9d2fb;box-shadow:inset 0 -3px 0 var(--ambre)}
.st-key-bg_cur [data-testid="stPageLink"] a *{color:var(--bleu) !important;font-weight:700}
.st-key-bg_moi [data-testid="stPopover"] button{border-radius:999px;padding:2px 12px 2px 4px}
.bg-avatar{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;color:#fff;font-weight:800;font-size:.78rem;flex:0 0 auto}

/* ===== Panneau de contrôle : recherche, filtres, regroupement, vue ===== */
[class*="st-key-bg_cp_"]{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:8px 10px;margin-bottom:.6rem;row-gap:8px}
[class*="st-key-bg_cp_"] [data-testid="stCaptionContainer"] p{margin:0}
.bg-compte{color:var(--doux);font-size:.88rem;white-space:nowrap}
[class*="st-key-bg_cp_"] [data-testid="stButtonGroup"],[class*="st-key-bg_cp_"] [data-testid="stButtonGroup"]>div{flex-wrap:wrap !important;max-width:100%}

/* ===== Kanban ===== */
.bg-colonne{display:flex;justify-content:space-between;align-items:center;font-weight:800;color:var(--bg-navy);padding:6px 4px;margin-bottom:6px;border-bottom:3px solid var(--k,#c8d0e4)}
.bg-colonne span{background:#e9eeff;color:var(--bleu);border-radius:999px;padding:1px 10px;font-size:.8rem}
[class*="st-key-bg_k_"]{background:#fff;border:1px solid var(--bord);border-left:4px solid var(--k,#c8d0e4);border-radius:12px;padding:10px 12px 4px 12px;
 box-shadow:0 1px 2px rgba(15,26,110,.04);transition:box-shadow .15s ease,transform .15s ease;gap:4px !important}
[class*="st-key-bg_k_"]:hover{box-shadow:0 10px 24px rgba(15,26,110,.10);transform:translateY(-1px)}
.bg-kc .h{display:flex;gap:10px;align-items:center}
.bg-kc .h b{display:block;color:var(--bg-navy);font-size:1rem;line-height:1.2}
.bg-kc .h small{display:block;color:var(--doux);font-size:.84rem}
.bg-kc .av{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;color:#fff;font-weight:800;flex:0 0 auto}
.bg-kc .l{margin-top:6px;color:var(--texte);font-size:.86rem;line-height:1.45}
.bg-kc .l div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bg-kc .pb{height:6px;border-radius:3px;background:#edf0f7;margin:8px 0 2px;overflow:hidden}
.bg-kc .pb i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--ambre),var(--vert))}
.bg-kc .pc{font-size:.76rem;color:var(--doux)}
.bg-kc .tg{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px}
.bg-kc .tg span{border-radius:999px;padding:1px 9px;font-size:.75rem;font-weight:700;background:#eef1fd;color:var(--bleu)}
[class*="st-key-bg_k_"] [data-testid^="stBaseButton"]{min-height:1.8rem;padding:0 6px}
.bg-groupe{display:flex;align-items:center;gap:.6rem;margin:.8rem 0 .3rem 0;font-weight:800;color:var(--bg-navy)}
.bg-groupe span{background:#e9eeff;color:var(--bleu);border-radius:999px;padding:1px 10px;font-size:.8rem}

/* ===== Fiche : fil d'Ariane, étapes, fil d'activité ===== */
.st-key-bg_ariane{margin:.4rem 0 .6rem 0;align-items:center}
.bg-ariane{font-size:1.35rem;color:var(--doux);font-weight:600}
.bg-ariane b{color:var(--bg-navy);font-weight:800}
.bg-etapes{display:flex;flex-wrap:wrap;gap:0}
.bg-etapes span{position:relative;padding:6px 18px 6px 22px;background:#edf0f7;color:var(--doux);font-weight:700;font-size:.85rem;
 clip-path:polygon(0 0,calc(100% - 10px) 0,100% 50%,calc(100% - 10px) 100%,0 100%,10px 50%);margin-right:-4px}
.bg-etapes span:first-child{clip-path:polygon(0 0,calc(100% - 10px) 0,100% 50%,calc(100% - 10px) 100%,0 100%);border-radius:8px 0 0 8px}
.bg-etapes span.on{background:var(--bleu);color:#fff}
.st-key-bg_etapes [data-testid="stButtonGroup"] button[aria-checked="true"],.st-key-bg_etapes [data-testid="stButtonGroup"] button[kind="segmented_controlActive"]{background:var(--bleu) !important;color:#fff !important;border-color:var(--bleu) !important}
.st-key-bg_feuille{background:#fff;border:1px solid var(--bord);border-radius:16px;padding:14px 18px;box-shadow:0 1px 2px rgba(15,26,110,.04),0 8px 22px rgba(15,26,110,.05)}
.st-key-bg_chatter{background:#fbfcff;border:1px solid var(--bord);border-radius:16px;padding:12px 14px}
.bg-chat-t{font-weight:800;color:var(--bg-navy);font-size:1.02rem;margin:0 0 .3rem}
.bg-msg{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #eef1f7}
.bg-msg:last-child{border-bottom:0}
.bg-msg .c{flex:1;min-width:0}
.bg-msg .q{font-size:.86rem;color:var(--doux)}
.bg-msg .q b{color:var(--bg-navy)}
.bg-msg .a{display:inline-block;border-radius:999px;padding:0 8px;font-size:.72rem;font-weight:700;margin-left:4px;background:#eef1fd;color:var(--bleu)}
.bg-msg .a.note{background:#fff4e0;color:#b35c00}
.bg-msg .a.cre{background:#e6f6ee;color:#176846}
.bg-msg .a.sup{background:#fdeeec;color:#a62d25}
.bg-msg .t{font-size:.92rem;color:var(--texte);margin-top:2px;overflow-wrap:anywhere}
.bg-msg .t.note{background:#fff;border:1px solid #f3dcb8;border-radius:10px;padding:6px 10px;margin-top:4px}
.bg-msg ul{margin:4px 0 0 0;padding-left:1.1rem;font-size:.84rem;color:var(--doux)}
.bg-msg ul b{color:var(--texte)}
</style>
"""


def appliquer_style_erp() -> None:
    st.html(STYLE_ERP)


# ------------------------------------------------------------------ grille d'applications
def page_applications(sections: dict[str, list], utilisateur: dict) -> None:
    """Accueil des modules : une icône par application, comme l'écran d'accueil d'Odoo."""
    st.html(STYLE_APPS)
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
            "novembre", "décembre"]
    d = dt.date.today()
    prenom = str(utilisateur.get("nom") or "").split(" ")[0]
    st.html(f'<div class="bg-accueil-apps"><h1>Bonjour {ui._esc(prenom)}</h1>'
            f'<p>{jours[d.weekday()].capitalize()} {d.day} {mois[d.month - 1]} {d.year} · choisissez une application</p></div>')
    with st.container(key="bg_apps_q"):
        q = st.text_input("Rechercher un menu", placeholder="Rechercher un menu : factures, caisse, pointage…",
                          label_visibility="collapsed", key="bg_apps_recherche")
    if q.strip():
        nq = _norm(q)
        trouves = [(sec, p) for sec, pages in sections.items() for p in pages
                   if nq in _norm(p.title) or nq in _norm(APPS.get(sec, (sec,))[0]) or nq in _norm(sec)]
        with st.container(key="bg_apps_res"):
            if not trouves:
                st.caption("Aucun menu ne correspond.")
            for sec, p in trouves[:20]:
                st.page_link(p, label=f"{APPS.get(sec, (sec,))[0]} › {p.title}", icon=p.icon or None)
    css = []
    with st.container(horizontal=True, key="bg_apps", gap="large", horizontal_alignment="center"):
        for i, (sec, pages) in enumerate(sections.items()):
            nom, icone, c1, c2, desc = APPS.get(sec, (sec, "apps", "#1a27b5", "#3d5afe", ""))
            css.append(f'.st-key-bg_app_{i} [data-testid="stPageLink"] a>span:first-child{{background:linear-gradient(135deg,{c1},{c2})}}')
            with st.container(key=f"bg_app_{i}", width=136):
                st.page_link(pages[0], label=nom, icon=f":material/{icone}:")
                st.html(f'<div class="bg-app-desc">{ui._esc(desc)}</div>')
    st.html("<style>" + "".join(css) + "</style>")


# ------------------------------------------------------------------ barre de module
def barre_module(page_active, page_apps, sections: dict[str, list], utilisateur: dict, poste: str) -> None:
    """Barre en haut de chaque page : bouton Applications, nom du module, ses menus, puis recherche et compte."""
    import auth
    import nav
    section = next((sec for sec, pages in sections.items() if any(_url(p) == _url(page_active) for p in pages)), None)
    with st.container(horizontal=True, key="bg_odoo", gap="small", vertical_alignment="center",
                      horizontal_alignment="distribute"):
        with st.container(horizontal=True, gap="small", vertical_alignment="center", width="content"):
            with st.container(key="bg_appsbtn", width="content"):
                st.page_link(page_apps, label="Applications", icon=":material/apps:")
            if section:
                nom, _, c1, c2, _ = APPS.get(section, (section, "", "#1a27b5", "#3d5afe", ""))
                st.html(f'<span class="bg-mod"><i style="background:linear-gradient(135deg,{c1},{c2})"></i>'
                        f'{ui._esc(nom)}</span>')
                for p in sections[section]:
                    if _url(p) == _url(page_active):
                        with st.container(key="bg_cur", width="content"):
                            st.page_link(p, label=p.title, icon=p.icon or None)
                    else:
                        st.page_link(p, label=p.title, icon=p.icon or None)
        with st.container(horizontal=True, gap="small", vertical_alignment="center", width="content"):
            nav.lien("recherche", "Rechercher", ":material/search:")
            with st.container(key="bg_alerte", width="content"):
                nav.lien("rapports", "Alertes", ":material/campaign:")
            with st.container(key="bg_moi", width="content"):
                with st.popover(str(utilisateur.get("nom") or "Mon compte"), icon=":material/account_circle:"):
                    st.html(f'<div style="display:flex;gap:10px;align-items:center"><span class="bg-avatar" '
                            f'style="background:{couleur_nom(utilisateur.get("nom"))}">{ui._esc(initiales(utilisateur.get("nom")))}'
                            f'</span><div><b>{ui._esc(utilisateur.get("nom"))}</b><br><small>{ui._esc(poste)}</small></div></div>')
                    nav.lien("mon-compte", "Mon compte", ":material/person:")
                    if st.button("Se déconnecter", icon=":material/logout:", key="bg_deconnexion"):
                        auth.deconnecter()
                        st.rerun()


# ------------------------------------------------------------------ fiche ouverte (état de navigation)
def fiche_ouverte(cle: str) -> str | None:
    return st.session_state.get(f"bg_fiche_{cle}")


def ouvrir(cle: str, id_) -> None:
    st.session_state[f"bg_fiche_{cle}"] = id_
    st.rerun()


def fermer(cle: str) -> None:
    st.session_state.pop(f"bg_fiche_{cle}", None)
    st.session_state[f"bg_gen_{cle}"] = st.session_state.get(f"bg_gen_{cle}", 0) + 1   # remet les sélections à zéro


def fil_ariane(racine: str, titre: str, cle: str) -> None:
    """« ← Chantiers / Résidence Kintambo » : retour à la liste par le bouton."""
    with st.container(horizontal=True, key="bg_ariane", gap="small", vertical_alignment="center"):
        if st.button(racine, icon=":material/arrow_back:", key=f"bg_retour_{cle}", type="tertiary"):
            fermer(cle)
            st.rerun()
        st.html(f'<span class="bg-ariane">/ <b>{ui._esc(titre)}</b></span>')
    ui.flash()


def barre_etapes(etapes: list[str], courante: str, cle: str, modifiable: bool = False) -> str | None:
    """Étapes d'un dossier (statusbar Odoo). Si modifiable, renvoie la nouvelle étape choisie (ou None)."""
    if not modifiable:
        st.html('<div class="bg-etapes">' + "".join(f'<span class="{"on" if e == courante else ""}">{ui._esc(e)}</span>'
                                                    for e in etapes) + "</div>")
        return None
    with st.container(key="bg_etapes", width="content"):
        choix = st.segmented_control("Étape", etapes, default=courante if courante in etapes else None,
                                     key=f"bg_etape_{cle}_{courante}", label_visibility="collapsed")
    return choix if choix and choix != courante else None


# ------------------------------------------------------------------ filtres et regroupements (logique pure)
Filtre = tuple[str, str, Callable[[dict], bool]]       # (libellé, groupe, prédicat)


def filtrer(lignes: list[dict], q: str, champs: Iterable[str], filtres: list[Filtre], actifs: Iterable[str]) -> list[dict]:
    """Recherche plein texte (sans accents) + filtres : « OU » dans un même groupe, « ET » entre groupes."""
    nq = _norm(q)
    champs = tuple(champs)
    actifs = set(actifs or [])
    groupes: dict[str, list[Callable]] = {}
    for lib, grp, fn in filtres:
        if lib in actifs:
            groupes.setdefault(grp, []).append(fn)
    out = []
    for r in lignes:
        if nq and not any(nq in _norm(r.get(c)) for c in champs):
            continue
        if all(any(fn(r) for fn in fns) for fns in groupes.values()):
            out.append(r)
    return out


def regrouper(lignes: list[dict], champ: str, ordre: list[str] | None = None) -> list[tuple[str, list[dict]]]:
    """Groupes dans l'ordre donné (étapes), puis les autres valeurs par ordre alphabétique ; « Non renseigné » en dernier."""
    g: dict[str, list[dict]] = {}
    for r in lignes:
        v = r.get(champ)
        g.setdefault(str(v) if v not in (None, "", "—") else "Non renseigné", []).append(r)
    cles = [k for k in (ordre or []) if k in g] + sorted(k for k in g if k not in (ordre or []) and k != "Non renseigné")
    if "Non renseigné" in g:
        cles.append("Non renseigné")
    return [(k, g[k]) for k in cles]


# ------------------------------------------------------------------ vue kanban / liste
def _carte_html(c: dict) -> str:
    av = c.get("initiales")
    avatar = (f'<span class="av" style="background:{c.get("couleur_avatar") or couleur_nom(c.get("titre"))}">'
              f'{ui._esc(av)}</span>') if av else ""
    lignes = "".join(f"<div>{ui._esc(l)}</div>" for l in c.get("lignes", []) if l)
    prog = c.get("progression")
    barre = (f'<div class="pb"><i style="width:{max(0, min(100, float(prog))):.0f}%"></i></div>'
             f'<div class="pc">{float(prog):.0f} %</div>') if prog is not None else ""
    tags = "".join(f'<span style="background:{fond};color:{txt}">{ui._esc(t)}</span>'
                   for t, fond, txt in c.get("etiquettes", []))
    return (f'<div class="bg-kc"><div class="h">{avatar}<div><b>{ui._esc(c.get("titre"))}</b>'
            f'<small>{ui._esc(c.get("sous_titre") or "")}</small></div></div><div class="l">{lignes}</div>{barre}'
            + (f'<div class="tg">{tags}</div>' if tags else "") + "</div>")


def _carte_kanban(cle: str, r: dict, carte: Callable[[dict], dict], n: int) -> None:
    c = carte(r)
    with st.container(key=f"bg_k_{cle}_{n}"):
        st.html(f'<style>.st-key-bg_k_{cle}_{n}{{--k:{c.get("couleur", "#c8d0e4")}}}</style>' + _carte_html(c))
        if st.button("Ouvrir", key=f"bg_ko_{cle}_{r['_id']}_{n}", icon=":material/open_in_new:", type="tertiary"):
            ouvrir(cle, r["_id"])


def vue_liste(cle: str, lignes: list[dict], colonnes: dict, *, recherche: Iterable[str],
              filtres: list[Filtre] | None = None, regroupements: dict[str, tuple[str, list[str] | None]] | None = None,
              carte: Callable[[dict], dict] | None = None, vues_sup: dict[str, Callable[[list[dict]], None]] | None = None,
              vue_defaut: str = "Kanban", regroupement_defaut: str | None = None, nom: str = "enregistrement",
              nom_pluriel: str | None = None, couleurs_groupes: dict[str, str] | None = None) -> None:
    """Vue d'ensemble d'une liste : recherche, filtres, « Regrouper par », bascule Kanban / Liste (/ Carte…).

    `lignes` : dictionnaires avec une clé « _id ». « Ouvrir » (kanban) ou un clic sur une ligne (liste) ouvre la fiche
    (voir fiche_ouverte / ouvrir / fermer)."""
    filtres = filtres or []
    regroupements = regroupements or {}
    nom_pluriel = nom_pluriel or nom + "s"
    vues = (["Kanban"] if carte else []) + ["Liste"] + list(vues_sup or {})
    icones = {"Kanban": ":material/view_kanban:", "Liste": ":material/view_list:", "Carte": ":material/map:"}
    gen = st.session_state.get(f"bg_gen_{cle}", 0)
    with st.container(horizontal=True, key=f"bg_cp_{cle}", gap="small", vertical_alignment="center"):
        q = st.text_input("Rechercher", placeholder=f"Rechercher…", key=f"{cle}_q", label_visibility="collapsed",
                          width=260, icon=":material/search:")
        actifs = st.pills("Filtres", [f[0] for f in filtres], selection_mode="multi", key=f"{cle}_filtres",
                          label_visibility="collapsed") if filtres else []
        options_g = ["Sans regroupement"] + list(regroupements)
        grp = st.selectbox("Regrouper par", options_g, key=f"{cle}_grp", label_visibility="collapsed", width=210,
                           index=options_g.index(regroupement_defaut) if regroupement_defaut in options_g else 0,
                           format_func=lambda g: g if g == "Sans regroupement" else f"Regrouper par : {g}")
        vue = st.segmented_control("Vue", vues, key=f"{cle}_vue", label_visibility="collapsed",
                                   default=vue_defaut if vue_defaut in vues else vues[0],
                                   format_func=lambda v: f"{icones.get(v, '')} {v}".strip()) or vues[0]
    res = filtrer(lignes, q, recherche, filtres, actifs)
    st.html(f'<div class="bg-compte">{len(res)} {nom if len(res) <= 1 else nom_pluriel}'
            + (f" sur {len(lignes)}" if len(res) != len(lignes) else "") + "</div>")
    if not res:
        st.info("Aucun résultat : modifiez la recherche ou retirez un filtre.")
        return
    champ, ordre = regroupements.get(grp, (None, None)) if grp != "Sans regroupement" else (None, None)
    groupes = regrouper(res, champ, ordre) if champ else [("", res)]

    if vue in (vues_sup or {}):
        vues_sup[vue](res)
        return

    if vue == "Kanban" and carte:
        limite = st.session_state.get(f"bg_lim_{cle}", 60)
        n = 0
        if champ:
            par_rangee = min(len(groupes), 4)
            for debut in range(0, len(groupes), par_rangee):
                cols = st.columns(par_rangee, gap="small")
                for col, (titre, rs) in zip(cols, groupes[debut:debut + par_rangee]):
                    with col:
                        teinte = (couleurs_groupes or {}).get(titre, "#c8d0e4")
                        st.html(f'<div class="bg-colonne" style="--k:{teinte}">{ui._esc(titre)}<span>{len(rs)}</span></div>')
                        for r in rs[:limite]:
                            _carte_kanban(cle, r, carte, n)
                            n += 1
                        if len(rs) > limite:
                            st.caption(f"… et {len(rs) - limite} autre(s). Utilisez la recherche ou la vue Liste.")
        else:
            cols = st.columns(3, gap="small")
            for k, r in enumerate(res[:limite]):
                with cols[k % 3]:
                    _carte_kanban(cle, r, carte, n)
                    n += 1
            if len(res) > limite and st.button(f"Afficher {min(60, len(res) - limite)} de plus", key=f"bg_plus_{cle}"):
                st.session_state[f"bg_lim_{cle}"] = limite + 60
                st.rerun()
        return

    for k, (titre, rs) in enumerate(groupes):
        if champ:
            st.html(f'<div class="bg-groupe">{ui._esc(titre)} <span>{len(rs)}</span></div>')
        i = ui.tableau(rs, colonnes, key=f"bg_tab_{cle}_{gen}_{k}", selection=True)
        if i is not None:
            ouvrir(cle, rs[i]["_id"])
    st.caption("Cliquez sur une ligne pour ouvrir la fiche.")


# ------------------------------------------------------------------ fil d'activité (chatter)
LIBELLES = {
    "name": "Nom", "status": "État", "progress": "Avancement", "deadline": "Échéance", "client": "Client",
    "location": "Lieu", "latitude": "GPS", "longitude": "GPS", "currency": "Monnaie", "phone": "Téléphone",
    "email": "E-mail", "address": "Adresse", "roles": "Rôles", "archived": "Archivé", "registration": "RCCM",
    "code": "Code", "date": "Date", "due": "Échéance", "notes": "Notes", "number": "Numéro", "project": "Chantier",
    "label": "Libellé", "category": "Catégorie",
}
MONTANTS = {"budget", "amount", "paid", "lines", "price", "total"}


def _valeur(v) -> str:
    if v is None or v == "":
        return "vide"
    if isinstance(v, bool):
        return "oui" if v else "non"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)[:60]
    t = str(v)
    return t if len(t) <= 60 else t[:57] + "…"


def _dict(v) -> dict:
    """Valeur JSON du journal : dict en mémoire, texte JSON quand elle vient d'une requête SQL brute."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


def _changements(avant: dict | None, apres: dict | None) -> list[str]:
    avant, apres = _dict(avant), _dict(apres)
    vus, out = set(), []
    for k, v in apres.items():
        if k in ("id", "longitude") or avant.get(k) == v:
            continue
        lib = LIBELLES.get(k, k)
        if lib in vus:
            continue
        vus.add(lib)
        if k in MONTANTS:
            out.append(f"<b>{ui._esc(lib if k in LIBELLES else 'Montants')}</b> modifiés")
        else:
            out.append(f"<b>{ui._esc(lib)}</b> : {ui._esc(_valeur(avant.get(k)))} → {ui._esc(_valeur(v))}")
    return out[:6]


def historique(objet: str, objet_id, limite: int = 40) -> list[dict]:
    return db.requete("select quand, user_nom, action, resume, avant, apres from audit "
                      "where objet = :o and objet_id = :i order by id desc limit " + str(int(limite)),
                      o=objet, i=str(objet_id))


def fil_activite(objet: str, objet_id, peut_noter: bool = True, titre: str = "Fil d’activité") -> None:
    """Historique de la fiche (créations, modifications, notes) et saisie d'une note interne."""
    with st.container(key="bg_chatter"):
        st.html(f'<div class="bg-chat-t">{ui._esc(titre)}</div>')
        if peut_noter:
            with st.form(f"bg_note_{objet}_{objet_id}", clear_on_submit=True, border=False):
                texte = st.text_area("Note interne", placeholder="Écrire une note pour l’équipe (visible dans l’historique)…",
                                     label_visibility="collapsed", height=80, max_chars=2000)
                if st.form_submit_button("Enregistrer la note", icon=":material/edit_note:"):
                    if texte.strip():
                        db.journaliser("Note", texte.strip(), objet, str(objet_id))
                        st.rerun()
                    else:
                        st.warning("La note est vide.")
        lignes = historique(objet, objet_id)
        if not lignes:
            st.caption("Aucune activité enregistrée pour cette fiche.")
            return
        items = []
        for r in lignes:
            action = r["action"] or ""
            cls = "note" if action == "Note" else "cre" if action == "Création" else "sup" if action == "Suppression" else ""
            quand = r["quand"]
            if isinstance(quand, str):
                try:
                    quand = dt.datetime.fromisoformat(quand)
                except ValueError:
                    quand = None
            q = quand.strftime("%d/%m/%Y %H:%M") if isinstance(quand, dt.datetime) else ""
            nom = r["user_nom"] or "Système"
            corps = (f'<div class="t note">{ui._esc(r["resume"])}</div>' if action == "Note"
                     else f'<div class="t">{ui._esc(r["resume"])}</div>')
            if action == "Modification":
                ch = _changements(r.get("avant"), r.get("apres"))
                if ch:
                    corps += "<ul>" + "".join(f"<li>{c}</li>" for c in ch) + "</ul>"
            items.append(f'<div class="bg-msg"><span class="bg-avatar" style="background:{couleur_nom(nom)}">'
                         f'{ui._esc(initiales(nom))}</span><div class="c"><div class="q"><b>{ui._esc(nom)}</b> · {q}'
                         f'<span class="a {cls}">{ui._esc(action)}</span></div>{corps}</div></div>')
        st.html("".join(items))
