"""Soldes de caisse, contrôle du solde et arrêtés de caisse (mémo V8, § 9.1 « Caisses arrêtées »).

Une « caisse » est un compte de trésorerie dans une devise :
- chaque compte de trésorerie du circuit V7 (caisse, banque ou Mobile money, une devise chacun) : clé « v7:<id> » ;
- le journal de caisse historique, hors comptes V7, par compte et par devise : clé « h:<compte>:<devise> ».
Les soldes restent dans leur devise : aucune conversion (les billets CDF d'une caisse ne sont pas des USD).

Tout est paramétrable par la DG : comptes dont le solde ne peut pas devenir négatif, coupures du billetage par
devise, comptes d'écart de caisse (manquant, excédent), droits de validation des arrêtés.
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

import auth
import db
import derogations as DG
import gestion_v7 as V
import regles as R

PARAMETRES_DEFAUT = {
    # Un solde de caisse ou de Mobile money ne peut jamais devenir négatif ; la banque peut avoir un découvert autorisé.
    "interdire_negatif": {"cash": True, "mobile": True, "bank": False},
    # Coupures en circulation, en unités de la devise (billetage du procès-verbal de comptage).
    "coupures": {"USD": [100, 50, 20, 10, 5, 2, 1],
                 "CDF": [20000, 10000, 5000, 1000, 500, 200, 100, 50, 20, 10],
                 "EUR": [500, 200, 100, 50, 20, 10, 5]},
    "compte_manquant": "658",     # Charges diverses (ou compte du caissier, selon la décision de la DG)
    "compte_excedent": "758",     # Produits divers
}
ORDRE_NATURE = {"cash": 0, "mobile": 1, "bank": 2}
STATUTS_ARRETE = ("Proposé", "Validé", "Rejeté")


# ------------------------------------------------------------------ paramètres
def parametres(tx=None) -> dict:
    v = auth._param("caisse_parametres", tx)
    p = {k: (dict(x) if isinstance(x, dict) else x) for k, x in PARAMETRES_DEFAUT.items()}
    if isinstance(v, dict):
        for k, x in v.items():
            if k in p:
                p[k] = {**p[k], **x} if isinstance(p[k], dict) and isinstance(x, dict) else x
    return p


def configurer(valeurs: dict, motif: str) -> None:
    """Décision DG, motivée et tracée au journal d'audit."""
    u = V.actor()
    V._exiger(u, "approbation_dg", "Paramètres de caisse réservés à la DG.")
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    p = parametres()
    for k, x in valeurs.items():
        if k not in PARAMETRES_DEFAUT:
            raise ValueError(f"Paramètre inconnu : {k}.")
        if k in ("compte_manquant", "compte_excedent") and not str(x).strip().isdigit():
            raise ValueError("Les comptes d’écart de caisse sont des numéros (chiffres seulement).")
        if k == "interdire_negatif" and set(x) - set(R.CASH_ACCOUNTS):
            raise ValueError("Nature de compte inconnue.")
        if k == "coupures":
            for dev, liste in x.items():
                if dev not in R.CURRENCIES or not liste or any(int(c) <= 0 for c in liste):
                    raise ValueError(f"Coupures invalides pour {dev}.")
            x = {dev: sorted({int(c) for c in liste}, reverse=True) for dev, liste in x.items()}
        p[k] = x
    with db.transaction("Paramètres de caisse") as t:
        t.parametre("caisse_parametres", p, resume=f"Paramètres de caisse : {motif.strip()}")


# ------------------------------------------------------------------ caisses et soldes
def cle(m: dict) -> str | None:
    """Caisse d'un mouvement ; None pour un mouvement historique incomplet (sans date ou sans compte)."""
    if not R.cash_complete(m):
        return None
    v7 = (m.get("journal") or {}).get("v7_account")
    return f"v7:{v7}" if v7 else f"h:{m['account']}:{m['currency']}"


def _signe(m: dict) -> int:
    return int(m["amount"]) if m["direction"] == "in" else -int(m["amount"])


def _ordre(m: dict):
    return (m["date"], str(m.get("cree_le") or ""), str(m["id"]))


def _mouvements(tx=None) -> list[dict]:
    if tx is not None:
        return [dict(r._mapping) for r in tx.cx.execute(sa.select(db.TABLES["movements"]))]
    return db.tout("movements")


def _comptes_v7(tx=None) -> dict:
    return {a["id"]: a for a in V.records("account", tx)}


def _identite(k: str, comptes: dict, p: dict, tx=None) -> dict:
    if k.startswith("v7:"):
        a = comptes.get(k[3:])
        if not a:
            return dict(libelle="Compte V7 supprimé", nature="cash", devise="", compte="")
        return dict(libelle=f"{a['data'].get('label') or a['ref']} ({a['ref']})", nature=a["data"].get("legacy", "cash"),
                    devise=a["currency"], compte=a["data"].get("ledger", ""))
    _, nature, devise = k.split(":")
    import comptabilisation as CPT
    return dict(libelle=f"{R.account_name(nature)} — journal de caisse", nature=nature, devise=devise,
                compte=(CPT.parametres(tx).get("tresorerie_historique") or {}).get(nature, ""))


def caisses(date_: str | None = None, tx=None, mouvements: list[dict] | None = None) -> list[dict]:
    """Solde de chaque caisse, dans sa devise, à la date choisie (aujourd'hui par défaut), avec son dernier mouvement."""
    date_ = date_ or R.today()
    p = parametres(tx)
    comptes = _comptes_v7(tx)
    groupes: dict[str, list[dict]] = {f"v7:{i}": [] for i in comptes}
    for m in (mouvements if mouvements is not None else _mouvements(tx)):
        k = cle(m)
        if k and m["date"] <= date_:
            groupes.setdefault(k, []).append(m)
    out = []
    for k, mv in groupes.items():
        ident = _identite(k, comptes, p, tx)
        mv.sort(key=_ordre)
        solde = sum(_signe(m) for m in mv)
        dernier = mv[-1] if mv else None
        out.append(dict(cle=k, **ident, solde=solde, nb=len(mv), negatif=solde < 0,
                        bloque=bool((p["interdire_negatif"] or {}).get(ident["nature"])),
                        dernier_date=dernier["date"] if dernier else "",
                        dernier_libelle=dernier["label"] if dernier else "",
                        dernier_montant=_signe(dernier) if dernier else 0))
    return sorted(out, key=lambda c: (ORDRE_NATURE.get(c["nature"], 9), c["libelle"], c["devise"]))


def solde(k: str, date_: str | None = None, tx=None) -> int:
    date_ = date_ or R.today()
    return sum(_signe(m) for m in _mouvements(tx) if cle(m) == k and m["date"] <= date_)


def caisse(k: str, tx=None) -> dict:
    c = next((x for x in caisses(tx=tx) if x["cle"] == k), None)
    if not c:
        raise ValueError("Caisse introuvable.")
    return c


# ------------------------------------------------------------------ contrôle : pas de sortie supérieure au solde
def _fins_de_journee(mv: list[dict]) -> dict[str, int]:
    """Solde de fin de journée à chaque date mouvementée. Le contrôle est fait à la journée : l'ordre des mouvements
    d'un même jour n'est pas fiable (saisies groupées, reprise d'historique)."""
    par_jour: dict[str, int] = {}
    for m in mv:
        par_jour[m["date"]] = par_jour.get(m["date"], 0) + _signe(m)
    out, courant = {}, 0
    for jour in sorted(par_jour):
        courant += par_jour[jour]
        out[jour] = courant
    return out


def _solde_au(fins: dict[str, int], jour: str) -> int:
    return next((fins[d] for d in sorted(fins, reverse=True) if d <= jour), 0)


def noter(t, avant: dict | None, apres: dict | None) -> None:
    """Appelé par db.Transaction à chaque écriture d'un mouvement : retient, pour chaque caisse touchée, ses soldes de
    fin de journée avant la transaction. Le contrôle lui-même a lieu à la validation de la transaction (verifier), pour
    qu'une saisie groupée (import d'un journal, virement) soit jugée sur son résultat d'ensemble."""
    suivies = t.__dict__.setdefault("_caisses", {})
    for m in (avant, apres):
        k = cle(m) if m else None
        if not k or k in suivies:
            continue
        # État avant cette écriture : on retire la version écrite et on remet l'ancienne.
        ids = {x["id"] for x in (avant, apres) if x}
        mv = [x for x in _mouvements(t) if cle(x) == k and x["id"] not in ids]
        if avant and cle(avant) == k:
            mv.append(avant)
        suivies[k] = _fins_de_journee(mv)


def verifier(t) -> None:
    """Refuse la transaction si, à une date quelconque, elle rend négatif le solde de fin de journée d'une caisse
    protégée ou le rend plus négatif qu'il n'était. Une caisse déjà négative dans l'historique repris n'empêche donc
    pas d'enregistrer une entrée, mais aucune nouvelle sortie tant qu'elle n'est pas renflouée."""
    suivies = t.__dict__.get("_caisses") or {}
    if not suivies:
        return
    p = parametres(t)
    comptes = _comptes_v7(t)
    tous = _mouvements(t)
    for k, avant in suivies.items():
        ident = _identite(k, comptes, p, t)
        if not (p["interdire_negatif"] or {}).get(ident["nature"]):
            continue
        apres = _fins_de_journee([m for m in tous if cle(m) == k])
        for jour in sorted(set(avant) | set(apres)):
            s_apres, s_avant = _solde_au(apres, jour), _solde_au(avant, jour)
            if s_apres < 0 and s_apres < s_avant:
                veille = _solde_au(apres, max((d for d in apres if d < jour), default=""))
                entrees = sum(int(m["amount"]) for m in tous
                              if cle(m) == k and m["date"] == jour and m["direction"] == "in")
                raise ValueError(
                    f"Solde insuffisant : « {ident['libelle']} » serait à {R.money(s_apres, ident['devise'])} en fin "
                    f"de journée du {jour}. Une sortie ne peut pas dépasser le solde de la caisse "
                    f"({R.money(veille + entrees, ident['devise'])} disponibles ce jour-là). Enregistrez d’abord "
                    "l’entrée ou le solde de départ.")


# ------------------------------------------------------------------ arrêtés de caisse
def coupures(devise: str) -> list[int]:
    return list((parametres()["coupures"] or {}).get(devise) or [])


def montant_billetage(billetage: dict, autres: int = 0) -> int:
    total = 0
    for c, n in (billetage or {}).items():
        n = int(n or 0)
        if n < 0:
            raise ValueError("Le nombre de billets ne peut pas être négatif.")
        total += int(round(float(c) * 100)) * n
    if int(autres or 0) < 0:
        raise ValueError("Le complément compté ne peut pas être négatif.")
    return total + int(autres or 0)


def proposer_arrete(k: str, date_: str, billetage: dict, autres: int = 0, explication: str = "") -> str:
    """Procès-verbal de comptage saisi par le caissier : billets comptés, écart avec le solde théorique."""
    u = V.actor()
    V._exiger(u, "tresorerie", "Arrêté de caisse réservé à la trésorerie.")
    V.date(date_)
    if date_ > R.today():
        raise ValueError("Un arrêté de caisse ne peut pas être daté dans le futur.")
    with db.transaction("Arrêté de caisse") as t:
        c = caisse(k, t)
        arr = [dict(r._mapping) for r in t.cx.execute(
            sa.select(db.TABLES["caisse_arretes"]).where(db.TABLES["caisse_arretes"].c.caisse == k))]
        if any(a["statut"] == "Proposé" for a in arr):
            raise ValueError("Un arrêté est déjà en attente de validation pour cette caisse.")
        if any(a["statut"] == "Validé" and a["date"] >= date_ for a in arr):
            raise ValueError("Un arrêté validé existe déjà à cette date ou après : la caisse est arrêtée.")
        compte = montant_billetage(billetage, autres)
        theorique = solde(k, date_, t)
        ecart = compte - theorique
        if ecart and not (explication or "").strip():
            raise ValueError("Écart constaté : une explication est obligatoire.")
        id_ = db.nouvel_id()
        t.inserer("caisse_arretes", dict(
            id=id_, caisse=k, libelle_caisse=c["libelle"], devise=c["devise"], date=date_, solde_theorique=theorique,
            billetage={str(x): int(n) for x, n in (billetage or {}).items() if int(n or 0)}, autres=int(autres or 0),
            montant_compte=compte, ecart=ecart, explication=(explication or "").strip(), statut="Proposé",
            saisi_par=u["id"], saisi_le=db.maintenant(), version=1),
            resume=f"Arrêté de caisse {c['libelle']} au {date_} : écart {R.money(ecart, c['devise'])}")
    return id_


def _regulariser(t, a: dict, c: dict, compte_ecart: str) -> str:
    """Mouvement de régularisation de l'écart, daté de l'arrêté, comptabilisé au compte d'écart paramétré."""
    import comptabilisation as CPT
    sens = "in" if a["ecart"] > 0 else "out"
    libelle = f"Écart d’arrêté de caisse du {a['date']} ({'excédent' if sens == 'in' else 'manquant'})"
    mid = db.nouvel_id()
    base = dict(id=mid, date=a["date"], label=libelle, direction=sens, amount=abs(a["ecart"]), currency=c["devise"],
                project="", invoice_id="", invoice_amount=None, expense_id="", supplier_payment_id="",
                supplier_reversal_id="", cree_le=db.maintenant())
    if a["caisse"].startswith("v7:"):
        compte_v7 = V.get(t, a["caisse"][3:], "account")
        t.inserer("movements", dict(base, kind="v7", account=compte_v7["data"]["legacy"],
                                    journal=dict(v7_account=compte_v7["id"], v7_source="arrete:" + a["id"],
                                                 compte=compte_ecart, imputation="Écart de caisse")))
        if CPT.actif(t, a["date"]):
            ctx = CPT._ctx_devise(t, abs(a["ecart"]), c["devise"], a["date"])
            CPT.comptabiliser(t, "tresorerie_manuel", a["date"], libelle, "caisse_arrete", a["id"],
                              dict(ctx, contrepartie=-(ctx["montant"] if sens == "in" else -ctx["montant"]),
                                   compte_contrepartie=compte_ecart, centre="FRAIS GÉNÉRAUX"),
                              journal=CPT.journal_tresorerie(t, compte_v7))
    else:
        _, nature, _ = a["caisse"].split(":")
        t.inserer("movements", dict(base, kind="manual", account=nature,
                                    journal=dict(compte=compte_ecart, imputation="Écart de caisse",
                                                 piece=f"AC-{a['date']}-{a['id'][:6]}", centre="")))
    return mid


def decider_arrete(id_: str, valider: bool, motif: str = "") -> None:
    """Validation (ou rejet) par une autre personne que le caissier : comptabilité ou DG."""
    u = V.actor()
    if not (auth.droits_de(u["id"], u["role"]).get("comptabilite") == "w"
            or auth.droits_de(u["id"], u["role"]).get("approbation_dg") == "w"):
        raise ValueError("Validation des arrêtés de caisse réservée à la comptabilité ou à la DG.")
    if not valider and not (motif or "").strip():
        raise ValueError("Motif du rejet obligatoire.")
    with db.transaction("Décision sur un arrêté de caisse") as t:
        a = t.get("caisse_arretes", id_)
        if not a or a["statut"] != "Proposé":
            raise ValueError("Cet arrêté n’est plus en attente de validation.")
        DG.exiger_distinct(t, u["id"], {a["saisi_par"]}, "arrete_caisse",
                           "le caissier qui a compté ne peut pas valider son propre arrêté", a["date"])
        vals = dict(statut="Validé" if valider else "Rejeté", decide_par=u["id"], decide_le=db.maintenant(),
                    motif_decision=(motif or "").strip(), version=a["version"] + 1)
        if valider:
            if solde(a["caisse"], a["date"], t) != a["solde_theorique"]:
                raise ValueError("Des mouvements ont été saisis ou modifiés à cette date ou avant depuis le comptage : "
                                 "rejetez cet arrêté et refaites le comptage.")
            if a["ecart"]:
                p = parametres(t)
                c = caisse(a["caisse"], t)
                vals["mouvement_ecart"] = _regulariser(t, a, c, p["compte_excedent"] if a["ecart"] > 0
                                                       else p["compte_manquant"])
        t.maj("caisse_arretes", id_, vals,
              resume=f"Arrêté de caisse {a['libelle_caisse']} au {a['date']} : {vals['statut'].lower()}")


def arretes(k: str | None = None) -> list[dict]:
    out = [a for a in db.tout("caisse_arretes") if k is None or a["caisse"] == k]
    return sorted(out, key=lambda a: (a["date"], str(a["saisi_le"])), reverse=True)


def dernier_arrete(k: str) -> dict | None:
    return next((a for a in arretes(k) if a["statut"] == "Validé"), None)


def etat_cloture(mois: str) -> list[dict]:
    """Point « Caisses arrêtées » de la liste de clôture mensuelle (§ 9.1) : chaque caisse protégée (caisse, Mobile
    money) mouvementée dans le mois ou dont le solde de fin de mois n'est pas nul doit avoir un arrêté validé daté du
    mois, au plus tôt à la date de son dernier mouvement du mois."""
    an, mo = (int(x) for x in mois.split("-"))
    debut = dt.date(an, mo, 1).isoformat()
    fin = (dt.date(an + mo // 12, mo % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
    tous = _mouvements()
    out = []
    for c in caisses(fin, mouvements=tous):
        if not c["bloque"]:
            continue
        du_mois = [m for m in tous if cle(m) == c["cle"] and debut <= m["date"] <= fin]
        if not du_mois and not c["solde"]:
            continue
        dernier = max((m["date"] for m in du_mois), default=debut)
        a = next((x for x in arretes(c["cle"]) if x["statut"] == "Validé" and dernier <= x["date"] <= fin), None)
        out.append(dict(caisse=c["libelle"], devise=c["devise"], solde=c["solde"], arretee=bool(a),
                        arrete=a["date"] if a else "", ecart=a["ecart"] if a else 0))
    return out
