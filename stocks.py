"""Stock permanent (mémo V8, § 4) : familles, articles, magasins, soldes, mouvements valorisés au CMUP,
réservations et bons de sortie vers les chantiers.

Règles :
- quantités exactes (Decimal) en unité de stock ; valeurs en centimes de la monnaie de tenue, fixée par la DG ;
- stock jamais négatif : disponible = stock physique − réservations actives ;
- CMUP par article et par société, recalculé à chaque entrée ; une sortie est valorisée au CMUP du moment ;
- un mouvement validé ne se supprime pas : il se corrige par contre-passation référencée ;
- la conversion d'un coût d'achat en monnaie de tenue utilise le taux enregistré à la date, jamais estimé.

Les écritures comptables STK (32 / 33 ↔ 6032 / 6033) seront produites par le lot 1 (comptabilisation.py) à partir des
mouvements, qui portent déjà la source, la famille, le projet et le poste.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

import auth
import db
import devises as DV
import gestion_v7 as V
import regles as R

NATURES = {"stocke": "Article stocké", "non_stocke": "Non stocké (consommé à la réception)",
           "prestation": "Prestation ou sous-traitance"}
TYPES_MAGASIN = {"central": "Magasin central", "chantier": "Magasin de chantier", "transit": "Transit"}
QMAX = Decimal("1e12")


def D(v) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    try:
        d = Decimal(str(v).replace(",", ".").replace(" ", "").replace(" ", ""))
    except Exception:  # noqa: BLE001
        raise ValueError("Quantité invalide.") from None
    if not d.is_finite():
        raise ValueError("Quantité invalide.")
    return d


def qte(v, libelle="Quantité", zero_ok=False) -> Decimal:
    d = D(v)
    if d < 0 or (d == 0 and not zero_ok) or d > QMAX:
        raise ValueError(f"{libelle} positive requise.")
    if d != d.quantize(Decimal("0.0001")):
        raise ValueError(f"{libelle} : quatre décimales au plus.")
    return d


def cents(v: Decimal) -> int:
    return int(Decimal(v).quantize(Decimal("1"), ROUND_HALF_UP))


def T(nom):
    return db.TABLES[nom]


def _lignes(tx, nom, *conds) -> list[dict]:
    q = sa.select(T(nom))
    for c in conds:
        q = q.where(c)
    if tx is not None:
        return [dict(r._mapping) for r in tx.cx.execute(q)]
    with db.moteur().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def _un(tx, nom, id_, verrou=False):
    t = T(nom)
    q = sa.select(t).where(t.c.id == id_)
    if verrou and tx.cx.dialect.name == "postgresql":
        q = q.with_for_update()
    r = tx.cx.execute(q).first()
    return dict(r._mapping) if r else None


def numero(tx, nom: str, prefixe: str, date_: str | None = None) -> str:
    """Numérotation continue par préfixe et par année : PREFIXE-AAAA-00001."""
    annee = (date_ or R.today())[:4]
    t = T(nom)
    debut = f"{prefixe}-{annee}-"
    nums = [r[0] for r in tx.cx.execute(sa.select(t.c.numero).where(t.c.numero.like(debut + "%")))]
    suivant = max((int(n[len(debut):]) for n in nums if n[len(debut):].isdigit()), default=0) + 1
    return f"{debut}{suivant:05d}"


def acteur(module: str | None = None, message: str = "") -> dict:
    u = V.actor()
    if module and not V.peut(u, module):
        raise ValueError(message or "Votre profil ne permet pas cette action.")
    return u


# ------------------------------------------------------------------ monnaie de tenue
def tenue(tx=None) -> dict | None:
    v = auth._param("comptabilite_tenue", tx)
    return v if isinstance(v, dict) and v.get("devise") in R.CURRENCIES else None


def devise_tenue(tx=None) -> str:
    t_ = tenue(tx)
    if not t_:
        raise ValueError("Monnaie de tenue non fixée : la DG doit l’enregistrer (Paramètres achats et stock) avant "
                         "toute valorisation de stock.")
    return t_["devise"]


def fixer_tenue(devise: str, reference: str, motif: str, debut: str | None = None) -> None:
    """Décision DG, fixée une fois pour toutes (mémo § 2.5) : modifiable seulement tant qu'aucun mouvement n'existe.
    « debut » : date de démarrage de la comptabilisation des opérations existantes (circuit V7, journal de caisse,
    dépenses, comptes tiers) ; vide = pas encore (le stock et les achats V8 sont comptabilisés dès maintenant)."""
    u = acteur("approbation_dg", "Décision réservée à la DG.")
    if devise not in R.CURRENCIES:
        raise ValueError("Devise invalide.")
    if debut:
        V.date(debut)
    if not (reference or "").strip() or not (motif or "").strip():
        raise ValueError("Référence de la décision (PV, courrier de l’expert-comptable) et motif obligatoires.")
    with db.transaction("Monnaie de tenue") as t:
        actuelle = tenue(t)
        if actuelle and actuelle["devise"] != devise and t.cx.execute(sa.select(sa.func.count()).select_from(
                T("stk_mouvements"))).scalar():
            raise ValueError("Des mouvements de stock sont valorisés : la monnaie de tenue ne peut plus changer.")
        if actuelle and actuelle.get("debut") and debut != actuelle["debut"] and t.cx.execute(
                sa.select(sa.func.count()).select_from(T("cpt_pieces")).where(
                    T("cpt_pieces").c.date >= actuelle["debut"])).scalar() and (not debut or debut > actuelle["debut"]):
            raise ValueError("Des écritures existent depuis la date de démarrage : elle ne peut plus être reculée "
                             "ni retirée.")
        t.parametre("comptabilite_tenue", {"devise": devise, "reference": reference.strip(), "motif": motif.strip(),
                                           "debut": debut or None,
                                           "decide_par": u["id"], "decide_nom": u["nom"],
                                           "decide_le": db.maintenant().isoformat()},
                    resume=f"Monnaie de tenue : {devise} ({reference.strip()})")


def vers_tenue(montant: int, devise: str, date_: str, tx=None) -> tuple[int, str]:
    """Conversion au taux historique enregistré à la date ; bloquée sans taux (jamais estimée)."""
    cible = devise_tenue(tx)
    if devise == cible:
        return montant, "1"
    t_ = DV.taux(devise, cible, date_, V.records("rate", tx) if tx is not None else None)
    if t_ is None:
        raise ValueError(f"Aucun taux {devise} → {cible} enregistré au {date_} : saisissez le taux du jour.")
    return cents(Decimal(montant) * t_["taux"]), str(t_["taux"])


# ------------------------------------------------------------------ référentiels
def enregistrer_famille(code: str, libelle: str, compte_charge: str, compte_stock: str = "",
                        compte_variation: str = "", actif: bool = True) -> None:
    u = acteur("comptabilite", "Les familles d’articles et leurs comptes relèvent de la comptabilité.")
    with db.transaction(f"Famille d’articles {code}") as t:
        _famille_tx(t, u, code, libelle, compte_charge, compte_stock, compte_variation, actif)


def _famille_tx(t, u, code, libelle, compte_charge, compte_stock="", compte_variation="", actif=True) -> str:
    code = (code or "").strip().upper()
    if not code or len(code) > 30 or not (libelle or "").strip():
        raise ValueError("Code (30 caractères au plus) et libellé obligatoires.")
    for c in (compte_charge, compte_stock, compte_variation):
        if c and not str(c).strip().isdigit():
            raise ValueError("Les comptes sont des numéros SYSCOHADA (chiffres seulement).")
    if not str(compte_charge or "").strip():
        raise ValueError("Compte de charge obligatoire.")
    if bool(compte_stock) != bool(compte_variation):
        raise ValueError("Un compte de stock va avec son compte de variation (ex. 321 et 6032).")
    vals = dict(libelle=libelle.strip(), compte_charge=str(compte_charge).strip(), compte_stock=str(compte_stock or "").strip(),
                compte_variation=str(compte_variation or "").strip(), actif=bool(actif))
    f = T("stk_familles")
    avant = t.cx.execute(sa.select(f).where(f.c.code == code)).first()
    if avant:
        avant = dict(avant._mapping)
        t.cx.execute(f.update().where(f.c.code == code).values(**vals, version=avant["version"] + 1))
        t._auditer("Modification", "stk_familles", code, avant, vals)
    else:
        t.cx.execute(f.insert().values(code=code, **vals, cree_par=u["id"], cree_le=db.maintenant(), version=1))
        t._auditer("Création", "stk_familles", code, None, vals)
    return code


def familles(actives=False) -> list[dict]:
    return [f for f in _lignes(None, "stk_familles") if f["actif"] or not actives]


def enregistrer_article(code: str, libelle: str, famille: str, nature: str, unite_stock: str, unite_achat: str = "",
                        coefficient="1", seuil_min=None, seuil_max=None, actif: bool = True, id_: str | None = None,
                        a_qualifier: bool = False) -> str:
    u = acteur("achats", "Le référentiel des articles relève des achats.")
    with db.transaction(f"Article {code}") as t:
        return _enregistrer_article_tx(t, u, code, libelle, famille, nature, unite_stock, unite_achat, coefficient,
                                       seuil_min, seuil_max, actif, id_, a_qualifier)


def _enregistrer_article_tx(t, u, code, libelle, famille, nature, unite_stock, unite_achat="", coefficient="1",
                            seuil_min=None, seuil_max=None, actif=True, id_=None, a_qualifier=False) -> str:
    code = (code or "").strip().upper()
    if not code or len(code) > 60 or not (libelle or "").strip() or not (unite_stock or "").strip():
        raise ValueError("Code, libellé et unité de stock obligatoires.")
    if nature not in NATURES:
        raise ValueError("Nature d’article invalide.")
    fam = t.cx.execute(sa.select(T("stk_familles")).where(T("stk_familles").c.code == famille)).first()
    if not fam or not fam._mapping["actif"]:
        raise ValueError("Famille d’articles inconnue ou inactive.")
    if nature == "stocke" and not fam._mapping["compte_stock"]:
        raise ValueError("Un article stocké appartient à une famille dotée d’un compte de stock (32 / 33).")
    coef = qte(coefficient, "Coefficient d’achat")
    smin = qte(seuil_min, "Seuil minimum", True) if seuil_min not in (None, "") else None
    smax = qte(seuil_max, "Seuil maximum", True) if seuil_max not in (None, "") else None
    if smin is not None and smax is not None and smin > smax:
        raise ValueError("Le seuil minimum dépasse le seuil maximum.")
    vals = dict(code=code, libelle=libelle.strip()[:300], famille=famille, nature=nature, unite_stock=unite_stock.strip()[:30],
                unite_achat=(unite_achat or unite_stock).strip()[:30], coefficient=coef, seuil_min=smin, seuil_max=smax,
                actif=bool(actif), a_qualifier=bool(a_qualifier))
    a = T("stk_articles")
    if id_:
        avant = _un(t, "stk_articles", id_, True)
        if not avant:
            raise ValueError("Article introuvable.")
        bouge = t.cx.execute(sa.select(sa.func.count()).select_from(T("stk_mouvements")).where(
            T("stk_mouvements").c.article == id_)).scalar()
        if bouge and (avant["nature"] != nature or avant["unite_stock"] != vals["unite_stock"]):
            raise ValueError("Article déjà mouvementé : sa nature et son unité de stock ne changent plus.")
        try:
            with t.cx.begin_nested():
                t.cx.execute(a.update().where(a.c.id == id_, a.c.version == avant["version"]).values(
                    **vals, version=avant["version"] + 1))
        except sa.exc.IntegrityError:
            raise ValueError("Code article déjà utilisé.") from None
        t._auditer("Modification", "stk_articles", id_, avant, vals)
        return id_
    id_ = db.nouvel_id()
    try:
        with t.cx.begin_nested():
            t.inserer("stk_articles", dict(id=id_, **vals, qte_totale=0, valeur_totale=0, cmup=0, cree_par=u["id"],
                                           cree_le=db.maintenant(), version=1))
    except sa.exc.IntegrityError:
        raise ValueError(f"Code article déjà utilisé : {code}.") from None
    return id_


def articles(actifs=False, tx=None) -> list[dict]:
    return [a for a in _lignes(tx, "stk_articles") if a["actif"] or not actifs]


def enregistrer_magasin(code: str, libelle: str, type_: str, projet: str | None = None, responsable: int | None = None,
                        adjoint: int | None = None, actif: bool = True, id_: str | None = None) -> str:
    u = acteur("achats", "Les magasins relèvent des achats et de la logistique.")
    with db.transaction(f"Magasin {code}") as t:
        return _magasin_tx(t, u, code, libelle, type_, projet, responsable, adjoint, actif, id_)


def _magasin_tx(t, u, code, libelle, type_, projet=None, responsable=None, adjoint=None, actif=True, id_=None) -> str:
    code = (code or "").strip().upper()
    if not code or not (libelle or "").strip() or type_ not in TYPES_MAGASIN:
        raise ValueError("Code, libellé et type de magasin obligatoires.")
    if type_ == "chantier" and not projet:
        raise ValueError("Un magasin de chantier est rattaché à un chantier.")
    vals = dict(code=code, libelle=libelle.strip(), type=type_, projet=projet or None, responsable=responsable,
                adjoint=adjoint, actif=bool(actif))
    if projet and not t.get("projects", projet):
        raise ValueError("Chantier introuvable.")
    if type_ == "chantier" and actif:
        autres = [m for m in _lignes(t, "stk_magasins") if m["type"] == "chantier" and m["projet"] == projet
                  and m["actif"] and m["id"] != id_]
        if autres:
            raise ValueError(f"Ce chantier a déjà un magasin actif : {autres[0]['code']}.")
    try:
        with t.cx.begin_nested():
            if id_:
                avant = _un(t, "stk_magasins", id_, True)
                if not avant:
                    raise ValueError("Magasin introuvable.")
                if not actif and any(D(x["quantite"]) for x in _lignes(t, "stk_soldes", T("stk_soldes").c.magasin == id_)):
                    raise ValueError("Magasin non vide : transférez ou ajustez le stock avant de le désactiver.")
                t.maj("stk_magasins", id_, {**vals, "version": avant["version"] + 1})
                return id_
            id_ = db.nouvel_id()
            t.inserer("stk_magasins", dict(id=id_, **vals, cree_par=u["id"], cree_le=db.maintenant(), version=1))
            return id_
    except sa.exc.IntegrityError:
        raise ValueError("Code de magasin déjà utilisé.") from None


def magasins(actifs=False, tx=None) -> list[dict]:
    return [m for m in _lignes(tx, "stk_magasins") if m["actif"] or not actifs]


def magasin_du_chantier(projet: str, tx=None) -> dict | None:
    return next((m for m in magasins(True, tx) if m["type"] == "chantier" and m["projet"] == projet), None)


# ------------------------------------------------------------------ soldes, disponible, réservations
def solde(tx, article: str, magasin: str) -> Decimal:
    s = T("stk_soldes")
    v = tx.cx.execute(sa.select(s.c.quantite).where(s.c.article == article, s.c.magasin == magasin)).scalar() \
        if tx is not None else None
    if tx is None:
        with db.moteur().connect() as c:
            v = c.execute(sa.select(s.c.quantite).where(s.c.article == article, s.c.magasin == magasin)).scalar()
    return D(v)


def reserve(tx, article: str, magasin: str, sauf: str | None = None) -> Decimal:
    r = T("stk_reservations")
    conds = [r.c.article == article, r.c.magasin == magasin, r.c.statut == "Active"]
    if sauf:
        conds.append(r.c.source_id != sauf)
    return sum((D(x["quantite"]) for x in _lignes(tx, "stk_reservations", *conds)), Decimal(0))


def disponible(tx, article: str, magasin: str, sauf: str | None = None) -> Decimal:
    return solde(tx, article, magasin) - reserve(tx, article, magasin, sauf)


def disponibilites(article: str, tx=None) -> list[dict]:
    """Stock physique, réservé et disponible de l'article dans chaque magasin (affichage avant soumission)."""
    out = []
    for m in magasins(True, tx):
        phys = solde(tx, article, m["id"])
        if phys:
            res = reserve(tx, article, m["id"])
            out.append(dict(magasin=m["id"], code=m["code"], libelle=m["libelle"], type=m["type"], physique=phys,
                            reserve=res, disponible=phys - res))
    return out


def _maj_solde(t, article: str, magasin: str, delta: Decimal) -> Decimal:
    s = T("stk_soldes")
    ligne = t.cx.execute(sa.select(s).where(s.c.article == article, s.c.magasin == magasin)).first()
    if ligne is None:
        if delta < 0:
            raise ValueError("Stock insuffisant.")
        t.cx.execute(s.insert().values(article=article, magasin=magasin, quantite=delta, version=1))
        return delta
    ligne = dict(ligne._mapping)
    nouveau = D(ligne["quantite"]) + delta
    if nouveau < 0:
        raise ValueError("Stock insuffisant : le stock ne peut pas devenir négatif.")
    res = t.cx.execute(s.update().where(s.c.article == article, s.c.magasin == magasin,
                                        s.c.version == ligne["version"]).values(quantite=nouveau,
                                                                                version=ligne["version"] + 1))
    if res.rowcount != 1:
        raise ValueError("Une autre personne a modifié ce stock. Actualisez.")
    return nouveau


def _mouvement(t, u, type_, date_, article, magasin, quantite: Decimal, valeur: int, source_type, source_id,
               projet=None, poste=None, cout_devise=None, cout_origine=None, taux=None, contre_passe=None) -> str:
    """Seul point d'écriture du stock : solde, quantité et valeur société, CMUP, mouvement tracé."""
    V.date(date_)
    a = _un(t, "stk_articles", article, True)
    if not a or a["nature"] != "stocke":
        raise ValueError("Seuls les articles stockés ont des mouvements de stock.")
    devise = devise_tenue(t)
    _maj_solde(t, article, magasin, quantite)
    q_tot = D(a["qte_totale"]) + quantite
    v_tot = int(a["valeur_totale"]) + valeur
    if q_tot < 0:
        raise ValueError("Stock société insuffisant.")
    if q_tot == 0:
        v_tot = 0 if abs(v_tot) <= 1 else v_tot
        if v_tot:
            raise ValueError("Valeur résiduelle sur un stock nul : contre-passation ou ajustement requis.")
    cmup = (Decimal(v_tot) / q_tot).quantize(Decimal("0.000001"), ROUND_HALF_UP) if q_tot else D(a["cmup"])
    res = t.cx.execute(T("stk_articles").update().where(T("stk_articles").c.id == article,
                                                        T("stk_articles").c.version == a["version"]).values(
        qte_totale=q_tot, valeur_totale=v_tot, cmup=cmup, version=a["version"] + 1))
    if res.rowcount != 1:
        raise ValueError("Une autre personne a modifié cet article. Actualisez.")
    id_ = db.nouvel_id()
    t.inserer("stk_mouvements", dict(
        id=id_, numero=numero(t, "stk_mouvements", "MVT", date_), type=type_, date=date_, article=article,
        magasin=magasin, quantite=quantite, valeur=valeur, cmup_apres=cmup, devise_tenue=devise, cout_devise=cout_devise,
        cout_origine=cout_origine, taux=taux, projet=projet, poste=poste, source_type=source_type, source_id=source_id,
        contre_passe=contre_passe, statut="Validé", cree_par=u["id"], cree_le=db.maintenant(), version=1),
        resume=f"Mouvement de stock {type_}")
    _comptabiliser_mouvement(t, id_, type_, date_, a, magasin, valeur, projet, poste, cout_devise, cout_origine, taux,
                             contre_passe)
    return id_


def _comptes_famille(t, article: dict) -> dict:
    f = t.cx.execute(sa.select(T("stk_familles")).where(T("stk_familles").c.code == article["famille"])).first()
    f = dict(f._mapping)
    return dict(compte_stock=f["compte_stock"], compte_variation=f["compte_variation"], compte_charge=f["compte_charge"])


def _comptabiliser_mouvement(t, id_, type_, date_, article, magasin, valeur, projet, poste, cout_devise, cout_origine,
                             taux, contre_passe):
    """Écriture STK du mouvement, dans la même transaction (comptabilisation.py est le seul à écrire les pièces)."""
    import comptabilisation as CPT
    if contre_passe:
        CPT.contre_passer(t, "stk_mouvement", contre_passe, date_, ("stk_mouvement", id_))
        return
    mag = _un(t, "stk_magasins", magasin)
    ligne = dict(**_comptes_famille(t, article), valeur=abs(valeur), devise=cout_devise or devise_tenue(t),
                 montant_devise=abs(cout_origine if cout_origine is not None else valeur), taux=taux or "1",
                 libelle_ligne=f"{article['code']} · {mag['code'] if mag else ''}")
    if type_ == "sortie_chantier":
        CPT.comptabiliser(t, "stock_sortie", date_, f"Sortie {article['code']} vers le chantier", "stk_mouvement", id_,
                          {}, [dict(ligne, projet=projet, poste=poste)])
    elif type_ == "ecart_prix":
        CPT.comptabiliser(t, "stock_ecart_prix", date_, f"Écart de prix {article['code']}", "stk_mouvement", id_, {},
                          [dict(ligne, valeur=valeur, centre=f"MAG-{mag['code']}" if mag else "STOCK")])
    else:
        CPT.comptabiliser(t, "stock_entree", date_, f"Entrée {article['code']}", "stk_mouvement", id_, {},
                          [dict(ligne, centre=f"MAG-{mag['code']}" if mag else "STOCK")])


def entree(t, u, article, magasin, quantite: Decimal, cout: int, devise: str, date_: str, source_type: str,
           source_id: str) -> str:
    """Entrée valorisée au coût d'achat converti en monnaie de tenue au taux historique de la date."""
    valeur, taux = vers_tenue(cout, devise, date_, t)
    return _mouvement(t, u, "entree_reception", date_, article, magasin, quantite, valeur, source_type, source_id,
                      cout_devise=devise, cout_origine=cout, taux=taux)


def sortie(t, u, article, magasin, quantite: Decimal, date_: str, source_type: str, source_id: str, projet: str,
           poste: str, reservation_source: str | None = None) -> str:
    """Sortie au CMUP du moment, imputée au chantier et au poste DQE."""
    if disponible(t, article, magasin, sauf=reservation_source) < quantite:
        raise ValueError("Stock disponible insuffisant (stock physique moins réservations).")
    a = _un(t, "stk_articles", article)
    q_tot = D(a["qte_totale"])
    valeur = int(a["valeur_totale"]) if quantite == q_tot else cents(quantite * D(a["cmup"]))
    return _mouvement(t, u, "sortie_chantier", date_, article, magasin, -quantite, -valeur, source_type, source_id,
                      projet=projet, poste=poste)


def ajuster_valeur(t, u, article: str, ecart: int, date_: str, source_type: str, source_id: str) -> None:
    """Écart de prix facturé porté sur la valeur du stock restant (quantité inchangée)."""
    a = _un(t, "stk_articles", article, True)
    v_tot = int(a["valeur_totale"]) + ecart
    if v_tot < 0:
        raise ValueError("L’écart de prix rendrait la valeur du stock négative.")
    cmup = (Decimal(v_tot) / D(a["qte_totale"])).quantize(Decimal("0.000001"), ROUND_HALF_UP)
    t.cx.execute(T("stk_articles").update().where(T("stk_articles").c.id == article).values(
        valeur_totale=v_tot, cmup=cmup, version=a["version"] + 1))
    mag = next((s["magasin"] for s in _lignes(t, "stk_soldes", T("stk_soldes").c.article == article)
                if D(s["quantite"]) > 0), None)
    id_ = db.nouvel_id()
    t.inserer("stk_mouvements", dict(
        id=id_, numero=numero(t, "stk_mouvements", "MVT", date_), type="ecart_prix", date=date_,
        article=article, magasin=mag, quantite=0, valeur=ecart, cmup_apres=cmup, devise_tenue=devise_tenue(t),
        source_type=source_type, source_id=source_id, statut="Validé", cree_par=u["id"], cree_le=db.maintenant(),
        version=1), resume="Écart de prix porté sur le stock")
    _comptabiliser_mouvement(t, id_, "ecart_prix", date_, a, mag, ecart, None, None, None, None, None, None)


def contre_passer(mouvement: str, motif: str, date_: str | None = None) -> str:
    """Mouvement inverse référencé (aucune suppression)."""
    u = acteur("magasin", "Contre-passation réservée au magasin.")
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    date_ = date_ or R.today()
    with db.transaction("Contre-passation de mouvement de stock") as t:
        m = _un(t, "stk_mouvements", mouvement, True)
        if not m or m["type"] == "ecart_prix" or m["contre_passe"]:
            raise ValueError("Mouvement introuvable ou non contre-passable.")
        if t.cx.execute(sa.select(T("stk_mouvements").c.id).where(T("stk_mouvements").c.contre_passe == mouvement)).first():
            raise ValueError("Mouvement déjà contre-passé.")
        return _mouvement(t, u, "contre_passation", date_, m["article"], m["magasin"], -D(m["quantite"]),
                          -int(m["valeur"]), "contre_passation", mouvement, projet=m["projet"], poste=m["poste"],
                          contre_passe=mouvement)


# ------------------------------------------------------------------ bons de sortie
def _creer_bon_tx(t, u, projet: str, magasin: str, date_: str, lignes: list[dict], motif: str = "") -> str:
    V.date(date_)
    m = _un(t, "stk_magasins", magasin)
    if not m or not m["actif"]:
        raise ValueError("Magasin introuvable ou inactif.")
    b = V.budget_for(projet, t)
    postes = {x["code"] for x in b["data"]["lines"]}
    if not lignes:
        raise ValueError("Au moins une ligne.")
    id_ = db.nouvel_id()
    t.inserer("stk_bons_sortie", dict(id=id_, numero=numero(t, "stk_bons_sortie", "BS", date_), magasin=magasin,
                                      projet=projet, demandeur=u["id"], date_souhaitee=date_, statut="À servir",
                                      motif=motif, cree_par=u["id"], cree_le=db.maintenant(), version=1))
    for l in lignes:
        q = qte(l["quantite"])
        a = _un(t, "stk_articles", l["article"])
        if not a or a["nature"] != "stocke" or not a["actif"]:
            raise ValueError("Bon de sortie : article stocké et actif requis.")
        if l["poste"] not in postes:
            raise ValueError("Bon de sortie : poste DQE absent du budget.")
        if disponible(t, l["article"], magasin) < q:
            raise ValueError(f"{a['code']} : disponible insuffisant dans le magasin {m['code']}.")
        lid = db.nouvel_id()
        t.inserer("stk_bon_sortie_lignes", dict(id=lid, bon=id_, article=l["article"], poste=l["poste"], quantite=q))
        t.inserer("stk_reservations", dict(id=db.nouvel_id(), article=l["article"], magasin=magasin, quantite=q,
                                           source_type="bon_sortie", source_id=id_, statut="Active",
                                           cree_par=u["id"], cree_le=db.maintenant(), version=1))
    return id_


def creer_bon_sortie(projet: str, magasin: str, date_: str, lignes: list[dict], motif: str = "") -> str:
    u = acteur("demandes_achat", "Demande de sortie réservée à l’équipe du chantier.")
    if not auth.sur_chantier(u, projet):
        raise ValueError("Chantier hors de votre périmètre.")
    with db.transaction("Bon de sortie") as t:
        return _creer_bon_tx(t, u, projet, magasin, date_, lignes, motif)


def servir_bon(bon: str, date_: str | None = None) -> None:
    """Le magasinier sert le bon : sorties au CMUP, réservations consommées, coût réalisé sur le poste DQE."""
    u = acteur("magasin", "Sortie de stock réservée au magasin.")
    date_ = date_ or R.today()
    with db.transaction("Sortie de stock vers le chantier") as t:
        b = _un(t, "stk_bons_sortie", bon, True)
        if not b or b["statut"] != "À servir":
            raise ValueError("Bon introuvable ou déjà traité.")
        for l in _lignes(t, "stk_bon_sortie_lignes", T("stk_bon_sortie_lignes").c.bon == bon):
            mid = sortie(t, u, l["article"], b["magasin"], D(l["quantite"]), date_, "bon_sortie", bon, b["projet"],
                         l["poste"], reservation_source=bon)
            t.cx.execute(T("stk_bon_sortie_lignes").update().where(T("stk_bon_sortie_lignes").c.id == l["id"]).values(
                mouvement=mid))
        t.cx.execute(T("stk_reservations").update().where(T("stk_reservations").c.source_id == bon,
                                                          T("stk_reservations").c.statut == "Active").values(
            statut="Consommée"))
        t.maj("stk_bons_sortie", bon, {"statut": "Servi", "servi_par": u["id"], "servi_le": db.maintenant(),
                                       "version": b["version"] + 1})


def annuler_bon(bon: str, motif: str) -> None:
    u = V.actor()
    if not (motif or "").strip():
        raise ValueError("Motif obligatoire.")
    with db.transaction("Annulation de bon de sortie") as t:
        b = _un(t, "stk_bons_sortie", bon, True)
        if not b or b["statut"] != "À servir":
            raise ValueError("Bon introuvable ou déjà servi.")
        if u["id"] != b["demandeur"] and not V.peut(u, "magasin"):
            raise ValueError("Annulation par le demandeur ou le magasin.")
        t.cx.execute(T("stk_reservations").update().where(T("stk_reservations").c.source_id == bon,
                                                          T("stk_reservations").c.statut == "Active").values(
            statut="Annulée"))
        t.maj("stk_bons_sortie", bon, {"statut": "Annulé", "motif": f"{b['motif'] or ''} — annulé : {motif}".strip(" —"),
                                       "version": b["version"] + 1})


# ------------------------------------------------------------------ états
def etat_valorise(tx=None) -> list[dict]:
    arts = {a["id"]: a for a in articles(tx=tx)}
    mags = {m["id"]: m for m in magasins(tx=tx)}
    out = []
    for s in _lignes(tx, "stk_soldes"):
        q = D(s["quantite"])
        if not q:
            continue
        a, m = arts[s["article"]], mags[s["magasin"]]
        out.append(dict(article=a["code"], libelle=a["libelle"], famille=a["famille"], magasin=m["code"],
                        quantite=q, unite=a["unite_stock"], cmup=D(a["cmup"]),
                        valeur=cents(q * D(a["cmup"])), reserve=reserve(tx, a["id"], m["id"])))
    return out


def alertes_seuils(tx=None) -> list[dict]:
    """Articles dont le disponible société passe sous le seuil minimum : proposer un réapprovisionnement."""
    out = []
    for a in articles(True, tx):
        if a["nature"] != "stocke" or a["seuil_min"] is None:
            continue
        dispo = sum((x["disponible"] for x in disponibilites(a["id"], tx)), Decimal(0))
        if dispo < D(a["seuil_min"]):
            out.append(dict(article=a["id"], code=a["code"], libelle=a["libelle"], disponible=dispo,
                            seuil_min=D(a["seuil_min"]), seuil_max=D(a["seuil_max"]) if a["seuil_max"] is not None else None))
    return out


def sorties_chantier(projet: str, tx=None) -> list[dict]:
    m = T("stk_mouvements")
    return _lignes(tx, "stk_mouvements", m.c.projet == projet)
