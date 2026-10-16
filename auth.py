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
           "sauvegarde", "audit", "imports",
           "approbation_n1", "approbation_n2", "approbation_n3", "approbation_dg",
           "demandes_achat", "approbation_chantier", "chiffrage_achats", "approbation_coordonnateur"]
DROITS = {
    "admin": {m: "w" for m in MODULES},
    "finance": {"accueil": "r", "recherche": "r", "rapports": "r", "chantiers": "r", "tiers": "w",
                "comptes": "w", "commercial": "w", "depenses": "w", "justificatifs": "w",
                "validation_pieces": "w", "tresorerie": "w", "achats": "w", "charroi": "r", "projets": "r",
                "comptabilite": "w", "documents": "w", "societe": "r", "reprise": "w", "imports": "w",
                "approbation_n2": "w", "approbation_n3": "w", "demandes_achat": "r", "chiffrage_achats": "w"},
    "rh": {"accueil": "r", "recherche": "r", "chantiers": "r", "personnel": "w", "pointage": "w", "paie": "w",
           "documents": "r", "societe": "r", "imports": "w"},
    "chantier": {"accueil": "r", "recherche": "r", "chantiers": "w", "tiers": "r", "depenses": "w",
                 "justificatifs": "w", "personnel": "r", "pointage": "w", "achats": "w", "charroi": "w",
                 "projets": "w", "documents": "r", "societe": "r", "imports": "w", "approbation_n1": "w",
                 "demandes_achat": "w", "approbation_chantier": "w"},
    "lecteur": {"accueil": "r", "recherche": "r", "rapports": "r", "chantiers": "r", "tiers": "r", "comptes": "r",
                "commercial": "r", "depenses": "r", "justificatifs": "r", "tresorerie": "r", "personnel": "r",
                "achats": "r", "charroi": "r", "projets": "r", "comptabilite": "r", "documents": "r",
                "societe": "r", "imports": "r", "demandes_achat": "r"},
}

# Libellés des rubriques (affichés dans la gestion des accès).
MODULE_LABELS = {
    "accueil": "Vue d’ensemble", "recherche": "Recherche globale", "rapports": "Rapports et alertes",
    "chantiers": "Chantiers", "tiers": "Clients et fournisseurs", "comptes": "Comptes tiers",
    "commercial": "Devis, factures, prospects", "depenses": "Dépenses et circuit financier V7",
    "justificatifs": "Justificatifs", "validation_pieces": "Validation des pièces", "tresorerie": "Trésorerie et journal de caisse",
    "personnel": "Personnel et congés", "pointage": "Pointage et présence Kobo", "paie": "Paie (salaires)",
    "achats": "Achats et stocks", "charroi": "Matériel et charroi", "projets": "DQE, situations, qualité",
    "comptabilite": "Comptabilité et fiscalité", "documents": "Registres, garanties, tâches", "societe": "Société",
    "reprise": "Reprise historique", "utilisateurs": "Utilisateurs", "sauvegarde": "Paramètres et sauvegarde",
    "audit": "Journal d’audit", "imports": "Centre d’import",
    "approbation_n1": "Approbation N1 (contrôle chantier, dépenses)",
    "approbation_n2": "Approbation N2 (finance, rapprochement des lots)",
    "approbation_n3": "Approbation N3 (autorisation de paiement)",
    "approbation_dg": "Approbation DG (budgets, révisions, délégations, activation)",
    "demandes_achat": "Demandes d’achat matériel et matériaux",
    "approbation_chantier": "Validation du besoin (chef de chantier, directeur de projet)",
    "chiffrage_achats": "Chiffrage des achats et commandes groupées",
    "approbation_coordonnateur": "Validation coordonnateur de projet (demandes d’achat)",
}
NIVEAUX = {"w": "Modification", "r": "Consultation", None: "Aucun"}

ITERATIONS = 260_000
DUREE_SESSION = dt.timedelta(hours=12)
ECHECS_MAX = 5
DUREE_BLOCAGE = dt.timedelta(minutes=15)
MDP_INITIAL_PAR_DEFAUT = "changez-moi"


# ----------------------------------------------------------------- postes et profils
# Un poste (profil) est un MODÈLE DE DÉPART : une famille de rôle technique (ROLES, qui fixe ce que les services
# autorisent), un jeu d'accès par rubrique et une description. Les accès réglés par l'administrateur pour une
# personne (droits_utilisateur:<id>) restent prioritaires sur le modèle, exactement comme avec les rôles.
_LECTURE = {"accueil": "r", "recherche": "r", "societe": "r", "documents": "r"}


def _avec(base: dict, **acces) -> dict:
    d = dict(base)
    d.update(acces)
    return {m: v for m, v in d.items() if v}


PROFILS_STANDARDS: dict[str, dict] = {
    "chef_equipe": dict(
        libelle="Chef d’équipe", role="chantier",
        description="Exprime les besoins de son équipe (demandes d’achat) et pointe le personnel.",
        droits=_avec(_LECTURE, chantiers="r", demandes_achat="w", pointage="w", achats="r")),
    "conducteur_travaux": dict(
        libelle="Conducteur de travaux", role="chantier",
        description="Chantiers, dépenses et justificatifs, pointage, demandes d’achat, réceptions ; contrôle N1.",
        droits=_avec(DROITS["chantier"], approbation_chantier=None)),
    "magasinier_chantier": dict(
        libelle="Magasinier chantier", role="chantier",
        description="Demandes d’achat du magasin de chantier, réceptions, stocks du chantier.",
        droits=_avec(_LECTURE, chantiers="r", achats="w", demandes_achat="w", imports="w")),
    "chef_chantier": dict(
        libelle="Chef de chantier", role="chantier",
        description="Valide le besoin des demandes d’achat de ses chantiers ; contrôle N1.",
        droits=dict(DROITS["chantier"])),
    "directeur_projet": dict(
        libelle="Directeur de projet", role="chantier",
        description="Valide le besoin des demandes d’achat de ses projets ; suivi DQE et rapports.",
        droits=_avec(DROITS["chantier"], rapports="r")),
    "coordonnateur_projet": dict(
        libelle="Coordonnateur de projet", role="chantier",
        description="Arbitre et valide les demandes d’achat chiffrées au-delà du seuil, sur son portefeuille.",
        droits=_avec(_LECTURE, chantiers="r", rapports="r", achats="r", projets="r", demandes_achat="r",
                     approbation_coordonnateur="w")),
    "acheteur": dict(
        libelle="Acheteur", role="finance",
        description="Chiffre les demandes (prix, fournisseur), passe les commandes groupées.",
        droits=_avec(_LECTURE, chantiers="r", tiers="w", comptes="r", achats="w", demandes_achat="r",
                     chiffrage_achats="w", imports="w")),
    "responsable_achats": dict(
        libelle="Responsable achats", role="finance",
        description="Comme l’acheteur, avec les rapports, les dépenses et le matériel en consultation.",
        droits=_avec(_LECTURE, chantiers="r", tiers="w", comptes="r", achats="w", demandes_achat="r",
                     chiffrage_achats="w", imports="w", rapports="r", depenses="r", charroi="r")),
    "magasinier_central": dict(
        libelle="Magasinier central / logistique", role="chantier",
        description="Dépôt central : réceptions, stocks, transferts vers les chantiers.",
        droits=_avec(_LECTURE, chantiers="r", achats="w", demandes_achat="r", imports="w")),
    "comptable": dict(
        libelle="Comptable fournisseurs", role="finance",
        description="Factures, comptes tiers, comptabilité ; contrôle N2. Sans chiffrage ni autorisation N3.",
        droits=_avec(DROITS["finance"], chiffrage_achats=None, approbation_n3=None)),
    "daf": dict(
        libelle="Directeur administratif et financier", role="finance",
        description="Finance et comptabilité ; contrôles N2 et N3. Sans chiffrage des achats.",
        droits=_avec(DROITS["finance"], chiffrage_achats=None)),
    "dg": dict(
        libelle="Directeur général", role="admin",
        description="Tous les accès (administrateur) ; approbation DG.",
        droits={m: "w" for m in MODULES}),
    "admin_erp": dict(
        libelle="Administrateur ERP", role="lecteur",
        description="Crée les comptes et les profils, règle les sauvegardes ; aucune approbation.",
        droits=_avec(_LECTURE, utilisateurs="w", sauvegarde="w", audit="r")),
}

# Séparation des tâches : un même profil ne cumule pas ces accès en modification.
INCOMPATIBILITES = [
    ("chiffrage_achats", "approbation_coordonnateur", "fixer les prix puis les approuver"),
    ("chiffrage_achats", "approbation_dg", "fixer les prix puis donner l’approbation finale"),
    ("utilisateurs", "chiffrage_achats", "s’attribuer des droits et passer les commandes"),
]


def incompatibilites(droits: dict) -> list[str]:
    """Combinaisons interdites présentes dans un jeu d'accès (messages lisibles)."""
    return [f"{MODULE_LABELS[a]} + {MODULE_LABELS[b]} : {raison}" for a, b, raison in INCOMPATIBILITES
            if (droits or {}).get(a) == "w" and (droits or {}).get(b) == "w"]


SENSIBLES_ADMIN = ("utilisateurs", "approbation_dg", "audit")


def _controle_sensible(auteur: dict, droits: dict) -> None:
    """Seule la direction générale (administrateur) accorde la gestion des comptes, l'approbation DG ou l'audit."""
    if auteur.get("role") != "admin" and any(droits.get(m) for m in SENSIBLES_ADMIN):
        raise ValueError("Seule la direction générale peut accorder la gestion des utilisateurs, l’approbation DG "
                         "ou le journal d’audit.")


def _normaliser_droits(droits: dict) -> dict:
    out = {}
    for m, v in (droits or {}).items():
        if m not in MODULES:
            raise ValueError(f"Rubrique inconnue : {m}.")
        if v in (None, "", "x"):
            continue
        if v not in ("r", "w"):
            raise ValueError(f"Niveau d’accès invalide pour {MODULE_LABELS[m]}.")
        if m.startswith("approbation_") and v == "r":
            continue  # une approbation s'accorde ou se retire
        out[m] = v
    return out


def _param(cle: str, tx=None):
    """Lit un paramètre, dans la transaction en cours si elle est fournie (pas de seconde connexion)."""
    if tx is not None:
        return tx.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == cle)).scalar()
    return db.parametre(cle)


def profils(actifs_seulement: bool = False, tx=None) -> dict[str, dict]:
    """Profils standards puis personnalisés : {code: {libelle, role, droits, description, standard, actif}}."""
    out = {k: {**v, "standard": True, "actif": True} for k, v in PROFILS_STANDARDS.items()}
    for k, v in (_param("profils_personnalises", tx) or {}).items():
        out[k] = {**v, "standard": False, "actif": v.get("actif", True)}
    return {k: v for k, v in out.items() if v["actif"] or not actifs_seulement}


CODE_PROFIL = r"[a-z][a-z0-9_]{2,39}"


def creer_profil(code: str, libelle: str, role: str, droits: dict, description: str = "") -> None:
    """Profil personnalisé bien défini, créé par un usager qui gère les utilisateurs."""
    import re
    auteur = utilisateur() or {}
    if not peut(auteur.get("droits"), "utilisateurs"):
        raise ValueError("Seul un gestionnaire des utilisateurs peut créer un profil.")
    code = (code or "").strip().lower()
    if not re.fullmatch(CODE_PROFIL, code):
        raise ValueError("Code du profil : 3 à 40 caractères, lettres minuscules, chiffres ou _ (commence par une lettre).")
    if code in profils():
        raise ValueError("Ce code de profil existe déjà.")
    if not (libelle or "").strip():
        raise ValueError("Libellé du profil obligatoire.")
    if role not in ROLES or role == "admin":
        raise ValueError("Famille de rôle invalide (l’administrateur garde tous les accès : profil réservé).")
    d = _normaliser_droits(droits)
    if not d:
        raise ValueError("Un profil doit donner au moins un accès.")
    _controle_sensible(auteur, d)
    if conflits := incompatibilites(d):
        raise ValueError("Accès incompatibles (séparation des tâches) : " + " ; ".join(conflits))
    with db.transaction(f"Création du profil {code}") as t:
        tous = dict(t.cx.execute(sa.select(db.settings.c.valeur).where(
            db.settings.c.cle == "profils_personnalises")).scalar() or {})
        if code in tous:
            raise ValueError("Ce code de profil existe déjà.")
        tous[code] = {"libelle": libelle.strip(), "role": role, "droits": d, "description": (description or "").strip(),
                      "actif": True, "cree_par": auteur.get("identifiant", ""), "cree_le": db.maintenant().isoformat()}
        t.parametre("profils_personnalises", tous, resume=f"Création du profil {code} ({libelle.strip()})")


def modifier_profil(code: str, libelle: str, droits: dict, description: str, actif: bool) -> None:
    """Modifie un profil personnalisé ; les profils standards ne se modifient pas (créer un profil dérivé)."""
    auteur = utilisateur() or {}
    if not peut(auteur.get("droits"), "utilisateurs"):
        raise ValueError("Seul un gestionnaire des utilisateurs peut modifier un profil.")
    d = _normaliser_droits(droits)
    if not d:
        raise ValueError("Un profil doit donner au moins un accès.")
    _controle_sensible(auteur, d)
    if conflits := incompatibilites(d):
        raise ValueError("Accès incompatibles (séparation des tâches) : " + " ; ".join(conflits))
    with db.transaction(f"Modification du profil {code}") as t:
        tous = dict(t.cx.execute(sa.select(db.settings.c.valeur).where(
            db.settings.c.cle == "profils_personnalises")).scalar() or {})
        if code not in tous:
            raise ValueError("Profil personnalisé introuvable (les profils standards ne se modifient pas).")
        if not (libelle or "").strip():
            raise ValueError("Libellé du profil obligatoire.")
        tous[code] = {**tous[code], "libelle": libelle.strip(), "droits": d, "description": (description or "").strip(),
                      "actif": bool(actif)}
        t.parametre("profils_personnalises", tous, resume=f"Modification du profil {code}")
        # Les usagers de ce profil reprennent le nouveau modèle à leur prochaine action : sessions fermées.
        for cle, valeur in t.cx.execute(sa.select(db.settings.c.cle, db.settings.c.valeur).where(
                db.settings.c.cle.like("poste_utilisateur:%"))).all():
            if valeur == code:
                t.cx.execute(sa.text("update users set version_session = coalesce(version_session, 0) + 1 where id = :i"),
                             {"i": int(cle.split(":")[1])})


def enregistrer_affectation(t, uid: int, identifiant: str, role: str, poste: str | None,
                            projets: list[str] | None) -> None:
    """Poste (modèle de départ) et chantiers affectés d'un usager, dans la transaction de modification du compte."""
    poste = poste or None
    if poste:
        p = profils(tx=t).get(poste)
        if not p or not p["actif"]:
            raise ValueError("Poste ou profil inconnu ou désactivé.")
        if p["role"] != role:
            raise ValueError(f"Le poste « {p['libelle']} » relève de la famille « {ROLES[p['role']]} ».")
    auteur = utilisateur() or {}
    if role == "admin" and auteur.get("role") != "admin":
        raise ValueError("Seule la direction générale peut créer ou modifier un compte administrateur.")
    projets = sorted(set(projets or [])) or None
    if projets:
        connus = {r[0] for r in t.cx.execute(sa.select(db.projects.c.id))}
        if inconnus := [p for p in projets if p not in connus]:
            raise ValueError(f"Chantiers inconnus : {', '.join(inconnus)}.")
    for cle, valeur, quoi in ((f"poste_utilisateur:{uid}", poste, "Poste"),
                              (f"projets_utilisateur:{uid}", projets, "Chantiers affectés")):
        avant = t.cx.execute(sa.select(db.settings.c.valeur).where(db.settings.c.cle == cle)).scalar()
        if (avant or None) != valeur:
            t.parametre(cle, valeur, resume=f"{quoi} de {identifiant}")


def poste_de(uid: int) -> str | None:
    p = db.parametre(f"poste_utilisateur:{uid}")
    return p if isinstance(p, str) and p else None


def modele_droits(role: str, poste: str | None) -> dict:
    """Modèle d'accès : celui du poste s'il est actif et de la même famille de rôle, sinon celui du rôle."""
    if role == "admin":
        return {m: "w" for m in MODULES}
    p = profils().get(poste) if poste else None
    if p and p["actif"] and p["role"] == role:
        return dict(p["droits"])
    return dict(DROITS.get(role, {}))


def libelle_poste(uid: int, role: str) -> str:
    p = profils().get(poste_de(uid) or "")
    return p["libelle"] if p and p["role"] == role else ROLES.get(role, role)


def projets_de(uid: int, tx=None) -> list[str] | None:
    """Chantiers affectés à l'usager ; None = tous les chantiers."""
    v = _param(f"projets_utilisateur:{uid}", tx)
    return list(v) if isinstance(v, list) and v else None


def sur_chantier(u: dict, projet: str, tx=None) -> bool:
    """Vrai si le chantier est dans le périmètre de l'usager (l'administrateur voit tout)."""
    if not u or u.get("role") == "admin":
        return True
    p = projets_de(u["id"], tx)
    return p is None or projet in p


def droits_de(uid: int, role: str) -> dict:
    """Droits effectifs d'un usager : le modèle de son poste (ou de son rôle), sauf les accès réglés par
    l'administrateur pour cette personne, qui restent prioritaires."""
    if role == "admin":  # la direction générale garde toujours tous les accès
        return {m: "w" for m in MODULES}
    base = modele_droits(role, poste_de(uid))
    perso = db.parametre(f"droits_utilisateur:{uid}")
    if isinstance(perso, dict):
        for m, niveau in perso.items():
            if m in MODULES:
                base[m] = None if niveau in (None, "x") else niveau
    return {m: base.get(m) for m in MODULES}


def peut(droits: dict | None, module: str) -> bool:
    """Vrai si les droits (session ou base) donnent la modification de la rubrique."""
    return (droits or {}).get(module) == "w"


def personnalise(uid: int) -> bool:
    return isinstance(db.parametre(f"droits_utilisateur:{uid}"), dict)


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
        out = {k: row[k] for k in ("id", "identifiant", "nom", "role", "doit_changer_mdp")}
        out["droits"] = droits_de(row["id"], row["role"])
        return out, None


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
    out = {k: u[k] for k in ("id", "identifiant", "nom", "role", "doit_changer_mdp")}
    out["droits"] = droits_de(u["id"], u["role"])
    return out


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
    u = utilisateur() or {}
    droits = u.get("droits")
    if droits is None:  # session ouverte avant ce réglage : modèle du rôle
        droits = DROITS.get(u.get("role"), {})
    return droits.get(module)


def voit(module: str) -> bool:
    return droit(module) in ("r", "w")


def modifie(module: str) -> bool:
    return droit(module) == "w"


def est_admin() -> bool:
    """Vrai pour le rôle administrateur (direction générale) uniquement."""
    return (utilisateur() or {}).get("role") == "admin"


def exiger(module: str) -> None:
    """À placer en tête de page : arrête l'affichage si le rôle n'a pas accès au module."""
    if not voit(module):
        st.error("Votre rôle ne donne pas accès à cette rubrique.")
        st.stop()
