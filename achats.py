"""Circuit d'achat V8 (mémo V8, § 5) : la demande d'achat à lignes d'articles est le point de départ unique de tout
achat ; chaque étape se crée depuis la précédente et le statut des lignes en est déduit, jamais saisi.

    besoin du chantier → bon de sortie (part disponible) + demande d'achat (manque)
    → N0 (engagement prévisionnel) → N1 → N2 → N3 → DG (délégations V7) → bon de commande (engagement ferme,
    plusieurs demandes d'un même fournisseur) → réception (entrée en stock, ou coût réalisé si non stocké)
    → facture (rapprochement à 3 voies) → paiement (trésorerie V7) → sortie vers le chantier (coût réalisé)

Tous les seuils et tolérances sont des paramètres DG datés, sans valeur par défaut : une étape qui en a besoin est
bloquée tant qu'ils ne sont pas fixés. Les montants sont des centimes entiers ; une conversion de devise utilise le
taux historique enregistré à la date, jamais estimé. Les écritures comptables complètes (ACH, STK, BQ) viendront du
lot 1 ; en attendant, la facture et le paiement produisent les écritures simples du circuit V7.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

import auth
import db
import derogations as DR
import devises as DV
import gestion_v7 as V
import regles as R
import stocks as S
from stocks import D, T, _lignes, _un, cents, numero, qte

STATUTS_VALIDATION = ("Brouillon", "Soumise", "Approuvée", "Annulée")
ETAPES = ("Brouillon", "Soumise", "Approuvée", "Partiellement commandée", "Commandée", "Partiellement reçue", "Reçue",
          "Facturée", "Payée", "Soldée")


# ------------------------------------------------------------------ paramètres DG (aucune valeur par défaut)
def parametres(tx=None) -> dict:
    v = auth._param("achats_parametres", tx)
    return v if isinstance(v, dict) else {}


def configurer(tolerance_qte_pct, tolerance_prix_pct, seuil_devis: dict, nb_devis: int, reference: str,
               motif: str) -> None:
    u = S.acteur("approbation_dg", "Paramètres d’achat fixés par la DG.")
    try:
        tq, tp = Decimal(str(tolerance_qte_pct).replace(",", ".")), Decimal(str(tolerance_prix_pct).replace(",", "."))
    except Exception:  # noqa: BLE001
        raise ValueError("Tolérances : pourcentages attendus.") from None
    if not (0 <= tq <= 100 and 0 <= tp <= 100):
        raise ValueError("Tolérances entre 0 et 100 %.")
    seuils = {}
    for c in R.CURRENCIES:
        v = (seuil_devis or {}).get(c)
        seuils[c] = None if v in (None, "") else V.amount(int(v))
    if int(nb_devis) < 1:
        raise ValueError("Nombre de devis exigé : au moins 1.")
    if not (reference or "").strip() or not (motif or "").strip():
        raise ValueError("Référence de la décision et motif obligatoires.")
    with db.transaction("Paramètres d’achat") as t:
        t.parametre("achats_parametres", dict(tolerance_qte_pct=str(tq), tolerance_prix_pct=str(tp), seuil_devis=seuils,
                                              nb_devis=int(nb_devis), reference=reference.strip(), motif=motif.strip(),
                                              decide_par=u["id"], decide_nom=u["nom"], decide_le=db.maintenant().isoformat()),
                    resume=f"Paramètres d’achat ({reference.strip()})")


def _tolerance(tx, cle: str) -> Decimal:
    p = parametres(tx)
    if p.get(cle) in (None, ""):
        raise ValueError("Paramètre DG manquant : tolérances de quantité et de prix à fixer dans Paramètres achats et "
                         "stock avant les commandes, réceptions et factures.")
    return Decimal(p[cle]) / 100


# ------------------------------------------------------------------ lecture
def _demande(tx, id_, verrou=False):
    d = _un(tx, "ach_demandes", id_, verrou)
    if not d:
        raise ValueError("Demande d’achat introuvable.")
    return d


def lignes_demande(tx, demande: str) -> list[dict]:
    return sorted(_lignes(tx, "ach_demande_lignes", T("ach_demande_lignes").c.demande == demande), key=lambda l: l["numero"])


def _hist(d: dict, u: dict, action: str, note: str = "") -> list:
    h = list(d.get("historique") or [])
    h.append(dict(user=u["id"], name=u["nom"], action=action, note=note, at=db.maintenant().isoformat()))
    return h


def _maj(t, nom: str, ligne: dict, valeurs: dict) -> None:
    tb = T(nom)
    res = t.cx.execute(tb.update().where(tb.c.id == ligne["id"], tb.c.version == ligne["version"]).values(
        **valeurs, version=ligne["version"] + 1))
    if res.rowcount != 1:
        raise ValueError("Une autre personne a modifié ce document. Actualisez.")
    t._auditer("Modification", nom, ligne["id"], {k: ligne.get(k) for k in valeurs}, valeurs)


def _get(tx, nom, id_):
    return _un(tx, nom, id_) if tx is not None else db.un(nom, id_)


def _quantites(tx, demande_ligne: str) -> dict:
    """Quantités commandées, reçues, facturées et état du paiement d'une ligne de demande (déduits des documents)."""
    cl = T("ach_commande_lignes")
    cmds = [c for c in _lignes(tx, "ach_commande_lignes", cl.c.demande_ligne == demande_ligne)
            if (_get(tx, "ach_commandes", c["commande"]) or {}).get("statut") == "Émise"]
    out = dict(commande=Decimal(0), recu=Decimal(0), rejete=Decimal(0), facture=Decimal(0), paye=True, lignes_cmd=cmds)
    for c in cmds:
        out["commande"] += D(c["quantite"])
        for r in _lignes(tx, "ach_reception_lignes", T("ach_reception_lignes").c.commande_ligne == c["id"]):
            out["recu"] += D(r["qte_acceptee"])
            out["rejete"] += D(r["qte_rejetee"])
        for f in _lignes(tx, "ach_facture_lignes", T("ach_facture_lignes").c.commande_ligne == c["id"]):
            fac = _get(tx, "ach_factures", f["facture"])
            if fac and fac["statut"] != "Rejetée":
                out["facture"] += D(f["quantite"])
                ttc = fac["montant_ht"] + fac["tva"]
                if fac["statut"] != "Validée" or sum(p["montant"] for p in fac["paiements"] if not p.get("annule")) < ttc:
                    out["paye"] = False
    return out


def statut_ligne(d: dict, l: dict, tx=None) -> str:
    """Statut synchronisé d'une ligne, déduit des documents liés (mémo § 5.3)."""
    if d["statut"] != "Approuvée":
        return d["statut"]
    if l["cloturee"]:
        return "Soldée"
    q = _quantites(tx, l["id"])
    attendu = D(l["quantite"])
    if q["commande"] == 0:
        return "Approuvée"
    if q["facture"] >= attendu and q["recu"] >= attendu:
        return "Soldée" if q["paye"] else "Facturée"
    if q["facture"] and q["facture"] >= q["recu"]:
        return "Facturée"
    if q["recu"] >= attendu:
        return "Reçue"
    if q["recu"] > 0:
        return "Partiellement reçue"
    return "Commandée" if q["commande"] >= attendu else "Partiellement commandée"


def statut_demande(d: dict, tx=None) -> str:
    if d["statut"] != "Approuvée":
        return d["statut"]
    statuts = [statut_ligne(d, l, tx) for l in lignes_demande(tx, d["id"])]
    return min(statuts, key=ETAPES.index) if statuts else "Approuvée"


def montant_estime(tx, demande: str) -> int:
    return sum(cents(D(l["quantite"]) * l["prix_estime"]) for l in lignes_demande(tx, demande))


# ------------------------------------------------------------------ effets sur le budget DQE (lus par gestion_v7.metrics)
def effets_budget(projet: str, devise: str, tx=None) -> dict[str, dict]:
    """Par poste DQE : engagement ouvert (prévisionnel puis ferme), coût réalisé et décaissements, dans la devise
    du budget. Coût réalisé : à la sortie de stock (article stocké), à la réception (non stocké, prestation) ;
    le paiement ne crée jamais un second coût."""
    out: dict[str, dict] = {}

    def ajout(poste, cle, v):
        p = out.setdefault(poste, dict(open=0, cost=0, cash=0))
        p[cle] = p.get(cle, 0) + v

    taux_rows = V.records("rate", tx) if tx is not None else None
    for d in _lignes(tx, "ach_demandes", T("ach_demandes").c.projet == projet):
        if d["statut"] not in ("Soumise", "Approuvée") or d["devise"] != devise:
            continue
        for l in lignes_demande(tx, d["id"]):
            art = _get(tx, "stk_articles", l["article"])
            q = _quantites(tx, l["id"])
            reste = max(Decimal(0), D(l["quantite"]) - q["commande"])
            if not l["cloturee"] and reste:
                ajout(l["poste"], "open", cents(reste * l["prix_estime"]))      # engagement prévisionnel
            for c in q["lignes_cmd"]:
                unite_b = Decimal(c["montant_budget"]) / D(c["quantite"])
                recus = _lignes(tx, "ach_reception_lignes", T("ach_reception_lignes").c.commande_ligne == c["id"])
                recu = sum((D(r["qte_acceptee"]) for r in recus), Decimal(0))
                ecarts = 0
                for fl in _lignes(tx, "ach_facture_lignes", T("ach_facture_lignes").c.commande_ligne == c["id"]):
                    ecarts += int(fl["ecart_budget"])
                    fac = _get(tx, "ach_factures", fl["facture"])
                    if fac and fac["statut"] == "Validée" and fac["montant_ht"]:
                        part = Decimal(cents(D(fl["quantite"]) * fl["prix_unitaire"])) / fac["montant_ht"]
                        for p in fac["paiements"]:
                            if not p.get("annule"):
                                v = DV.convertir(cents(part * p["montant"]), fac["devise"], devise, p["date"], taux_rows)
                                ajout(l["poste"], "cash", v or 0)
                ajout(l["poste"], "cost", ecarts)
                if art["nature"] == "stocke":
                    # Engagement ferme jusqu'à la sortie vers le chantier, qui le transforme en coût réalisé.
                    ferme = int(c["montant_budget"]) if not l["cloturee"] else cents(min(recu, D(c["quantite"])) * unite_b)
                    ajout(l["poste"], "ferme_stk", ferme)
                else:
                    ajout(l["poste"], "cost", sum(int(r["cout_budget"]) for r in recus))
                    if not l["cloturee"]:
                        ajout(l["poste"], "open", max(0, cents((D(c["quantite"]) - recu) * unite_b)))
    # Sorties de stock imputées au chantier : coût réalisé (monnaie de tenue → devise du budget, taux de la date)
    for m in S.sorties_chantier(projet, tx):
        if not m["poste"] or m["type"] == "ecart_prix":
            continue
        v = DV.convertir(-int(m["valeur"]), m["devise_tenue"], devise, m["date"], taux_rows)
        ajout(m["poste"], "cost", v or 0)
        ajout(m["poste"], "sorti_stk", v or 0)
    for p in out.values():
        p["open"] += max(0, p.pop("ferme_stk", 0) - p.pop("sorti_stk", 0))
    return out


# ------------------------------------------------------------------ 1. besoin du chantier et demande d'achat
def _controle_lignes(t, projet: str, budget: dict, lignes: list[dict]) -> list[dict]:
    if not lignes:
        raise ValueError("Au moins une ligne d’article.")
    postes = {x["code"] for x in budget["data"]["lines"]}
    out = []
    for i, l in enumerate(lignes, 1):
        a = _un(t, "stk_articles", l.get("article"))
        if not a or not a["actif"]:
            raise ValueError(f"Ligne {i} : article inconnu ou inactif.")
        if l.get("poste") not in postes:
            raise ValueError(f"Ligne {i} : poste DQE absent du budget du chantier.")
        prix = V.amount(int(l.get("prix_estime") or 0))
        f = (l.get("fournisseur") or "").strip() or None
        if f:
            c = t.get("clients", f)
            if not c or not set(R.party_roles(c)) & {"supplier", "subcontractor"}:
                raise ValueError(f"Ligne {i} : fournisseur suggéré introuvable ou sans rôle fournisseur.")
        out.append(dict(numero=i, article=a["id"], poste=l["poste"], quantite=qte(l.get("quantite"), f"Ligne {i} : quantité"),
                        prix_estime=prix, fournisseur_suggere=f, motif_hors_stock=(l.get("motif_hors_stock") or "").strip() or None,
                        note=(l.get("note") or "").strip()[:500] or None, cloturee=False))
    return out


def _creer_demande_tx(t, u, projet, date_souhaitee, magasin, urgence, justification, lignes, origine="") -> str:
    V.date(date_souhaitee)
    b = V.budget_for(projet, t)
    propres = _controle_lignes(t, projet, b, lignes)
    if magasin:
        m = _un(t, "stk_magasins", magasin)
        if not m or not m["actif"]:
            raise ValueError("Magasin de livraison introuvable ou inactif.")
    elif any(_un(t, "stk_articles", l["article"])["nature"] == "stocke" for l in propres):
        raise ValueError("Magasin de livraison obligatoire pour des articles stockés.")
    id_ = db.nouvel_id()
    t.inserer("ach_demandes", dict(
        id=id_, numero=numero(t, "ach_demandes", "DA", date_souhaitee if date_souhaitee[:4] == R.today()[:4] else None),
        projet=projet, devise=b["currency"], demandeur=u["id"], date_souhaitee=date_souhaitee, magasin=magasin or None,
        urgence=urgence or "Normale", justification=(justification or "").strip(), statut="Brouillon", niveau=0,
        approbations=[], derogation_dg=False, historique=_hist({}, u, "Création" + (f" ({origine})" if origine else "")),
        origine=origine, cree_par=u["id"], cree_le=db.maintenant(), version=1))
    for l in propres:
        t.inserer("ach_demande_lignes", dict(id=db.nouvel_id(), demande=id_, **l))
    return id_


def creer_demande(projet: str, date_souhaitee: str, magasin: str | None, lignes: list[dict], justification: str = "",
                  urgence: str = "Normale") -> str:
    u = S.acteur("demandes_achat", "Votre profil ne permet pas de créer une demande d’achat.")
    if not auth.sur_chantier(u, projet):
        raise ValueError("Chantier hors de votre périmètre (chantiers affectés).")
    with db.transaction("Demande d’achat") as t:
        return _creer_demande_tx(t, u, projet, date_souhaitee, magasin, urgence, justification, lignes)


def besoin_chantier(projet: str, magasin: str, date_: str, lignes: list[dict], justification: str = "") -> dict:
    """Étape 1 : le disponible du magasin part au chantier (bon de sortie réservé) ; seul le manque devient une
    demande d'achat. lignes : article, poste, quantite, prix_estime (pour le manque), fournisseur."""
    u = S.acteur("demandes_achat", "Votre profil ne permet pas d’exprimer un besoin.")
    if not auth.sur_chantier(u, projet):
        raise ValueError("Chantier hors de votre périmètre (chantiers affectés).")
    with db.transaction("Besoin du chantier") as t:
        a_sortir, a_acheter = [], []
        for l in lignes:
            art = _un(t, "stk_articles", l["article"])
            q = qte(l["quantite"])
            dispo = S.disponible(t, l["article"], magasin) if art and art["nature"] == "stocke" else Decimal(0)
            pris = min(q, max(Decimal(0), dispo))
            if pris:
                a_sortir.append(dict(article=l["article"], poste=l["poste"], quantite=pris))
            if q - pris:
                a_acheter.append({**l, "quantite": q - pris})
        bon = S._creer_bon_tx(t, u, projet, magasin, date_, a_sortir, justification) if a_sortir else None
        demande = _creer_demande_tx(t, u, projet, date_, magasin, "Normale", justification, a_acheter,
                                    origine="besoin chantier") if a_acheter else None
        return dict(bon_sortie=bon, demande=demande)


def modifier_demande(id_: str, date_souhaitee: str, magasin: str | None, lignes: list[dict], justification: str = "",
                     urgence: str = "Normale") -> None:
    """Toute modification après validation relance le circuit (validations remises à zéro)."""
    u = S.acteur("demandes_achat")
    with db.transaction("Modification de la demande d’achat") as t:
        d = _demande(t, id_, True)
        if d["demandeur"] != u["id"] or d["statut"] not in ("Brouillon", "Soumise", "Approuvée"):
            raise ValueError("Seul le demandeur modifie sa demande, tant qu’elle n’est ni commandée ni annulée.")
        anciennes = lignes_demande(t, id_)
        if any(_quantites(t, l["id"])["commande"] for l in anciennes):
            raise ValueError("Demande déjà commandée : clôturez les lignes restantes et créez une nouvelle demande.")
        V.date(date_souhaitee)
        b = V.budget_for(d["projet"], t)
        propres = _controle_lignes(t, d["projet"], b, lignes)
        for l in anciennes:
            t.cx.execute(T("ach_demande_lignes").delete().where(T("ach_demande_lignes").c.id == l["id"]))
            t._auditer("Suppression", "ach_demande_lignes", l["id"], l, None, "Lignes remplacées avant commande")
        for l in propres:
            t.inserer("ach_demande_lignes", dict(id=db.nouvel_id(), demande=id_, **l))
        _maj(t, "ach_demandes", d, dict(date_souhaitee=date_souhaitee, magasin=magasin or None, urgence=urgence,
                                        justification=(justification or "").strip(), statut="Brouillon", niveau=0,
                                        approbations=[], derogation_dg=False,
                                        historique=_hist(d, u, "Modification : validations remises à zéro")))


def soumettre(id_: str, accepter_alertes: bool = False) -> list[str]:
    """N0 : contrôle du stock disponible et du budget ; crée l'engagement prévisionnel. Renvoie les alertes."""
    u = S.acteur("demandes_achat")
    with db.transaction("Soumission de la demande d’achat (N0)") as t:
        d = _demande(t, id_, True)
        if d["demandeur"] != u["id"] or d["statut"] != "Brouillon":
            raise ValueError("Seul le demandeur soumet sa demande en brouillon.")
        erreurs, alertes = [], []
        for l in lignes_demande(t, id_):
            a = _un(t, "stk_articles", l["article"])
            if a["a_qualifier"]:
                erreurs.append(f"ligne {l['numero']} : article {a['code']} à qualifier par les achats avant soumission")
            if a["nature"] == "stocke" and not l["motif_hors_stock"]:
                dispo = sum((x["disponible"] for x in S.disponibilites(a["id"], t)
                             if x["type"] == "central" or x["magasin"] == d["magasin"]), Decimal(0))
                if dispo > 0:
                    erreurs.append(f"ligne {l['numero']} : {dispo.normalize():f} {a['unite_stock']} de {a['code']} "
                                   "disponibles en stock (bon de sortie, ou motif d’achat malgré le stock)")
        if erreurs:
            raise ValueError("Soumission refusée : " + " ; ".join(erreurs) + ".")
        alertes = _alertes_budget(t, d)
        if alertes and not accepter_alertes:
            raise ValueError("Alertes budgétaires à confirmer : " + " ; ".join(alertes))
        _maj(t, "ach_demandes", d, dict(statut="Soumise", niveau=0, approbations=[],
                                        historique=_hist(d, u, "Soumission N0", " ; ".join(alertes))))
        return alertes


def _alertes_budget(t, d: dict, hors_demande: bool = True) -> list[str]:
    """Taux d'engagement par poste avec cette demande (seuils de la politique V7, dynamiques)."""
    b = V.budget_for(d["projet"], t)
    m = V.metrics(b, V.records("operation", t), tx=t)
    seuils = V.policy(t)["thresholds"]
    besoin: dict[str, int] = {}
    for l in lignes_demande(t, d["id"]):
        besoin[l["poste"]] = besoin.get(l["poste"], 0) + cents(D(l["quantite"]) * l["prix_estime"])
    deja = d["statut"] in ("Soumise", "Approuvée")      # sa propre part est déjà dans les métriques
    out = []
    for x in m["lines"]:
        if x["code"] not in besoin or not x["budget"]:
            continue
        engage = x["open"] + x["cost"] + (0 if deja else besoin[x["code"]])
        taux = 100 * engage / x["budget"]
        franchis = [s for s in seuils if taux >= s]
        if franchis:
            out.append(f"poste {x['code']} engagé à {taux:.0f} % (seuil {max(franchis)} %)")
    return out


def approuver(id_: str, commentaire: str, rejeter: bool = False, derogation: bool = False) -> None:
    """N1 → N2 → N3 → DG selon la politique V7 (niveaux, délégations datées et plafonnées)."""
    u = V.actor()
    with db.transaction("Validation de la demande d’achat") as t:
        d = _demande(t, id_, True)
        niveaux = V.policy(t)["levels"]
        if d["statut"] != "Soumise" or d["niveau"] >= len(niveaux):
            raise ValueError("Aucune validation en attente.")
        niveau = niveaux[d["niveau"]]
        montant = montant_estime(t, id_)
        if not V.authorized_level(u, niveau, d["projet"], d["devise"], montant, t):
            raise ValueError(f"Niveau {niveau} ou délégation non autorisé.")
        if not auth.sur_chantier(u, d["projet"], t):
            raise ValueError("Chantier hors de votre périmètre.")
        DR.exiger_distinct(t, u["id"], {d["demandeur"], *[a["user"] for a in d["approbations"]]},
                           "validateur_distinct", "un autre validateur est requis à chaque niveau")
        if not (commentaire or "").strip():
            raise ValueError("Commentaire de contrôle obligatoire.")
        if rejeter:
            _maj(t, "ach_demandes", d, dict(statut="Brouillon", niveau=0, approbations=[],
                                            historique=_hist(d, u, f"Rejet {niveau}", commentaire)))
            return
        if derogation and niveau != niveaux[-1]:
            raise ValueError("Seul le dernier niveau (DG) autorise un dépassement.")
        if niveau == niveaux[-1]:
            b = V.budget_for(d["projet"], t)
            m = V.metrics(b, V.records("operation", t), tx=t)
            besoin: dict[str, int] = {}
            for l in lignes_demande(t, id_):
                besoin[l["poste"]] = besoin.get(l["poste"], 0) + cents(D(l["quantite"]) * l["prix_estime"])
            depasse = [x["code"] for x in m["lines"] if x["code"] in besoin and x["available"] < 0]
            if depasse and not derogation:
                raise ValueError(f"Seuil 100 % dépassé sur {', '.join(depasse)} : dérogation DG explicite requise.")
        approbations = list(d["approbations"]) + [dict(user=u["id"], nom=u["nom"], niveau=niveau, motif=commentaire,
                                                       at=db.maintenant().isoformat())]
        statut = "Approuvée" if len(approbations) == len(niveaux) else "Soumise"
        _maj(t, "ach_demandes", d, dict(statut=statut, niveau=len(approbations), approbations=approbations,
                                        derogation_dg=bool(derogation) or d["derogation_dg"],
                                        historique=_hist(d, u, f"Approbation {niveau}" + (" avec dérogation" if derogation else ""),
                                                         commentaire)))


def annuler_demande(id_: str, motif: str) -> None:
    u = V.actor()
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    with db.transaction("Annulation de la demande d’achat") as t:
        d = _demande(t, id_, True)
        if u["id"] != d["demandeur"] and not V.peut(u, "approbation_dg"):
            raise ValueError("Annulation par le demandeur ou la DG.")
        if d["statut"] == "Annulée" or any(_quantites(t, l["id"])["commande"] for l in lignes_demande(t, id_)):
            raise ValueError("Demande déjà annulée ou commandée : clôturez ses lignes restantes.")
        _maj(t, "ach_demandes", d, dict(statut="Annulée", historique=_hist(d, u, "Annulation", motif)))


def cloturer_ligne(ligne: str, motif: str) -> None:
    """Clôture motivée d'une ligne non livrée : libère l'engagement restant."""
    u = V.actor()
    if not (V.peut(u, "chiffrage_achats") or V.peut(u, "approbation_dg")):
        raise ValueError("Clôture réservée aux achats ou à la DG.")
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    with db.transaction("Clôture de ligne de demande d’achat") as t:
        l = _un(t, "ach_demande_lignes", ligne, True)
        if not l or l["cloturee"]:
            raise ValueError("Ligne introuvable ou déjà clôturée.")
        t.cx.execute(T("ach_demande_lignes").update().where(T("ach_demande_lignes").c.id == ligne).values(
            cloturee=True, motif_cloture=motif.strip()))
        t._auditer("Modification", "ach_demande_lignes", ligne, {"cloturee": False}, {"cloturee": True, "motif": motif})
        d = _demande(t, l["demande"], True)
        _maj(t, "ach_demandes", d, dict(historique=_hist(d, u, f"Clôture ligne {l['numero']}", motif)))


# ------------------------------------------------------------------ 4. bon de commande
def commander(fournisseur: str, devise: str, date_: str, lignes: list[dict], devis: list[dict] | None = None,
              conditions: str = "") -> str:
    """Lignes approuvées (une ou plusieurs demandes) d'un même fournisseur. lignes : demande_ligne, quantite,
    prix_unitaire (centimes, devise de la commande), magasin (articles stockés)."""
    u = S.acteur("chiffrage_achats", "Émission des commandes réservée aux achats.")
    V.date(date_)
    if devise not in R.CURRENCIES or not lignes:
        raise ValueError("Devise et au moins une ligne requises.")
    with db.transaction("Bon de commande") as t:
        c = t.get("clients", fournisseur)
        if not c or c.get("archived") or not set(R.party_roles(c)) & {"supplier", "subcontractor"}:
            raise ValueError("Fournisseur introuvable, archivé ou sans rôle fournisseur.")
        tol_prix = _tolerance(t, "tolerance_prix_pct")
        p = parametres(t)
        rows, total = [], 0
        for i, x in enumerate(lignes, 1):
            dl = _un(t, "ach_demande_lignes", x["demande_ligne"], True)
            if not dl:
                raise ValueError(f"Ligne {i} : ligne de demande introuvable.")
            d = _demande(t, dl["demande"])
            if d["statut"] != "Approuvée" or dl["cloturee"]:
                raise ValueError(f"Ligne {i} : la demande {d['numero']} n’est pas approuvée ou la ligne est clôturée.")
            if not auth.sur_chantier(u, d["projet"], t) and u.get("role") != "admin" and auth.projets_de(u["id"], t):
                raise ValueError(f"Ligne {i} : chantier hors de votre périmètre.")
            q = qte(x["quantite"], f"Ligne {i} : quantité")
            deja = _quantites(t, dl["id"])["commande"]
            if deja + q > D(dl["quantite"]):
                raise ValueError(f"Ligne {i} : quantité supérieure à la quantité approuvée restante "
                                 f"({(D(dl['quantite']) - deja).normalize():f}).")
            prix = V.amount(int(x["prix_unitaire"]))
            taux_b = DV.taux(devise, d["devise"], date_, V.records("rate", t))
            if taux_b is None:
                raise ValueError(f"Aucun taux {devise} → {d['devise']} enregistré au {date_} : saisissez le taux du jour.")
            prix_b = Decimal(prix) * taux_b["taux"]
            if prix_b > Decimal(dl["prix_estime"]) * (1 + tol_prix):
                raise ValueError(f"Ligne {i} : prix supérieur à l’estimation approuvée au-delà de la tolérance : "
                                 "modifiez la demande (nouvelle validation).")
            art = _un(t, "stk_articles", dl["article"])
            mag = x.get("magasin") or d["magasin"]
            if art["nature"] == "stocke" and not mag:
                raise ValueError(f"Ligne {i} : magasin de destination requis pour un article stocké.")
            montant = cents(q * prix)
            total += montant
            rows.append(dict(id=db.nouvel_id(), demande_ligne=dl["id"], magasin=mag if art["nature"] == "stocke" else None,
                             quantite=q, prix_unitaire=prix, taux_budget=str(taux_b["taux"]),
                             montant_budget=cents(q * prix_b)))
        seuil = (p.get("seuil_devis") or {}).get(devise)
        devis = [x for x in (devis or []) if (x.get("fournisseur") or "").strip() and (x.get("reference") or "").strip()]
        if seuil is not None and total > seuil and len(devis) < int(p.get("nb_devis") or 1):
            raise ValueError(f"Mise en concurrence : {p.get('nb_devis')} devis exigés au-delà de "
                             f"{R.money(seuil, devise)} ; {len(devis)} fourni(s).")
        id_ = db.nouvel_id()
        t.inserer("ach_commandes", dict(id=id_, numero=numero(t, "ach_commandes", "BC", date_), fournisseur=fournisseur,
                                        devise=devise, date=date_, statut="Émise", devis=devis, conditions=conditions,
                                        historique=_hist({}, u, "Émission"), cree_par=u["id"], cree_le=db.maintenant(),
                                        version=1))
        for r in rows:
            t.inserer("ach_commande_lignes", dict(commande=id_, **r))
        return id_


def annuler_commande(id_: str, motif: str) -> None:
    u = V.actor()
    if not (V.peut(u, "chiffrage_achats") or V.peut(u, "approbation_dg")) or not (motif or "").strip():
        raise ValueError("Annulation par les achats ou la DG, avec motif.")
    with db.transaction("Annulation de commande") as t:
        c = _un(t, "ach_commandes", id_, True)
        if not c or c["statut"] != "Émise":
            raise ValueError("Commande introuvable ou déjà annulée.")
        if t.cx.execute(sa.select(T("ach_receptions").c.id).where(T("ach_receptions").c.commande == id_)).first():
            raise ValueError("Commande déjà réceptionnée : clôturez les lignes restantes.")
        _maj(t, "ach_commandes", c, dict(statut="Annulée", historique=_hist(c, u, "Annulation", motif)))


def lignes_commande(tx, commande: str) -> list[dict]:
    return _lignes(tx, "ach_commande_lignes", T("ach_commande_lignes").c.commande == commande)


# ------------------------------------------------------------------ 5. réception
def receptionner(commande: str, date_: str, bl: str, lignes: list[dict]) -> str:
    """lignes : commande_ligne, qte_acceptee, qte_rejetee, motif. Entrée en stock (articles stockés) ou coût
    réalisé (non stocké, prestation = attestation de service fait)."""
    u = S.acteur("magasin", "Réception réservée au magasin ou au réceptionnaire désigné.")
    V.date(date_)
    if not (bl or "").strip():
        raise ValueError("Bon de livraison (ou attestation de service fait) requis.")
    with db.transaction("Réception") as t:
        c = _un(t, "ach_commandes", commande, True)
        if not c or c["statut"] != "Émise":
            raise ValueError("Commande introuvable ou annulée.")
        tol = _tolerance(t, "tolerance_qte_pct")
        par_id = {x["id"]: x for x in lignes_commande(t, commande)}
        id_ = db.nouvel_id()
        t.inserer("ach_receptions", dict(id=id_, numero=numero(t, "ach_receptions", "BR", date_), commande=commande,
                                         date=date_, bl=bl.strip(), statut="Validée", cree_par=u["id"],
                                         cree_le=db.maintenant(), version=1))
        utiles = 0
        for x in lignes:
            cl = par_id.get(x["commande_ligne"])
            if not cl:
                raise ValueError("Ligne étrangère à cette commande.")
            acc = qte(x.get("qte_acceptee") or 0, "Quantité acceptée", True)
            rej = qte(x.get("qte_rejetee") or 0, "Quantité rejetée", True)
            if not acc and not rej:
                continue
            if rej and not (x.get("motif") or "").strip():
                raise ValueError("Motif du rejet obligatoire.")
            dl = _un(t, "ach_demande_lignes", cl["demande_ligne"])
            d = _demande(t, dl["demande"])
            DR.exiger_distinct(t, u["id"], {d["demandeur"]}, "receptionnaire_demandeur",
                               "le réceptionnaire est différent du demandeur", date_)
            deja = sum((D(r["qte_acceptee"]) for r in _lignes(t, "ach_reception_lignes",
                                                               T("ach_reception_lignes").c.commande_ligne == cl["id"])),
                       Decimal(0))
            if deja + acc > D(cl["quantite"]) * (1 + tol):
                raise ValueError(f"Quantité reçue cumulée supérieure à la commande (tolérance {tol * 100:.0f} %).")
            art = _un(t, "stk_articles", dl["article"])
            mvt, cout_b = None, 0
            if acc and art["nature"] == "stocke":
                mvt = S.entree(t, u, art["id"], cl["magasin"], acc, cents(acc * cl["prix_unitaire"]), c["devise"],
                               date_, "reception", id_)
            elif acc:
                cout_b = cents(acc * Decimal(cl["montant_budget"]) / D(cl["quantite"]))
            t.inserer("ach_reception_lignes", dict(id=db.nouvel_id(), reception=id_, commande_ligne=cl["id"],
                                                   qte_acceptee=acc, qte_rejetee=rej,
                                                   motif_rejet=(x.get("motif") or "").strip() or None, mouvement=mvt,
                                                   cout_budget=cout_b))
            utiles += 1
        if not utiles:
            raise ValueError("Aucune quantité reçue ni rejetée.")
        return id_


# ------------------------------------------------------------------ 6. facture fournisseur (rapprochement à 3 voies)
def enregistrer_facture(fournisseur: str, reference: str, date_: str, echeance: str, devise: str, montant_ht: int,
                        tva: int, lignes: list[dict]) -> str:
    """lignes : commande_ligne, quantite, prix_unitaire. Contrôles : quantité facturée ≤ reçue, prix = commandé
    (tolérance), total ≤ engagement, référence unique par fournisseur."""
    u = S.acteur("factures_achat", "Saisie des factures d’achat réservée à la comptabilité fournisseurs.")
    V.date(date_)
    V.date(echeance)
    V.amount(montant_ht, True)
    V.amount(tva)
    if not (reference or "").strip():
        raise ValueError("Référence de la facture obligatoire.")
    with db.transaction("Facture d’achat") as t:
        tol = _tolerance(t, "tolerance_prix_pct")
        total, engagement, propres = 0, 0, []
        for i, x in enumerate(lignes, 1):
            cl = _un(t, "ach_commande_lignes", x["commande_ligne"])
            if not cl:
                raise ValueError(f"Ligne {i} : ligne de commande introuvable.")
            c = _un(t, "ach_commandes", cl["commande"])
            if c["fournisseur"] != fournisseur or c["devise"] != devise or c["statut"] != "Émise":
                raise ValueError(f"Ligne {i} : commande d’un autre fournisseur, d’une autre devise ou annulée.")
            q = qte(x["quantite"], f"Ligne {i} : quantité")
            prix = V.amount(int(x["prix_unitaire"]))
            recu = sum((D(r["qte_acceptee"]) for r in _lignes(t, "ach_reception_lignes",
                                                               T("ach_reception_lignes").c.commande_ligne == cl["id"])),
                       Decimal(0))
            deja = Decimal(0)
            for fl in _lignes(t, "ach_facture_lignes", T("ach_facture_lignes").c.commande_ligne == cl["id"]):
                if _un(t, "ach_factures", fl["facture"])["statut"] != "Rejetée":
                    deja += D(fl["quantite"])
            if deja + q > recu:
                raise ValueError(f"Ligne {i} : quantité facturée supérieure à la quantité reçue ({(recu - deja).normalize():f}).")
            if abs(Decimal(prix) - cl["prix_unitaire"]) > Decimal(cl["prix_unitaire"]) * tol:
                raise ValueError(f"Ligne {i} : prix différent du prix commandé au-delà de la tolérance.")
            total += cents(q * prix)
            engagement += cents(D(cl["quantite"]) * cl["prix_unitaire"])
            propres.append(dict(commande_ligne=cl["id"], quantite=q, prix_unitaire=prix))
        if not propres:
            raise ValueError("Au moins une ligne rapprochée.")
        if total != montant_ht:
            raise ValueError(f"Total des lignes ({R.money(total, devise)}) différent du montant HT saisi.")
        if total > engagement * (1 + tol):
            raise ValueError("Facture supérieure à l’engagement des commandes.")
        id_ = db.nouvel_id()
        try:
            with t.cx.begin_nested():
                t.inserer("ach_factures", dict(id=id_, fournisseur=fournisseur, reference=reference.strip(), date=date_,
                                               echeance=echeance, devise=devise, montant_ht=montant_ht, tva=tva,
                                               statut="Enregistrée", paiements=[], historique=_hist({}, u, "Saisie"),
                                               cree_par=u["id"], cree_le=db.maintenant(), version=1))
        except sa.exc.IntegrityError:
            raise ValueError("Facture déjà enregistrée pour ce fournisseur (référence unique).") from None
        for p in propres:
            t.inserer("ach_facture_lignes", dict(id=db.nouvel_id(), facture=id_, ecart_budget=0, **p))
        return id_


def valider_facture(id_: str, commentaire: str, rejeter: bool = False) -> None:
    u = S.acteur("factures_achat", "Validation des factures réservée à la comptabilité fournisseurs.")
    if not (commentaire or "").strip():
        raise ValueError("Commentaire de contrôle obligatoire.")
    with db.transaction("Validation de facture d’achat") as t:
        f = _un(t, "ach_factures", id_, True)
        if not f or f["statut"] != "Enregistrée":
            raise ValueError("Facture introuvable ou déjà traitée.")
        DR.exiger_distinct(t, u["id"], {f["cree_par"]}, "saisie_validation_facture",
                           "celui qui saisit la facture ne la valide pas")
        fl = _lignes(t, "ach_facture_lignes", T("ach_facture_lignes").c.facture == id_)
        acheteurs = {_un(t, "ach_commandes", _un(t, "ach_commande_lignes", x["commande_ligne"])["commande"])["cree_par"]
                     for x in fl}
        DR.exiger_distinct(t, u["id"], acheteurs, "acheteur_facture", "l’acheteur qui a émis la commande ne valide pas "
                                                                       "la facture")
        if rejeter:
            _maj(t, "ach_factures", f, dict(statut="Rejetée", historique=_hist(f, u, "Rejet", commentaire)))
            return
        import comptabilisation as CPT
        lignes_cpt = []
        for x in fl:
            cl = _un(t, "ach_commande_lignes", x["commande_ligne"])
            dl = _un(t, "ach_demande_lignes", cl["demande_ligne"])
            art = _un(t, "stk_articles", dl["article"])
            d_ = _demande(t, dl["demande"])
            ht = cents(D(x["quantite"]) * x["prix_unitaire"])
            ht_tenue, taux_f = CPT.vers_tenue(t, ht, f["devise"], f["date"])
            lignes_cpt.append(dict(ht=ht_tenue, devise=f["devise"], montant_devise=ht, taux=taux_f, projet=d_["projet"],
                                   poste=dl["poste"], libelle_ligne=f"{art['code']} × {D(x['quantite']).normalize():f}",
                                   **S._comptes_famille(t, art)))
            ecart = cents(D(x["quantite"]) * (x["prix_unitaire"] - cl["prix_unitaire"]))
            if not ecart:
                continue
            if art["nature"] == "stocke" and D(art["qte_totale"]) > 0:
                v, _ = S.vers_tenue(abs(ecart), f["devise"], f["date"], t)
                S.ajuster_valeur(t, u, art["id"], v if ecart > 0 else -v, f["date"], "facture", id_)
            else:          # article déjà sorti ou non stocké : écart en charge du poste DQE
                d = _demande(t, dl["demande"])
                v = DV.convertir(abs(ecart), f["devise"], d["devise"], f["date"], V.records("rate", t))
                if v is None:
                    raise ValueError(f"Aucun taux {f['devise']} → {d['devise']} au {f['date']}.")
                t.cx.execute(T("ach_facture_lignes").update().where(T("ach_facture_lignes").c.id == x["id"]).values(
                    ecart_budget=v if ecart > 0 else -v))
        # Écriture ACH (charge par famille et analytique chantier, TVA saisie, dette fournisseur)
        tva_tenue, taux_f = CPT.vers_tenue(t, f["tva"], f["devise"], f["date"])
        ttc_tenue = sum(l["ht"] for l in lignes_cpt) + tva_tenue
        CPT.comptabiliser(t, "achat_facture", f["date"], f"Facture {f['reference']}", "ach_facture", id_,
                          dict(tva=tva_tenue, ttc=ttc_tenue, tiers=f["fournisseur"], devise=f["devise"],
                               montant_devise=f["montant_ht"] + f["tva"], taux=taux_f, echeance=f["echeance"]),
                          lignes_cpt)
        _maj(t, "ach_factures", f, dict(statut="Validée", valide_par=u["id"], valide_le=db.maintenant(),
                                        historique=_hist(f, u, "Validation (rapprochement à 3 voies)", commentaire)))


# ------------------------------------------------------------------ 7. paiement (trésorerie V7)
def payer(id_: str, compte: str, montant: int, date_: str, reference: str) -> None:
    u = V.actor(["admin", "finance"])
    if not V.peut(u, "tresorerie"):
        raise ValueError("Paiement réservé à la trésorerie.")
    V.amount(montant, True)
    V.date(date_)
    with db.transaction("Paiement de facture d’achat") as t:
        f = _un(t, "ach_factures", id_, True)
        if not f or f["statut"] != "Validée":
            raise ValueError("Facture non validée.")
        a = V.get(t, compte, "account")
        if a["currency"] != f["devise"]:
            raise ValueError("Compte d’une autre devise : aucune conversion implicite.")
        paye = sum(p["montant"] for p in f["paiements"] if not p.get("annule"))
        if paye + montant > f["montant_ht"] + f["tva"]:
            raise ValueError("Paiement supérieur au reste dû.")
        acteurs = {f["valide_par"], f["cree_par"]}
        for x in _lignes(t, "ach_facture_lignes", T("ach_facture_lignes").c.facture == id_):
            dl = _un(t, "ach_demande_lignes", _un(t, "ach_commande_lignes", x["commande_ligne"])["demande_ligne"])
            d = _demande(t, dl["demande"])
            acteurs |= {d["demandeur"], *[ap["user"] for ap in d["approbations"]]}
        DR.exiger_distinct(t, u["id"], acteurs, "tresorier_distinct",
                           "le trésorier est distinct du demandeur, des validateurs et de la comptabilité fournisseurs")
        if V.balance(a, t) < montant:
            raise ValueError("Solde insuffisant sur le compte.")
        V.insert(t, "payment", reference, "", f["devise"], dict(facture_achat=id_, account=compte, amount=montant,
                                                               date=date_))
        V._touch_account(t, a)
        pid = db.nouvel_id()
        V._move(t, a, pid, "", date_, montant, "out", f"Facture {f['reference']} {reference}")
        # Écriture BQ : la dette est soldée au taux de la facture, la trésorerie au taux du paiement ; l'écart
        # de change va en 676 (perte) ou 776 (gain).
        import comptabilisation as CPT
        ttc = f["montant_ht"] + f["tva"]
        ttc_tenue = sum(int(l["debit"]) for l in t.lire(
            "select l.debit from cpt_lignes l join cpt_pieces p on p.id = l.piece "
            "where p.source_type = 'ach_facture' and p.source_id = :i", i=id_))
        dette = cents(Decimal(montant) * ttc_tenue / ttc) if ttc else 0
        tresor, taux_p = CPT.vers_tenue(t, montant, f["devise"], date_)
        ecart = tresor - dette
        CPT.comptabiliser(t, "achat_paiement", date_, f"Paiement {f['reference']} ({reference})", "ach_paiement", pid,
                          dict(dette=dette, tresorerie=tresor, perte_change=max(0, ecart), gain_change=max(0, -ecart),
                               tiers=f["fournisseur"], devise=f["devise"], montant_devise=montant, taux=taux_p,
                               centre="FINANCE"),
                          journal=CPT.journal_tresorerie(t, a))
        paiements = list(f["paiements"]) + [dict(id=pid, ref=reference, montant=montant, date=date_, compte=compte,
                                                 user=u["id"])]
        _maj(t, "ach_factures", f, dict(paiements=paiements, historique=_hist(f, u, "Paiement", reference)))


# ------------------------------------------------------------------ consultation
def demandes(u: dict | None = None) -> list[dict]:
    rows = _lignes(None, "ach_demandes")
    if u is None or u.get("role") == "admin" or V.peut(u, "chiffrage_achats") or V.peut(u, "factures_achat"):
        return rows
    return [r for r in rows if auth.sur_chantier(u, r["projet"])]


def a_valider(u: dict) -> list[dict]:
    niveaux = V.policy()["levels"]
    out = []
    for d in demandes(u):
        if d["statut"] != "Soumise" or d["niveau"] >= len(niveaux) or u["id"] == d["demandeur"]:
            continue
        if any(a["user"] == u["id"] for a in d["approbations"]):
            continue
        if V.peut(u, V.APPROB[niveaux[d["niveau"]]]):
            out.append(d)
    return out


def lignes_a_commander(u: dict | None = None) -> list[dict]:
    """Lignes approuvées avec une quantité restant à commander (base des bons de commande regroupés)."""
    out = []
    for d in _lignes(None, "ach_demandes", T("ach_demandes").c.statut == "Approuvée"):
        for l in lignes_demande(None, d["id"]):
            if l["cloturee"]:
                continue
            reste = D(l["quantite"]) - _quantites(None, l["id"])["commande"]
            if reste > 0:
                out.append({**l, "reste": reste, "demande_numero": d["numero"], "projet": d["projet"],
                            "devise": d["devise"], "magasin_demande": d["magasin"]})
    return out


def lignes_a_recevoir(commande: str) -> list[dict]:
    out = []
    for cl in lignes_commande(None, commande):
        recu = sum((D(r["qte_acceptee"]) for r in _lignes(None, "ach_reception_lignes",
                                                           T("ach_reception_lignes").c.commande_ligne == cl["id"])), Decimal(0))
        out.append({**cl, "recu": recu, "reste": D(cl["quantite"]) - recu})
    return out


def lignes_a_facturer(fournisseur: str) -> list[dict]:
    out = []
    for c in _lignes(None, "ach_commandes", T("ach_commandes").c.fournisseur == fournisseur,
                     T("ach_commandes").c.statut == "Émise"):
        for cl in lignes_commande(None, c["id"]):
            recu = sum((D(r["qte_acceptee"]) for r in _lignes(None, "ach_reception_lignes",
                                                               T("ach_reception_lignes").c.commande_ligne == cl["id"])),
                       Decimal(0))
            facture = Decimal(0)
            for fl in _lignes(None, "ach_facture_lignes", T("ach_facture_lignes").c.commande_ligne == cl["id"]):
                if db.un("ach_factures", fl["facture"])["statut"] != "Rejetée":
                    facture += D(fl["quantite"])
            if recu > facture:
                out.append({**cl, "commande_numero": c["numero"], "devise": c["devise"], "a_facturer": recu - facture})
    return out


def chaine(demande: str) -> dict:
    """Liens amont / aval d'une demande : commandes, réceptions, factures, paiements, mouvements de stock."""
    cmds, recs, facs, mvts = {}, {}, {}, []
    for l in lignes_demande(None, demande):
        for cl in _lignes(None, "ach_commande_lignes", T("ach_commande_lignes").c.demande_ligne == l["id"]):
            cmds[cl["commande"]] = db.un("ach_commandes", cl["commande"])
            for rl in _lignes(None, "ach_reception_lignes", T("ach_reception_lignes").c.commande_ligne == cl["id"]):
                recs[rl["reception"]] = db.un("ach_receptions", rl["reception"])
                if rl["mouvement"]:
                    mvts.append(db.un("stk_mouvements", rl["mouvement"]))
            for fl in _lignes(None, "ach_facture_lignes", T("ach_facture_lignes").c.commande_ligne == cl["id"]):
                facs[fl["facture"]] = db.un("ach_factures", fl["facture"])
    return dict(commandes=list(cmds.values()), receptions=list(recs.values()), factures=list(facs.values()),
                mouvements=mvts)


# ------------------------------------------------------------------ reprise du circuit transitoire (16 octobre)
def reprendre_transitoires(execute: bool = False) -> list[dict]:
    """Demandes du circuit transitoire encore ouvertes (non transmises au V7) reprises en brouillon dans le circuit
    V8, au nom de leur demandeur. Les articles libres sont rapprochés du référentiel par libellé, ou créés
    « à qualifier » (famille A_QUALIFIER) : la soumission reste bloquée jusqu'à leur qualification par les achats.
    Sans execute : aperçu seulement. Avec execute : réservé à la DG."""
    ouverts = ("Brouillon", "Soumise", "Rejetée", "Validée chantier", "À valider coordonnateur")
    a_reprendre = [r for r in V.records("purchase_request") if r["data"].get("statut") in ouverts]
    apercu = [dict(id=r["id"], ref=r["ref"], projet=r["project"], statut=r["data"]["statut"],
                   lignes=len(r["data"]["lignes"])) for r in a_reprendre]
    if not execute:
        return apercu
    u = S.acteur("approbation_dg", "Reprise réservée à la DG.")
    with db.transaction("Reprise des demandes d’achat transitoires") as t:
        if not t.cx.execute(sa.select(T("stk_familles")).where(T("stk_familles").c.code == "A_QUALIFIER")).first():
            t.cx.execute(T("stk_familles").insert().values(code="A_QUALIFIER", libelle="Articles à qualifier (reprise)",
                                                           compte_stock="", compte_charge="605", compte_variation="",
                                                           actif=True, cree_par=u["id"], cree_le=db.maintenant(), version=1))
        index = {R.normaliser(a["libelle"]): a["id"] for a in S.articles(tx=t)}
        for r in a_reprendre:
            d = r["data"]
            demandeur = t.get("users", d["creator"])
            lignes = []
            for l in d["lignes"]:
                cle = R.normaliser(l["article"])
                if cle not in index:
                    n = len(index) + 1
                    index[cle] = S._enregistrer_article_tx(t, u, f"AQ-{n:05d}", l["article"], "A_QUALIFIER",
                                                           "non_stocke", l.get("unite") or "u", a_qualifier=True)
                lignes.append(dict(article=index[cle], poste=l["post"], quantite=l["quantite"],
                                   prix_estime=l.get("prix") or 0, fournisseur=l.get("fournisseur") or None,
                                   note=l.get("note") or None))
            mag = S.magasin_du_chantier(r["project"], t) or next(
                (m for m in S.magasins(True, t) if m["type"] == "central"), None)
            _creer_demande_tx(t, demandeur, r["project"], max(d["date_besoin"], R.today()), mag["id"] if mag else None,
                              "Normale", d["objet"], lignes, origine=f"reprise {r['ref']}")
            nd = deepcopy(d)
            nd["statut"] = "Reprise V8"
            V.event(nd, u, "Reprise dans le circuit d’achat V8")
            V.save(t, V.get(t, r["id"]), nd)
    return apercu
