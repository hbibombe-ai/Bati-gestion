"""Comptabilisation automatique (mémo V8, § 2 à § 3) : seul module qui écrit dans cpt_pieces et cpt_lignes.

Chaque événement métier (entrée ou sortie de stock, écart de prix, facture d'achat validée, paiement) produit sa
pièce dans la même transaction que l'opération, à partir de la règle comptable active de l'événement
(table regles_comptables, versionnée, proposée par la Finance et activée par la DG). Si la pièce ne peut pas être
produite — compte absent ou inactif, taux de change absent à la date, période clôturée, pièce déséquilibrée —
l'opération est refusée.

Monnaie de tenue : paramètre DG (stocks.devise_tenue). Chaque ligne garde sa devise et son montant d'origine ;
le montant en monnaie de tenue vient du taux historique enregistré à la date, jamais estimé.

Une règle est une liste de « postes » : {sens D|C, compte (numéro ou {gabarit}), montant (clé), par document|ligne,
tiers (bool), analytique (bool)}. Un montant négatif inverse le sens. Les gabarits {compte_stock},
{compte_variation}, {compte_charge}, {compte_tresorerie} se résolvent depuis la famille de l'article ou le journal.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

import auth
import db
import devises as DV
import gestion_v7 as V
import regles as R

STATUTS_PERIODE = ("Ouverte", "Clôturée provisoirement", "Clôturée définitivement")
TYPES_JOURNAL = {"ACH": "Achats", "VTE": "Ventes", "BQ": "Banque", "CA": "Caisse", "MM": "Mobile money", "PAI": "Paie",
                 "STK": "Stocks", "IMM": "Immobilisations", "OD": "Opérations diverses", "AN": "À-nouveaux"}

# Comptes utilisés par les règles par défaut du mémo (§ 3.2) ; le plan SYSCOHADA complet s'importe à part.
COMPTES_DEFAUT = [
    ("32", "Matières premières et fournitures liées", False), ("33", "Autres approvisionnements", False),
    ("401", "Fournisseurs, dettes en compte", True), ("445", "État, TVA récupérable", False),
    ("521", "Banques locales", False), ("57", "Caisse", False), ("55", "Instruments de monnaie électronique", False),
    ("602", "Achats de matières premières et fournitures liées", False),
    ("604", "Achats stockés de matières et fournitures consommables", False), ("605", "Autres achats", False),
    ("6032", "Variations des stocks de matières premières et fournitures liées", False),
    ("6033", "Variations des stocks d’autres approvisionnements", False),
    ("676", "Pertes de change", False), ("776", "Gains de change", False),
    ("411", "Clients", True), ("4091", "Fournisseurs, avances et acomptes versés", True),
    ("471", "Comptes d’attente", False), ("581", "Régies d’avances et accréditifs", False),
    ("585", "Virements de fonds", False),
    ("658", "Charges diverses", False), ("758", "Produits divers", False),
]
JOURNAUX_DEFAUT = [("ACH", "Achats", "ACH"), ("STK", "Stocks", "STK"), ("OD", "Opérations diverses", "OD")]


def _p(sens, compte, montant, par="document", tiers=False, analytique=False):
    return dict(sens=sens, compte=compte, montant=montant, par=par, tiers=tiers, analytique=analytique)


REGLES_DEFAUT = {
    "stock_entree": ("STK", "Entrée en stock (réception acceptée)",
                     [_p("D", "{compte_stock}", "valeur", "ligne"), _p("C", "{compte_variation}", "valeur", "ligne")]),
    "stock_sortie": ("STK", "Sortie pour consommation chantier",
                     [_p("D", "{compte_variation}", "valeur", "ligne", analytique=True),
                      _p("C", "{compte_stock}", "valeur", "ligne")]),
    "stock_ecart_prix": ("STK", "Écart de prix facturé porté sur le stock",
                         [_p("D", "{compte_stock}", "valeur", "ligne"), _p("C", "{compte_variation}", "valeur", "ligne")]),
    "achat_facture": ("ACH", "Facture fournisseur (rapprochement à 3 voies)",
                      [_p("D", "{compte_charge}", "ht", "ligne", analytique=True), _p("D", "445", "tva"),
                       _p("C", "401", "ttc", tiers=True)]),
    "achat_paiement": ("BQ", "Paiement fournisseur",
                       [_p("D", "401", "dette", tiers=True), _p("D", "676", "perte_change"),
                        _p("C", "{compte_tresorerie}", "tresorerie"), _p("C", "776", "gain_change")]),
    # Circuit financier V7
    "v7_facture": ("ACH", "Facture d’une opération V7",
                   [_p("D", "{compte_charge}", "montant", analytique=True), _p("C", "401", "montant", tiers=True)]),
    "v7_paiement": ("BQ", "Paiement d’une opération V7 facturée",
                    [_p("D", "401", "dette", tiers=True), _p("D", "676", "perte_change"),
                     _p("C", "{compte_tresorerie}", "tresorerie"), _p("C", "776", "gain_change")]),
    "v7_avance": ("BQ", "Avance de régie versée",
                  [_p("D", "581", "montant"), _p("C", "{compte_tresorerie}", "montant")]),
    "v7_justification": ("OD", "Justificatif d’avance accepté",
                         [_p("D", "{compte_charge}", "montant", analytique=True), _p("C", "581", "montant")]),
    "v7_restitution": ("BQ", "Restitution du reliquat d’avance",
                       [_p("D", "{compte_tresorerie}", "montant"), _p("C", "581", "montant")]),
    "v7_virement_depart": ("BQ", "Virement entre comptes (départ)",
                           [_p("D", "585", "montant"), _p("C", "{compte_tresorerie}", "montant")]),
    "v7_virement_arrivee": ("BQ", "Virement entre comptes (arrivée)",
                            [_p("D", "{compte_tresorerie}", "montant"), _p("C", "585", "montant")]),
    "v7_ouverture": ("BQ", "Solde initial d’un compte de trésorerie",
                     [_p("D", "{compte_tresorerie}", "montant"), _p("C", "{compte_ouverture}", "montant")]),
    # Trésorerie historique (journal de caisse, dépenses, règlements hors circuit V7)
    "tresorerie_depense": ("BQ", "Dépense directe sans facture fournisseur",
                           [_p("D", "{compte_charge}", "montant", analytique=True),
                            _p("C", "{compte_tresorerie}", "montant")]),
    "tresorerie_client": ("BQ", "Encaissement client",
                          [_p("D", "{compte_tresorerie}", "montant"), _p("C", "411", "montant", tiers=True)]),
    "tresorerie_fournisseur": ("BQ", "Règlement ou avance fournisseur hors circuit V7",
                               [_p("D", "{compte_fournisseur}", "montant", tiers=True),
                                _p("C", "{compte_tresorerie}", "montant")]),
    "tresorerie_manuel": ("BQ", "Mouvement de caisse ou de banque, imputé ou en attente",
                          [_p("D", "{compte_contrepartie}", "contrepartie", analytique=True),
                           _p("C", "{compte_tresorerie}", "contrepartie")]),
    "tresorerie_ouverture": ("BQ", "Solde de départ d’un compte du journal de caisse",
                             [_p("D", "{compte_tresorerie}", "montant"), _p("C", "{compte_ouverture}", "montant")]),
    "facture_fournisseur_historique": ("ACH", "Facture fournisseur hors circuit V7 (comptes tiers)",
                                       [_p("D", "{compte_charge}", "montant", analytique=True),
                                        _p("C", "401", "montant", tiers=True)]),
}

PARAMETRES_DEFAUT = {
    "tresorerie_historique": {"cash": "57", "bank": "521", "mobile": "55"},
    "compte_attente": "471",
    "compte_ouverture": "",
    "compte_factures_historiques": "",
    "comptes_depenses": {},
}


def T(nom):
    return db.TABLES[nom]


# ------------------------------------------------------------------ socle par défaut (idempotent)
def assurer_socle(t) -> None:
    deja = {r[0] for r in t.cx.execute(sa.select(T("regles_comptables").c.evenement).distinct())}
    existants = {r[0] for r in t.cx.execute(sa.select(T("cpt_comptes").c.numero))}
    if deja >= set(REGLES_DEFAUT) and existants >= {c[0] for c in COMPTES_DEFAUT}:
        return
    maintenant = db.maintenant()
    for num, lib, coll in COMPTES_DEFAUT:
        if num not in existants:
            t.cx.execute(T("cpt_comptes").insert().values(numero=num, libelle=lib, classe=int(num[0]), collectif=coll,
                                                         actif=True, origine="regle_defaut", cree_le=maintenant, version=1))
    journaux = {r[0] for r in t.cx.execute(sa.select(T("cpt_journaux").c.code))}
    for code, lib, type_ in JOURNAUX_DEFAUT:
        if code not in journaux:
            t.cx.execute(T("cpt_journaux").insert().values(code=code, libelle=lib, type=type_, actif=True,
                                                          cree_le=maintenant, version=1))
    for ev, (journal, motif, postes) in REGLES_DEFAUT.items():
        if ev in deja:
            continue
        t.cx.execute(T("regles_comptables").insert().values(
            id=db.nouvel_id(), evenement=ev, version=1, journal=journal, schema={"postes": postes},
            date_effet="2000-01-01", statut="Active", motif=f"Valeur par défaut du mémo V8 : {motif}", cree_le=maintenant))
    t.evenement("Création", "Socle comptable par défaut (comptes, journaux, règles du mémo V8)", "regles_comptables")


# ------------------------------------------------------------------ plan de comptes
def compte(t, numero: str) -> dict | None:
    r = t.cx.execute(sa.select(T("cpt_comptes")).where(T("cpt_comptes").c.numero == str(numero))).first()
    return dict(r._mapping) if r else None


def assurer_compte(t, numero: str, libelle: str = "") -> dict:
    """Compte existant et actif ; sinon sous-compte créé sous un compte parent actif du plan (521 → 5211)."""
    numero = str(numero or "").strip()
    if not numero.isdigit():
        raise ValueError(f"Compte « {numero} » invalide.")
    c = compte(t, numero)
    if c:
        if not c["actif"]:
            raise ValueError(f"Compte {numero} désactivé : écriture impossible.")
        return c
    parents = [compte(t, numero[:i]) for i in range(len(numero) - 1, 0, -1)]
    parent = next((p for p in parents if p), None)
    if not parent or not parent["actif"]:
        raise ValueError(f"Compte {numero} absent du plan de comptes : importez le plan SYSCOHADA ou créez le compte.")
    vals = dict(numero=numero, libelle=libelle or f"{parent['libelle']} — {numero}", classe=int(numero[0]),
                collectif=parent["collectif"], actif=True, origine="sous_compte", cree_le=db.maintenant(), version=1)
    t.cx.execute(T("cpt_comptes").insert().values(**vals))
    t._auditer("Création", "cpt_comptes", numero, None, vals, f"Sous-compte {numero}")
    return vals


def importer_plan(lignes: list[dict], motif: str) -> int:
    """Plan SYSCOHADA fourni par l'expert-comptable : [{numero, libelle, collectif}] ; création ou mise à jour."""
    u = V.actor()
    V._exiger(u, "comptabilite", "Plan de comptes réservé à la comptabilité.")
    if not (motif or "").strip():
        raise ValueError("Motif (référence du plan validé) obligatoire.")
    n = 0
    with db.transaction("Import du plan de comptes") as t:
        assurer_socle(t)
        for l in lignes:
            num, lib = str(l.get("numero") or "").strip(), str(l.get("libelle") or "").strip()
            if not num.isdigit() or not lib or num[0] not in "123456789":
                raise ValueError(f"Ligne de plan invalide : {num} {lib}")
            avant = compte(t, num)
            vals = dict(libelle=lib[:300], classe=int(num[0]), collectif=bool(l.get("collectif")))
            if avant:
                t.cx.execute(T("cpt_comptes").update().where(T("cpt_comptes").c.numero == num).values(
                    **vals, version=avant["version"] + 1))
                t._auditer("Modification", "cpt_comptes", num, avant, vals, motif)
            else:
                t.cx.execute(T("cpt_comptes").insert().values(numero=num, **vals, actif=True, origine="import_plan",
                                                             cree_par=u["id"], cree_le=db.maintenant(), version=1))
                t._auditer("Création", "cpt_comptes", num, None, vals, motif)
            n += 1
    return n


def desactiver_compte(numero: str) -> None:
    u = V.actor()
    V._exiger(u, "comptabilite", "Plan de comptes réservé à la comptabilité.")
    with db.transaction(f"Désactivation du compte {numero}") as t:
        c = compte(t, numero)
        if not c:
            raise ValueError("Compte introuvable.")
        t.cx.execute(T("cpt_comptes").update().where(T("cpt_comptes").c.numero == numero).values(actif=False))
        t._auditer("Modification", "cpt_comptes", numero, {"actif": True}, {"actif": False})


# ------------------------------------------------------------------ journaux et périodes
def journal_tresorerie(t, compte_v7: dict) -> dict:
    """Un journal par compte de trésorerie V7 (BQ1…, CA1…, MM1…), créé à son premier mouvement comptabilisé."""
    j = t.cx.execute(sa.select(T("cpt_journaux")).where(T("cpt_journaux").c.v7_compte == compte_v7["id"])).first()
    if j:
        return dict(j._mapping)
    type_ = {"bank": "BQ", "cash": "CA", "mobile": "MM"}.get(compte_v7["data"].get("legacy"), "BQ")
    numero_compte = assurer_compte(t, compte_v7["data"]["ledger"], compte_v7["data"].get("label") or compte_v7["ref"])["numero"]
    n = len([r for r in t.cx.execute(sa.select(T("cpt_journaux").c.code).where(T("cpt_journaux").c.type == type_))]) + 1
    vals = dict(code=f"{type_}{n}", libelle=f"{TYPES_JOURNAL[type_]} — {compte_v7['ref']}", type=type_,
                compte_tresorerie=numero_compte, v7_compte=compte_v7["id"], actif=True, cree_le=db.maintenant(), version=1)
    t.cx.execute(T("cpt_journaux").insert().values(**vals))
    t._auditer("Création", "cpt_journaux", vals["code"], None, vals)
    return vals


def periode(t, date_: str) -> dict:
    """Période du mois de la date ; l'exercice (année civile) s'ouvre avec ses 12 périodes à la première écriture."""
    pid = date_[:7]
    r = t.cx.execute(sa.select(T("cpt_periodes")).where(T("cpt_periodes").c.id == pid)).first()
    if r:
        return dict(r._mapping)
    annee = int(date_[:4])
    for m in range(1, 13):
        cle = f"{annee}-{m:02d}"
        if not t.cx.execute(sa.select(T("cpt_periodes").c.id).where(T("cpt_periodes").c.id == cle)).first():
            t.cx.execute(T("cpt_periodes").insert().values(id=cle, exercice=annee, statut="Ouverte", historique=[],
                                                          version=1))
    t.evenement("Création", f"Ouverture de l’exercice {annee} (12 périodes)", "cpt_periodes")
    return dict(t.cx.execute(sa.select(T("cpt_periodes")).where(T("cpt_periodes").c.id == pid)).first()._mapping)


def changer_periode(pid: str, statut: str, motif: str) -> None:
    """Finance : clôture provisoire. DG : réouverture motivée d'une clôture provisoire, clôture définitive."""
    u = V.actor()
    if statut not in STATUTS_PERIODE or not (motif or "").strip():
        raise ValueError("Statut de période et motif obligatoires.")
    with db.transaction(f"Période {pid} : {statut}") as t:
        p = t.cx.execute(sa.select(T("cpt_periodes")).where(T("cpt_periodes").c.id == pid)).first()
        if not p:
            raise ValueError("Période introuvable.")
        p = dict(p._mapping)
        if p["statut"] == "Clôturée définitivement":
            raise ValueError("Période clôturée définitivement : irréversible.")
        if statut == "Clôturée provisoirement":
            V._exiger(u, "comptabilite", "Clôture réservée à la comptabilité.")
        else:
            V._exiger(u, "approbation_dg", "Réouverture et clôture définitive réservées à la DG.")
        h = list(p["historique"]) + [dict(user=u["id"], nom=u["nom"], de=p["statut"], vers=statut, motif=motif,
                                          at=db.maintenant().isoformat())]
        t.cx.execute(T("cpt_periodes").update().where(T("cpt_periodes").c.id == pid).values(
            statut=statut, historique=h, version=p["version"] + 1))
        t._auditer("Modification", "cpt_periodes", pid, {"statut": p["statut"]}, {"statut": statut}, motif)


# ------------------------------------------------------------------ règles comptables (Finance propose, DG active)
def regle_active(t, evenement: str, date_: str) -> dict:
    """Règle active de l'événement à la date (la plus récente version activée dont la date d'effet est passée)."""
    rows = [dict(r._mapping) for r in t.cx.execute(sa.select(T("regles_comptables")).where(
        T("regles_comptables").c.evenement == evenement, T("regles_comptables").c.statut == "Active",
        T("regles_comptables").c.date_effet <= date_))]
    if not rows:
        raise ValueError(f"Aucune règle comptable active pour « {evenement} » au {date_}.")
    return max(rows, key=lambda r: r["version"])


def proposer_regle(evenement: str, journal: str, postes: list[dict], date_effet: str, motif: str) -> str:
    u = V.actor()
    V._exiger(u, "comptabilite", "Proposition réservée à la Finance.")
    V.date(date_effet)
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    for p in postes:
        if p.get("sens") not in ("D", "C") or not p.get("compte") or not p.get("montant"):
            raise ValueError("Chaque poste de la règle : sens D ou C, compte, montant.")
    with db.transaction(f"Proposition de règle {evenement}") as t:
        assurer_socle(t)
        v = (t.cx.execute(sa.select(sa.func.max(T("regles_comptables").c.version)).where(
            T("regles_comptables").c.evenement == evenement)).scalar() or 0) + 1
        id_ = db.nouvel_id()
        t.inserer("regles_comptables", dict(id=id_, evenement=evenement, version=v, journal=journal,
                                            schema={"postes": postes}, date_effet=date_effet, statut="Proposée",
                                            motif=motif.strip(), propose_par=u["id"], cree_le=db.maintenant()))
        return id_


def activer_regle(id_: str, accepter: bool = True) -> None:
    """La DG active (ou rejette) une règle proposée par une autre personne ; les écritures validées ne changent pas."""
    u = V.actor()
    V._exiger(u, "approbation_dg", "Activation réservée à la DG.")
    with db.transaction("Activation de règle comptable") as t:
        r = t.get("regles_comptables", id_)
        if not r or r["statut"] != "Proposée":
            raise ValueError("Règle introuvable ou déjà traitée.")
        if r["propose_par"] == u["id"]:
            raise ValueError("Séparation des fonctions : celui qui propose une règle ne l’active pas.")
        if accepter:
            t.cx.execute(T("regles_comptables").update().where(T("regles_comptables").c.evenement == r["evenement"],
                                                               T("regles_comptables").c.statut == "Active").values(
                statut="Remplacée"))
        t.maj("regles_comptables", id_, {"statut": "Active" if accepter else "Rejetée", "active_par": u["id"],
                                         "active_le": db.maintenant()})


# ------------------------------------------------------------------ génération des pièces
def vers_tenue(t, montant: int, devise: str, date_: str) -> tuple[int, str]:
    import stocks as S
    cible = S.devise_tenue(t)
    if devise == cible:
        return montant, "1"
    taux = DV.taux(devise, cible, date_, V.records("rate", t))
    if taux is None:
        raise ValueError(f"Comptabilisation impossible : aucun taux {devise} → {cible} enregistré au {date_}.")
    return int((Decimal(montant) * taux["taux"]).quantize(Decimal("1"), ROUND_HALF_UP)), str(taux["taux"])


def _gabarit(compte_txt: str, ctx: dict) -> str:
    if compte_txt.startswith("{") and compte_txt.endswith("}"):
        v = ctx.get(compte_txt[1:-1])
        if not v:
            raise ValueError(f"Compte « {compte_txt[1:-1]} » non renseigné (famille d’articles ou journal).")
        return str(v)
    return compte_txt


def comptabiliser(t, evenement: str, date_: str, libelle: str, source_type: str, source_id: str, document: dict,
                  lignes: list[dict] | None = None, journal: dict | None = None) -> str:
    """Produit et valide la pièce de l'événement. document / lignes : {montants en monnaie de tenue, devise,
    montant_devise, taux, tiers, projet, poste, comptes de gabarit}. Renvoie l'identifiant de la pièce."""
    import stocks as S
    assurer_socle(t)
    V.date(date_)
    p = periode(t, date_)
    if p["statut"] != "Ouverte":
        raise ValueError(f"Période {p['id']} {p['statut'].lower()} : aucune écriture ne peut y être datée.")
    regle = regle_active(t, evenement, date_)
    code_j = (journal or {}).get("code") or regle["journal"]
    j = t.cx.execute(sa.select(T("cpt_journaux")).where(T("cpt_journaux").c.code == code_j)).first()
    if not j or not j._mapping["actif"]:
        raise ValueError(f"Journal {code_j} absent ou inactif.")
    tenue = S.devise_tenue(t)
    sorties = []
    for poste in regle["schema"]["postes"]:
        sources = (lignes or []) if poste["par"] == "ligne" else [document]
        for src in sources:
            ctx = {**document, **src, **({"compte_tresorerie": (journal or {}).get("compte_tresorerie")} if journal else {})}
            montant = int(src.get(poste["montant"]) or 0)
            if not montant:
                continue
            sens = poste["sens"] if montant > 0 else ("C" if poste["sens"] == "D" else "D")
            c = assurer_compte(t, _gabarit(poste["compte"], ctx))
            if c["collectif"] and not ctx.get("tiers"):
                raise ValueError(f"Compte collectif {c['numero']} : tiers obligatoire.")
            if c["classe"] in (6, 7) and not (ctx.get("projet") or ctx.get("centre")):
                raise ValueError(f"Compte {c['numero']} : chantier ou centre de coûts obligatoire (analytique).")
            sorties.append(dict(compte=c["numero"], sens=sens, montant=abs(montant),
                                tiers=ctx.get("tiers") if poste.get("tiers") or c["collectif"] else None,
                                projet=ctx.get("projet") if c["classe"] in (6, 7) else None,
                                poste=ctx.get("poste") if c["classe"] in (6, 7) else None,
                                centre=ctx.get("centre") if c["classe"] in (6, 7) else None,
                                libelle=ctx.get("libelle_ligne") or libelle, devise=ctx.get("devise") or tenue,
                                montant_devise=abs(int(ctx.get("montant_devise", montant) or 0)),
                                taux=str(ctx.get("taux") or "1"), echeance=ctx.get("echeance")))
    debit = sum(x["montant"] for x in sorties if x["sens"] == "D")
    credit = sum(x["montant"] for x in sorties if x["sens"] == "C")
    if not sorties or debit != credit:
        raise ValueError(f"Pièce « {evenement} » déséquilibrée ({debit} / {credit}) : vérifiez la règle comptable.")
    exercice = int(date_[:4])
    numero = (t.cx.execute(sa.select(sa.func.max(T("cpt_pieces").c.numero)).where(
        T("cpt_pieces").c.journal == code_j, T("cpt_pieces").c.exercice == exercice)).scalar() or 0) + 1
    pid = db.nouvel_id()
    u = auth.utilisateur() or {}
    t.inserer("cpt_pieces", dict(id=pid, journal=code_j, exercice=exercice, numero=numero, date=date_,
                                 libelle=libelle[:300], source_type=source_type, source_id=source_id, evenement=evenement,
                                 regle_version=regle["version"], devise_tenue=tenue, statut="Validée",
                                 cree_par=u.get("id"), cree_le=db.maintenant(), version=1),
              resume=f"Pièce {code_j}-{exercice}-{numero} ({evenement})")
    for i, x in enumerate(sorties, 1):
        t.cx.execute(T("cpt_lignes").insert().values(
            id=db.nouvel_id(), piece=pid, numero=i, compte=x["compte"], tiers=x["tiers"], projet=x["projet"],
            poste=x["poste"], centre=x["centre"], libelle=x["libelle"][:300],
            debit=x["montant"] if x["sens"] == "D" else 0, credit=x["montant"] if x["sens"] == "C" else 0,
            devise=x["devise"], montant_devise=x["montant_devise"], taux=x["taux"], echeance=x["echeance"]))
    return pid


def contre_passer(t, source_type: str, source_id: str, date_: str, nouvelle_source: tuple[str, str]) -> list[str]:
    """Pièce inverse de chaque pièce d'une source (aucune suppression), dans la période ouverte de la date."""
    out = []
    for p in [dict(r._mapping) for r in t.cx.execute(sa.select(T("cpt_pieces")).where(
            T("cpt_pieces").c.source_type == source_type, T("cpt_pieces").c.source_id == source_id))]:
        per = periode(t, date_)
        if per["statut"] != "Ouverte":
            raise ValueError(f"Période {per['id']} fermée.")
        lignes = [dict(r._mapping) for r in t.cx.execute(sa.select(T("cpt_lignes")).where(T("cpt_lignes").c.piece == p["id"]))]
        exercice = int(date_[:4])
        numero = (t.cx.execute(sa.select(sa.func.max(T("cpt_pieces").c.numero)).where(
            T("cpt_pieces").c.journal == p["journal"], T("cpt_pieces").c.exercice == exercice)).scalar() or 0) + 1
        pid = db.nouvel_id()
        t.inserer("cpt_pieces", {**{k: p[k] for k in ("journal", "evenement", "regle_version", "devise_tenue")},
                                 "id": pid, "exercice": exercice, "numero": numero, "date": date_,
                                 "libelle": f"Contre-passation : {p['libelle']}"[:300], "source_type": nouvelle_source[0],
                                 "source_id": nouvelle_source[1], "statut": "Validée", "contre_passe": p["id"],
                                 "cree_par": (auth.utilisateur() or {}).get("id"), "cree_le": db.maintenant(), "version": 1})
        for l in lignes:
            t.cx.execute(T("cpt_lignes").insert().values(**{**l, "id": db.nouvel_id(), "piece": pid,
                                                            "debit": l["credit"], "credit": l["debit"]}))
        out.append(pid)
    return out


# ------------------------------------------------------------------ états
def _toutes_lignes(exercice: int | None = None) -> list[dict]:
    with db.moteur().connect() as c:
        q = sa.select(T("cpt_lignes"), T("cpt_pieces").c.journal, T("cpt_pieces").c.date, T("cpt_pieces").c.numero.label("piece_numero"),
                      T("cpt_pieces").c.exercice).join(T("cpt_pieces"), T("cpt_pieces").c.id == T("cpt_lignes").c.piece)
        if exercice:
            q = q.where(T("cpt_pieces").c.exercice == exercice)
        return [dict(r._mapping) for r in c.execute(q)]


def balance(exercice: int | None = None) -> list[dict]:
    plan = {r["numero"]: r for r in db.tout("cpt_comptes")}
    tot: dict[str, dict] = {}
    for l in _toutes_lignes(exercice):
        x = tot.setdefault(l["compte"], dict(debit=0, credit=0))
        x["debit"] += l["debit"]
        x["credit"] += l["credit"]
    return [dict(compte=k, libelle=plan.get(k, {}).get("libelle", ""), debit=v["debit"], credit=v["credit"],
                 solde_debiteur=max(0, v["debit"] - v["credit"]), solde_crediteur=max(0, v["credit"] - v["debit"]))
            for k, v in sorted(tot.items())]


def grand_livre(compte_num: str, exercice: int | None = None) -> list[dict]:
    lignes = sorted([l for l in _toutes_lignes(exercice) if l["compte"] == compte_num],
                    key=lambda l: (l["date"], l["journal"], l["piece_numero"], l["numero"]))
    solde = 0
    for l in lignes:
        solde += l["debit"] - l["credit"]
        l["solde"] = solde
    return lignes


def controle_stock_comptes(tx=None) -> dict:
    """Contrôle permanent du mémo (§ 4.5) : valeur du stock = soldes des comptes de stock des familles."""
    import stocks as S
    valeur = sum(int(a["valeur_totale"]) for a in S.articles(tx=tx))
    comptes = {f["compte_stock"] for f in S.familles() if f["compte_stock"]}
    lignes = [l for l in _toutes_lignes() if l["compte"] in comptes]
    solde = sum(l["debit"] - l["credit"] for l in lignes)
    return dict(stock=valeur, comptes=solde, ecart=valeur - solde)


# ------------------------------------------------------------------ paramètres comptables (dynamiques)
def parametres(tx=None) -> dict:
    v = auth._param("parametres_comptables", tx)
    p = {k: (dict(v_) if isinstance(v_, dict) else v_) for k, v_ in PARAMETRES_DEFAUT.items()}
    if isinstance(v, dict):
        for k, v_ in v.items():
            if k in p:
                p[k] = v_
    return p


def configurer(parametres_: dict, motif: str) -> None:
    """Correspondances comptables (catégories de dépense, comptes de trésorerie historiques, comptes d'ouverture,
    d'attente…). Proposées par la comptabilité, tracées au journal d'audit."""
    u = V.actor()
    V._exiger(u, "comptabilite", "Paramètres comptables réservés à la comptabilité.")
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    propres = {}
    for k, v in parametres_.items():
        if k not in PARAMETRES_DEFAUT:
            raise ValueError(f"Paramètre inconnu : {k}.")
        valeurs = v.values() if isinstance(v, dict) else [v]
        if any(x and not str(x).strip().isdigit() for x in valeurs):
            raise ValueError("Les comptes sont des numéros (chiffres seulement).")
        propres[k] = {kk: str(vv).strip() for kk, vv in v.items() if str(vv).strip()} if isinstance(v, dict) else str(v or "").strip()
    with db.transaction("Paramètres comptables") as t:
        assurer_socle(t)
        for k, v in propres.items():
            for num in (v.values() if isinstance(v, dict) else [v]):
                if num:
                    assurer_compte(t, num)
        t.parametre("parametres_comptables", {**parametres(t), **propres}, resume=f"Paramètres comptables : {motif}")


def actif(t, date_: str) -> bool:
    """Comptabilisation des opérations existantes (V7, trésorerie historique) à partir de la date de démarrage DG."""
    import stocks as S
    tenue = S.tenue(t)
    return bool(tenue and tenue.get("debut") and date_ and date_ >= tenue["debut"])


def journal_historique(t, compte_legacy: str) -> dict:
    """Journal du compte du journal de caisse historique (caisse, banque, Mobile money) : CAH, BQH, MMH."""
    type_ = {"cash": "CA", "bank": "BQ", "mobile": "MM"}.get(compte_legacy)
    if not type_:
        raise ValueError("Compte de trésorerie à préciser (caisse, banque ou Mobile money) avant comptabilisation.")
    code = f"{type_}H"
    j = t.cx.execute(sa.select(T("cpt_journaux")).where(T("cpt_journaux").c.code == code)).first()
    numero = parametres(t)["tresorerie_historique"].get(compte_legacy)
    if not numero:
        raise ValueError(f"Compte comptable du {code} non paramétré.")
    c = assurer_compte(t, numero)["numero"]
    if j:
        j = dict(j._mapping)
        if j["compte_tresorerie"] != c:
            t.cx.execute(T("cpt_journaux").update().where(T("cpt_journaux").c.code == code).values(compte_tresorerie=c))
            j["compte_tresorerie"] = c
        return j
    vals = dict(code=code, libelle=f"{TYPES_JOURNAL[type_]} — journal de caisse historique", type=type_,
                compte_tresorerie=c, actif=True, cree_le=db.maintenant(), version=1)
    t.cx.execute(T("cpt_journaux").insert().values(**vals))
    return vals


def _signe(direction: str, montant: int) -> int:
    return montant if direction == "in" else -montant


# ------------------------------------------------------------------ circuit financier V7
def _ctx_devise(t, montant, devise, date_) -> dict:
    tenue, taux = vers_tenue(t, montant, devise, date_)
    return dict(montant=tenue, devise=devise, montant_devise=montant, taux=taux)


def v7_facture(t, op: dict, d: dict, ref: str, date_: str, valeur: int) -> None:
    if not actif(t, date_):
        return
    c = _ctx_devise(t, valeur, op["currency"], date_)
    comptabiliser(t, "v7_facture", date_, f"Facture {ref} — {d['label']}"[:300], "v7_facture", f"{op['id']}:{ref}",
                  dict(c, compte_charge=d["expense_account"], tiers=d["party"], projet=op["project"], poste=d["post"],
                       echeance=d.get("due")))


def _dette_tenue(t, source_type: str, prefixe: str, montant: int) -> int | None:
    """Montant en monnaie de tenue de la dette soldée, au taux moyen des factures comptabilisées de la source."""
    rows = t.lire("select l.credit, l.montant_devise from cpt_lignes l join cpt_pieces p on p.id = l.piece "
                  "where p.source_type = :s and p.source_id like :i and l.compte = '401' and l.credit > 0",
                  s=source_type, i=prefixe + "%")
    tot_dev, tot_tenue = sum(r["montant_devise"] for r in rows), sum(r["credit"] for r in rows)
    if not tot_dev:
        return None
    return int((Decimal(montant) * tot_tenue / tot_dev).quantize(Decimal("1"), ROUND_HALF_UP))


def v7_paiement(t, op: dict, d: dict, compte_v7: dict, pid: str, valeur: int, date_: str, ref: str) -> None:
    if not actif(t, date_):
        return
    j = journal_tresorerie(t, compte_v7)
    c = _ctx_devise(t, valeur, op["currency"], date_)
    if d["nature"] == "Avance":
        comptabiliser(t, "v7_avance", date_, f"Avance {op['ref']} ({ref})", "v7_paiement", pid,
                      dict(c, centre="REGIE", tiers=d["party"]), journal=j)
        return
    dette = _dette_tenue(t, "v7_facture", op["id"] + ":", valeur)
    if dette is None:      # facture antérieure au démarrage : dette au taux du paiement
        dette = c["montant"]
    ecart = c["montant"] - dette
    comptabiliser(t, "v7_paiement", date_, f"Paiement {op['ref']} ({ref})", "v7_paiement", pid,
                  dict(c, dette=dette, tresorerie=c["montant"], perte_change=max(0, ecart), gain_change=max(0, -ecart),
                       tiers=d["party"], centre="FINANCE"), journal=j)


def v7_contre_passation(t, pid: str, date_: str) -> None:
    if actif(t, date_):
        contre_passer(t, "v7_paiement", pid, date_, ("v7_contre_passation", pid))


def v7_justification(t, op: dict, d: dict, piece: str, montant: int, date_: str) -> None:
    if not actif(t, date_):
        return
    c = _ctx_devise(t, montant, op["currency"], date_)
    comptabiliser(t, "v7_justification", date_, f"Justificatif {op['ref']} — {d['label']}"[:300], "v7_justification",
                  piece, dict(c, compte_charge=d["expense_account"], projet=op["project"], poste=d["post"]))


def v7_restitution(t, op: dict, compte_v7: dict, rid: str, montant: int, date_: str) -> None:
    if not actif(t, date_):
        return
    comptabiliser(t, "v7_restitution", date_, f"Restitution {op['ref']}", "v7_restitution", rid,
                  _ctx_devise(t, montant, op["currency"], date_), journal=journal_tresorerie(t, compte_v7))


def v7_virement(t, source: dict, cible: dict, montant: int, date_: str, ref: str) -> None:
    if not actif(t, date_):
        return
    c = _ctx_devise(t, montant, source["currency"], date_)
    comptabiliser(t, "v7_virement_depart", date_, f"Virement {ref}", "v7_virement", f"{ref}:depart", c,
                  journal=journal_tresorerie(t, source))
    comptabiliser(t, "v7_virement_arrivee", date_, f"Virement {ref}", "v7_virement", f"{ref}:arrivee", c,
                  journal=journal_tresorerie(t, cible))


def v7_ouverture(t, compte_v7: dict, montant: int, date_: str, ref: str) -> None:
    if not actif(t, date_):
        return
    ouverture = parametres(t)["compte_ouverture"]
    if not ouverture:
        raise ValueError("Compte de contrepartie des soldes d’ouverture non paramétré (Comptabilité générale › "
                         "Paramètres).")
    comptabiliser(t, "v7_ouverture", date_, f"Solde initial {compte_v7['ref']} ({ref})", "v7_ouverture",
                  f"{compte_v7['id']}:{ref}", dict(_ctx_devise(t, montant, compte_v7["currency"], date_),
                                                   compte_ouverture=ouverture), journal=journal_tresorerie(t, compte_v7))


# ------------------------------------------------------------------ trésorerie historique (journal de caisse)
def mouvement_tresorerie(t, m: dict) -> None:
    """Mouvement du journal de caisse hors circuit V7 : dépense, encaissement client, règlement fournisseur,
    solde de départ ou mouvement manuel (imputé au compte choisi dans l'imputation, sinon en attente 471)."""
    if m.get("kind") == "v7" or not m.get("date") or m.get("account") in (None, "", "unassigned") \
            or not actif(t, m["date"]):
        return
    p = parametres(t)
    j = journal_historique(t, m["account"])
    montant = int(m["amount"])
    c = _ctx_devise(t, montant, m["currency"], m["date"])
    journal_imp = m.get("journal") or {}
    base = dict(c, projet=m.get("project") or None, centre=journal_imp.get("centre") or None)
    source = ("tresorerie_mouvement", m["id"])
    if m.get("expense_id"):
        e = t.get("expenses", m["expense_id"])
        compte = (p["comptes_depenses"] or {}).get((e or {}).get("category", ""))
        if not compte:
            raise ValueError(f"Catégorie de dépense « {(e or {}).get('category', '')} » sans compte comptable : "
                             "paramétrez-la dans Comptabilité générale › Paramètres.")
        sens = 1 if m["direction"] == "out" else -1
        comptabiliser(t, "tresorerie_depense", m["date"], m["label"][:300], *source,
                      dict(base, montant=sens * c["montant"], compte_charge=compte,
                           centre=base["centre"] or (None if base["projet"] else "FRAIS GÉNÉRAUX")), journal=j)
    elif m.get("invoice_id"):
        inv = t.get("invoices", m["invoice_id"])
        comptabiliser(t, "tresorerie_client", m["date"], m["label"][:300], *source,
                      dict(base, montant=_signe(m["direction"], c["montant"]), tiers=(inv or {}).get("client") or None),
                      journal=j)
    elif m.get("supplier_payment_id") or m.get("supplier_reversal_id"):
        pid = m.get("supplier_payment_id")
        if not pid:
            rev = t.get("supplier_reversals", m["supplier_reversal_id"])
            pid = (rev or {}).get("payment_id")
        pay = t.get("supplier_payments", pid) or {}
        # Un règlement affecté à une facture solde la dette (401) ; un paiement non affecté est une avance (4091).
        affecte = bool(t.lire("select id from supplier_allocations where payment_id = :p", p=pid))
        comptabiliser(t, "tresorerie_fournisseur", m["date"], m["label"][:300], *source,
                      dict(base, montant=-_signe(m["direction"], c["montant"]), tiers=pay.get("party_id"),
                           compte_fournisseur="401" if affecte else "4091"), journal=j)
    elif m.get("kind") == "opening":
        if not p["compte_ouverture"]:
            raise ValueError("Compte de contrepartie des soldes d’ouverture non paramétré.")
        comptabiliser(t, "tresorerie_ouverture", m["date"], m["label"][:300], *source,
                      dict(base, montant=_signe(m["direction"], c["montant"]), compte_ouverture=p["compte_ouverture"]),
                      journal=j)
    else:
        contrepartie = journal_imp.get("compte") or p["compte_attente"]
        comptabiliser(t, "tresorerie_manuel", m["date"], m["label"][:300], *source,
                      dict(base, contrepartie=-_signe(m["direction"], c["montant"]), compte_contrepartie=contrepartie,
                           centre=base["centre"] or (None if base["projet"] else "FRAIS GÉNÉRAUX")), journal=j)


def mouvement_modifie(t, avant: dict, apres: dict) -> None:
    """Modification d'un mouvement comptabilisé : contre-passation de la pièce, puis nouvelle pièce (rien ne s'efface)."""
    cles = ("date", "account", "amount", "direction", "currency", "project", "journal", "kind")
    if all(avant.get(k) == apres.get(k) for k in cles):
        return
    if t.lire("select id from cpt_pieces where source_type = 'tresorerie_mouvement' and source_id = :i "
              "and contre_passe is null", i=avant["id"]):
        _annuler_source(t, "tresorerie_mouvement", avant["id"], apres.get("date") or avant.get("date") or R.today())
    mouvement_tresorerie(t, apres)


def mouvement_supprime(t, avant: dict) -> None:
    if avant.get("kind") != "v7" and avant.get("date"):
        _annuler_source(t, "tresorerie_mouvement", avant["id"], R.today())


def _annuler_source(t, source_type: str, source_id: str, date_: str) -> None:
    """Contre-passe les pièces actives d'une source (une pièce déjà contre-passée ne l'est pas deux fois)."""
    actives = [p for p in t.lire("select id from cpt_pieces where source_type = :s and source_id = :i", s=source_type,
                                 i=source_id)
               if not t.lire("select id from cpt_pieces where contre_passe = :p", p=p["id"])]
    for p in actives:
        piece = t.lire("select * from cpt_pieces where id = :i", i=p["id"])[0]
        lignes = t.lire("select * from cpt_lignes where piece = :i", i=p["id"])
        per = periode(t, date_)
        if per["statut"] != "Ouverte":
            raise ValueError(f"Période {per['id']} fermée : correction impossible à cette date.")
        exercice = int(date_[:4])
        numero = (t.cx.execute(sa.select(sa.func.max(T("cpt_pieces").c.numero)).where(
            T("cpt_pieces").c.journal == piece["journal"], T("cpt_pieces").c.exercice == exercice)).scalar() or 0) + 1
        pid = db.nouvel_id()
        t.inserer("cpt_pieces", {**{k: piece[k] for k in ("journal", "evenement", "regle_version", "devise_tenue")},
                                 "id": pid, "exercice": exercice, "numero": numero, "date": date_,
                                 "libelle": f"Contre-passation : {piece['libelle']}"[:300],
                                 "source_type": source_type + "_annulation", "source_id": source_id, "statut": "Validée",
                                 "contre_passe": piece["id"], "cree_par": (auth.utilisateur() or {}).get("id"),
                                 "cree_le": db.maintenant(), "version": 1})
        for l in lignes:
            t.cx.execute(T("cpt_lignes").insert().values(**{**l, "id": db.nouvel_id(), "piece": pid,
                                                            "debit": l["credit"], "credit": l["debit"]}))


def facture_fournisseur_historique(t, f: dict) -> None:
    """Facture fournisseur saisie dans les comptes tiers (hors circuit V7)."""
    if not actif(t, f.get("date") or ""):
        return
    compte = parametres(t)["compte_factures_historiques"]
    if not compte:
        raise ValueError("Compte de charge des factures fournisseurs (comptes tiers) non paramétré.")
    comptabiliser(t, "facture_fournisseur_historique", f["date"], f"Facture {f['reference']}"[:300],
                  "facture_fournisseur", f["id"], dict(_ctx_devise(t, int(f["amount"]), f["currency"], f["date"]),
                                                       compte_charge=compte, tiers=f["party_id"],
                                                       projet=f.get("project") or None, echeance=f.get("due"),
                                                       centre=None if f.get("project") else "FRAIS GÉNÉRAUX"))


# ------------------------------------------------------------------ contrôle permanent trésorerie / comptes
def controle_tresorerie() -> list[dict]:
    """Par journal de trésorerie et par devise : solde de l'application (mouvements depuis le démarrage)
    = solde comptable en devise d'origine des lignes du compte de trésorerie (critère de sortie du lot 1)."""
    import stocks as S
    tenue = S.tenue() or {}
    debut = tenue.get("debut")
    if not debut:
        return []
    mouvements = [m for m in db.tout("movements") if (m.get("date") or "") >= debut]
    journaux = db.tout("cpt_journaux")
    lignes = _toutes_lignes()
    out = []
    for j in journaux:
        if j["type"] not in ("BQ", "CA", "MM") or not j["compte_tresorerie"]:
            continue
        if j["v7_compte"]:
            mv = [m for m in mouvements if (m.get("journal") or {}).get("v7_account") == j["v7_compte"]]
        else:
            legacy = {"CAH": "cash", "BQH": "bank", "MMH": "mobile"}.get(j["code"])
            mv = [m for m in mouvements if m["kind"] != "v7" and m["account"] == legacy]
        pieces_j = {p["id"] for p in db.tout("cpt_pieces") if p["journal"] == j["code"]}
        devises = {m["currency"] for m in mv} | {l["devise"] for l in lignes if l["piece"] in pieces_j}
        for dev in sorted(devises):
            app = sum(_signe(m["direction"], int(m["amount"])) for m in mv if m["currency"] == dev)
            cpt = sum((1 if l["debit"] else -1) * l["montant_devise"] for l in lignes
                      if l["piece"] in pieces_j and l["compte"] == j["compte_tresorerie"] and l["devise"] == dev)
            out.append(dict(journal=j["code"], compte=j["compte_tresorerie"], devise=dev, application=app,
                            comptabilite=cpt, ecart=app - cpt))
    return out
