"""Identifiants, mots de passe, sessions et droits d'accès par rôle.

Les mots de passe ne sont jamais stockés en clair : PBKDF2-SHA256 avec sel aléatoire
(bibliothèque standard Python). Cinq échecs de connexion bloquent le compte 15 minutes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets

import sqlalchemy as sa
import streamlit as st

import db

ROLES = {
    "admin": "Direction générale (administrateur)",
    "finance": "Finance et comptabilité",
    "rh": "Ressources humaines et paie",
    "chantier": "Conducteur de travaux",
    "lecteur": "Consultation",
}
DESCRIPTION_ROLES = {
    "admin": "Tout voir et tout modifier ; crée les comptes ; valide les justificatifs.",
    "finance": "Devis, factures, dépenses, caisse, trésorerie, tiers, achats et comptabilité ; valide les justificatifs.",
    "rh": "Personnel, salaires, pointages et paie. Seuls la direction et les RH voient les salaires.",
    "chantier": "Chantiers, dépenses de chantier et justificatifs, pointages, achats, stocks, matériel.",
    "lecteur": "Consulte les chantiers, les comptes et les rapports, sans rien modifier ni voir les salaires.",
}

# Modules de l'application et droits : "w" = consulter et modifier, "r" = consulter seulement.
MODULES = ["accueil", "recherche", "rapports", "chantiers", "tiers", "comptes", "commercial", "depenses",
           "justificatifs", "validation_pieces", "tresorerie", "personnel", "pointage", "paie", "achats",
           "charroi", "projets", "comptabilite", "documents", "societe", "reprise", "utilisateurs",
           "sauvegarde", "audit"]
DROITS = {
    "admin": {m: "w" for m in MODULES},
    "finance": {"accueil": "r", "recherche": "r", "rapports": "r", "chantiers": "r", "tiers": "w",
                "comptes": "w", "commercial": "w", "depenses": "w", "justificatifs": "w",
                "validation_pieces": "w", "tresorerie": "w", "achats": "w", "charroi": "r", "projets": "r",
                "comptabilite": "w", "documents": "w", "societe": "r", "reprise": "w"},
    "rh": {"accueil": "r", "recherche": "r", "chantiers": "r", "personnel": "w", "pointage": "w", "paie": "w",
           "documents": "r", "societe": "r"},
    "chantier": {"accueil": "r", "recherche": "r", "chantiers": "w", "tiers": "r", "depenses": "w",
                 "justificatifs": "w", "personnel": "r", "pointage": "w", "achats": "w", "charroi": "w",
                 "projets": "w", "documents": "r", "societe": "r"},
    "lecteur": {"accueil": "r", "recherche": "r", "rapports": "r", "chantiers": "r", "tiers": "r", "comptes": "r",
                "commercial": "r", "depenses": "r", "justificatifs": "r", "tresorerie": "r", "personnel": "r",
                "achats": "r", "charroi": "r", "projets": "r", "comptabilite": "r", "documents": "r",
                "societe": "r"},
}

ITERATIONS = 260_000
DUREE_SESSION = dt.timedelta(hours=12)
ECHECS_MAX = 5
DUREE_BLOCAGE = dt.timedelta(minutes=15)
MDP_INITIAL_PAR_DEFAUT = "changez-moi"


# ----------------------------------------------------------------- mots de passe
def hacher(mdp: str) -> str:
    sel = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${sel.hex()}${h.hex()}"


def verifier(mdp: str, stocke: str) -> bool:
    try:
        algo, it, sel, h = stocke.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), bytes.fromhex(sel), int(it))
        return algo == "pbkdf2_sha256" and hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def mdp_temporaire(longueur: int = 10) -> str:
    """Mot de passe lisible (sans 0/O ni 1/l/I), avec au moins une lettre et un chiffre."""
    lettres = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    chiffres = "23456789"
    while True:
        m = "".join(secrets.choice(lettres + chiffres) for _ in range(longueur))
        if any(c in chiffres for c in m) and any(c in lettres for c in m):
            return m


def probleme_mdp(mdp: str) -> str | None:
    if len(mdp) < 8:
        return "Le mot de passe doit contenir au moins 8 caractères."
    if not any(c.isdigit() for c in mdp) or not any(c.isalpha() for c in mdp):
        return "Le mot de passe doit contenir au moins une lettre et un chiffre."
    if mdp.lower() in {MDP_INITIAL_PAR_DEFAUT, "password", "motdepasse", "12345678", "mydestiny1"}:
        return "Ce mot de passe est trop facile à deviner."
    return None


# ------------------------------------------------------------------- comptes
def secret(cle: str, defaut: str | None = None) -> str | None:
    try:
        return st.secrets[cle]
    except Exception:  # noqa: BLE001
        return os.environ.get(cle, defaut)


def assurer_admin_initial() -> None:
    """À la toute première ouverture, crée le compte administrateur (direction générale)."""
    u = db.users
    with db.moteur().begin() as c:
        if c.execute(sa.select(sa.func.count()).select_from(u)).scalar():
            return
        ident = (secret("ADMIN_IDENTIFIANT", "admin") or "admin").strip().lower()
        mdp = secret("ADMIN_MDP_INITIAL") or MDP_INITIAL_PAR_DEFAUT
        c.execute(u.insert().values(identifiant=ident, nom="Administrateur", role="admin", telephone="",
                                    mdp_hash=hacher(mdp), doit_changer_mdp=True, actif=True, echecs=0,
                                    version_session=0, cree_le=db.maintenant()))


def admin_par_defaut_actif() -> bool:
    """Vrai tant que le compte initial n'a pas remplacé le mot de passe par défaut."""
    if secret("ADMIN_MDP_INITIAL"):
        return False
    rows = db.requete("select mdp_hash from users where role = 'admin' and doit_changer_mdp = :v", v=True)
    return any(verifier(MDP_INITIAL_PAR_DEFAUT, r["mdp_hash"]) for r in rows)


def creer_utilisateur(identifiant: str, nom: str, role: str, telephone: str = "") -> str:
    """Crée le compte et renvoie le mot de passe provisoire à communiquer à l'usager."""
    mdp = mdp_temporaire()
    with db.transaction(f"Création du compte {identifiant}") as t:
        t.inserer("users", {"identifiant": identifiant.strip().lower(), "nom": nom.strip(), "role": role,
                            "telephone": telephone.strip(), "mdp_hash": hacher(mdp), "doit_changer_mdp": True,
                            "actif": True, "echecs": 0, "version_session": 0, "cree_le": db.maintenant()})
    return mdp


def reinitialiser_mdp(uid: int) -> str:
    mdp = mdp_temporaire()
    u = db.un("users", uid)
    with db.transaction(f"Réinitialisation du mot de passe de {u['identifiant']}") as t:
        t.maj("users", uid, {"mdp_hash": hacher(mdp), "doit_changer_mdp": True, "echecs": 0,
                             "bloque_jusqua": None, "version_session": int(u["version_session"] or 0) + 1})
    return mdp


def mdp_correct(uid: int, mdp: str) -> bool:
    u = db.un("users", uid)
    return bool(u) and verifier(mdp, u["mdp_hash"])


def changer_mdp(uid: int, nouveau: str) -> None:
    with db.transaction("Changement de mot de passe") as t:
        t.maj("users", uid, {"mdp_hash": hacher(nouveau), "doit_changer_mdp": False})


def connecter(identifiant: str, mdp: str) -> tuple[dict | None, str | None]:
    u = db.users
    with db.moteur().begin() as c:
        row = c.execute(sa.select(u).where(u.c.identifiant == identifiant.strip().lower())).mappings().first()
        if row is None:
            verifier(mdp, hacher("x"))  # même durée de calcul : ne révèle pas si le compte existe
            return None, "Identifiant ou mot de passe incorrect."
        if not row["actif"]:
            return None, "Ce compte est désactivé. Contactez la direction."
        if row["bloque_jusqua"] and row["bloque_jusqua"] > db.maintenant():
            reste = max(1, -(-int((row["bloque_jusqua"] - db.maintenant()).total_seconds()) // 60))
            return None, f"Trop de tentatives : compte bloqué encore {reste} minute(s)."
        if not verifier(mdp, row["mdp_hash"]):
            echecs = (row["echecs"] or 0) + 1
            vals = {"echecs": echecs}
            if echecs >= ECHECS_MAX:
                vals = {"echecs": 0, "bloque_jusqua": db.maintenant() + DUREE_BLOCAGE}
            c.execute(u.update().where(u.c.id == row["id"]).values(**vals))
            return None, "Identifiant ou mot de passe incorrect."
        c.execute(u.update().where(u.c.id == row["id"]).values(echecs=0, bloque_jusqua=None,
                                                               derniere_connexion=db.maintenant()))
        c.execute(db.audit.insert().values(quand=db.maintenant(), user_id=row["id"], user_nom=row["nom"],
                                           action="Connexion", objet="users", objet_id=str(row["id"]),
                                           resume=f"Connexion de {row['identifiant']}"))
        return {k: row[k] for k in ("id", "identifiant", "nom", "role", "doit_changer_mdp")}, None


# --------------------------------------------------------------------- session
# Le jeton de session, signé, est gardé dans l'adresse (?s=…) : actualiser la page ne déconnecte pas.
# Il expire après 12 h et devient invalide dès que l'usager se déconnecte.
def _cle_secrete() -> bytes:
    cle = secret("CLE_SECRETE")
    if cle:
        return cle.encode()
    with db.moteur().begin() as c:
        v = c.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == "cle_secrete")).scalar()
        if not v:
            v = secrets.token_hex(32)
            c.execute(db.settings.insert().values(cle="cle_secrete", valeur=v))
    return str(v).encode()


def _signer(texte: str) -> str:
    return hmac.new(_cle_secrete(), texte.encode(), hashlib.sha256).hexdigest()[:32]


def jeton(uid: int) -> str:
    version = int(db.un("users", uid)["version_session"] or 0)
    exp = int((dt.datetime.now() + DUREE_SESSION).timestamp())
    corps = f"{uid}.{version}.{exp}"
    return f"{corps}.{_signer(corps)}"


def depuis_jeton(texte: str) -> dict | None:
    try:
        uid, version, exp, sig = texte.split(".")
        if not hmac.compare_digest(sig, _signer(f"{uid}.{version}.{exp}")) or int(exp) < dt.datetime.now().timestamp():
            return None
        u = db.un("users", int(uid))
    except (ValueError, AttributeError, TypeError):
        return None
    if not u or not u["actif"] or int(u["version_session"] or 0) != int(version):
        return None
    return {k: u[k] for k in ("id", "identifiant", "nom", "role", "doit_changer_mdp")}


def utilisateur() -> dict | None:
    return st.session_state.get("utilisateur")


def ouvrir_session(u: dict) -> None:
    st.session_state["utilisateur"] = u
    st.session_state["jeton"] = jeton(u["id"])


def deconnecter() -> None:
    u = utilisateur()
    if u:  # invalide tous les jetons de cet usager, sur tous ses appareils
        with db.moteur().begin() as c:
            c.execute(sa.text("update users set version_session = coalesce(version_session, 0) + 1 where id = :i"),
                      {"i": u["id"]})
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear()


# --------------------------------------------------------------------- droits
def droit(module: str) -> str | None:
    role = (utilisateur() or {}).get("role")
    return DROITS.get(role, {}).get(module)


def voit(module: str) -> bool:
    return droit(module) in ("r", "w")


def modifie(module: str) -> bool:
    return droit(module) == "w"


def exiger(module: str) -> None:
    """À placer en tête de page : arrête l'affichage si le rôle n'a pas accès au module."""
    if not voit(module):
        st.error("Votre rôle ne donne pas accès à cette rubrique.")
        st.stop()
