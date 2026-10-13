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
/* ===== Jetons de couleur (charte Bâti Gestion) ===== */
:root{--bg-navy:#112740;--bg-navy-2:#183653;--ambre:#efa63a;--ambre-clair:#ffb347;--bord:#dce4ed;--texte:#172b43;--doux:#5b6e83;--fond:#f2f5f8}

/* ===== Mise en page et apparition douce ===== */
.block-container{padding-top:2rem;padding-bottom:3rem;max-width:1400px}
@keyframes bgApparition{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
[data-testid="stMainBlockContainer"]{animation:bgApparition .4s cubic-bezier(.2,.7,.2,1) both}
@media (prefers-reduced-motion: reduce){[data-testid="stMainBlockContainer"]{animation:none}*{transition:none !important}}

/* ===== Titres : hiérarchie et filet ambre ===== */
h1{font-size:2.05rem;font-weight:800;letter-spacing:-.6px;color:var(--bg-navy);margin-bottom:.15rem;display:inline-block;padding-bottom:.4rem;background:linear-gradient(var(--ambre),var(--ambre)) no-repeat left bottom / 44px 4px}
h2,h3{color:var(--bg-navy-2);letter-spacing:-.3px}
.bg-sous{font-size:1rem;color:var(--doux);margin:.85rem 0 1.5rem 0;max-width:820px;line-height:1.5}

/* ===== Barre latérale : sections en capitales, liens arrondis ===== */
[data-testid="stNavSectionHeader"]{padding:0 14px;margin:1.1rem 0 .25rem 0 !important}
[data-testid="stNavSectionHeader"] p,[data-testid="stNavSectionHeader"] span{font-size:.7rem !important;font-weight:700 !important;letter-spacing:.12em;text-transform:uppercase;color:#7f95ab !important}
[data-testid="stSidebarNavLink"]{border-radius:10px;margin:2px 8px;transition:background .15s ease,color .15s ease}
[data-testid="stSidebarNavLink"]:hover{background:rgba(255,179,71,.10)}
[data-testid="stSidebarNavLink"][aria-current="page"]{background:rgba(255,179,71,.14);box-shadow:inset 3px 0 0 var(--ambre-clair)}
[data-testid="stSidebar"] hr{border-color:#29445f;opacity:.7}

/* ===== Onglets : pastille ambre sous l'onglet actif ===== */
[data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--bord)}
[data-baseweb="tab"]{background:transparent;border-radius:10px 10px 0 0;padding:.6rem 1.05rem;color:var(--doux);font-weight:600;transition:color .15s ease,background .15s ease}
[data-baseweb="tab"]:hover{color:var(--bg-navy);background:rgba(17,39,64,.04)}
[data-baseweb="tab"][aria-selected="true"]{color:var(--bg-navy);font-weight:700;box-shadow:inset 0 -3px 0 var(--ambre)}
[data-baseweb="tab-highlight"]{background:var(--ambre) !important;height:3px !important}
[data-baseweb="tab-border"]{display:none}

/* ===== Boutons : principal bleu nuit avec relief au survol ===== */
[data-testid^="stBaseButton"]{border-radius:10px;font-weight:600;transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,transform .18s ease}
[data-testid="stBaseButton-primary"]{background:var(--bg-navy-2);border-color:var(--bg-navy-2);color:#fff;box-shadow:0 1px 2px rgba(17,39,64,.18)}
[data-testid="stBaseButton-primary"]:hover{background:var(--bg-navy);border-color:var(--bg-navy);box-shadow:0 6px 18px rgba(17,39,64,.22);transform:translateY(-1px)}
[data-testid="stBaseButton-primary"]:active{transform:translateY(0)}
[data-testid="stBaseButton-secondary"]{background:#fff;border-color:#c9d4e0;color:var(--bg-navy-2)}
[data-testid="stBaseButton-secondary"]:hover{border-color:var(--bg-navy-2);background:#f5f8fb;box-shadow:0 2px 8px rgba(17,39,64,.08)}
[data-testid^="stBaseButton"]:disabled{opacity:.45;transform:none}
:focus-visible{outline:2px solid var(--ambre) !important;outline-offset:2px}

/* ===== Champs de saisie ===== */
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"]{border-radius:10px !important;border-color:#c9d4e0 !important;background:#fff}
[data-baseweb="input"]:focus-within,[data-baseweb="select"]>div:focus-within,[data-baseweb="textarea"]:focus-within{border-color:var(--bg-navy-2) !important;box-shadow:0 0 0 3px rgba(24,54,83,.12)}

/* ===== Cartes : métriques, formulaires, blocs repliables ===== */
[data-testid="stMetric"]{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(17,39,64,.04),0 6px 18px rgba(17,39,64,.05);transition:transform .2s ease,box-shadow .2s ease}
[data-testid="stMetric"]:hover{transform:translateY(-2px);box-shadow:0 2px 4px rgba(17,39,64,.06),0 12px 26px rgba(17,39,64,.09)}
[data-testid="stMetricLabel"]{color:var(--doux);font-weight:600}
[data-testid="stMetricValue"]{font-size:1.45rem;letter-spacing:-.5px;color:var(--bg-navy)}
[data-testid="stForm"]{border:1px solid var(--bord);border-radius:14px;background:#fff;padding:1rem 1.15rem;box-shadow:0 1px 2px rgba(17,39,64,.04)}
[data-testid="stExpander"]{border:1px solid var(--bord);border-radius:14px;background:#fff;overflow:hidden;box-shadow:0 1px 2px rgba(17,39,64,.03)}
[data-testid="stExpander"] summary{font-weight:600;color:var(--bg-navy-2)}

/* ===== Tableaux et messages ===== */
[data-testid="stDataFrame"]{border:1px solid var(--bord);border-radius:14px;overflow:hidden;background:#fff;box-shadow:0 1px 2px rgba(17,39,64,.04),0 6px 18px rgba(17,39,64,.04)}
[data-testid="stDataFrame"] [role="columnheader"]{background:#eef3f8;color:var(--texte);font-weight:700}
[data-testid="stAlert"]{border-radius:12px;border:1px solid var(--bord);box-shadow:0 1px 2px rgba(17,39,64,.03)}
[data-testid="stAlert"] p{font-size:.95rem}

/* ===== Repères de statut (chiffres clés et étiquettes) ===== */
.bg-tag{display:inline-block;background:#fff;border:1px solid var(--bord);border-radius:999px;padding:5px 12px;font-size:.84rem;color:var(--texte);margin:2px 6px 2px 0;box-shadow:0 1px 2px rgba(17,39,64,.04)}
.bg-tag b{color:var(--bg-navy)}
.bg-tag.ok{background:#e6f6ee;border-color:#bfe6cf;color:#176846}
.bg-tag.alerte{background:#fdeeec;border-color:#f3c4bf;color:#a62d25}
.bg-carte{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:16px 18px;height:100%;box-shadow:0 1px 2px rgba(17,39,64,.04),0 6px 18px rgba(17,39,64,.05)}
.bg-carte.accent{border-top:4px solid var(--ambre)}
.bg-carte .t{font-size:.9rem;color:var(--texte);margin-bottom:.35rem;font-weight:600}
.bg-carte .n{font-size:1.7rem;font-weight:800;letter-spacing:-1px;color:var(--bg-navy)}
.bg-carte .m{color:var(--doux);font-size:.85rem}
.bg-montants{font-variant-numeric:tabular-nums;line-height:1.55}
.bg-montants b{font-size:1.25rem;letter-spacing:-.3px}

/* ===== Petits écrans : marges de 16 px, pas de défilement horizontal ===== */
@media (max-width: 760px){
 [data-testid="stMainBlockContainer"].block-container{padding-left:16px;padding-right:16px;padding-top:4.8rem}
 h1{font-size:1.6rem}
 [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
 [data-testid="stMetricValue"]{font-size:1.2rem}
}
</style>
"""
STYLE_CONNEXION = """
<style>
[data-testid="stAppViewContainer"]{background:
 linear-gradient(90deg, rgba(17,39,64,.05) 1px, transparent 1px) 0 0/28px 28px,
 linear-gradient(rgba(17,39,64,.05) 1px, transparent 1px) 0 0/28px 28px, #f2f5f8}
[data-testid="stForm"]{background:#fff;border:1px solid #dce4ed;border-top:4px solid #efa63a;border-radius:10px;padding:8px 6px}
</style>
"""


def appliquer_style(connexion: bool = False) -> None:
    st.html(STYLE + (STYLE_CONNEXION if connexion else ""))


def en_tete(titre: str, sous_titre: str = "") -> None:
    st.title(titre)
    if sous_titre:
        st.html(f'<p class="bg-sous">{_esc(sous_titre)}</p>')
    flash()


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


def montants_html(totaux: dict[str, int]) -> str:
    """Totaux séparés par monnaie, sans conversion."""
    return '<div class="bg-montants">' + "<br>".join(
        f"<b>{_esc(R.money(totaux.get(c, 0), c))}</b>" for c in R.CURRENCIES) + "</div>"


def montants_texte(totaux: dict[str, int], seulement_non_nuls: bool = False) -> str:
    parts = [R.money(totaux.get(c, 0), c) for c in R.CURRENCIES if not seulement_non_nuls or totaux.get(c)]
    return " · ".join(parts) or R.money(0, R.company().get("defaultCurrency", "USD"))


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
