"""Tables relationnelles V8 du lot achats et stocks (mémo V8, § 4, § 5 et § 11.1).

Quantités en Numeric (décimales exactes), montants en centimes entiers (BigInteger), coût moyen en centimes
Numeric. Chaque table porte la traçabilité commune : auteur, date de création, version, statut.
"""
import sqlalchemy as sa

Q = sa.Numeric(18, 4)          # quantités
M = sa.BigInteger              # montants en centimes
C = sa.Numeric(24, 6)          # coût unitaire en centimes (CMUP)


def _trace():
    return [sa.Column("cree_par", sa.Integer, nullable=True), sa.Column("cree_le", sa.DateTime, nullable=False),
            sa.Column("version", sa.Integer, nullable=False, default=1)]


def ajouter(meta):
    # ------------------------------------------------------------------ référentiels de stock
    sa.Table("stk_familles", meta,
             sa.Column("code", sa.String(30), primary_key=True),
             sa.Column("libelle", sa.String(200), nullable=False),
             sa.Column("compte_stock", sa.String(20), nullable=False, default=""),    # 32x / 33x (vide : non stocké)
             sa.Column("compte_charge", sa.String(20), nullable=False),              # 602 / 604 / 605x / 6032…
             sa.Column("compte_variation", sa.String(20), nullable=False, default=""),  # 6032 / 6033
             sa.Column("actif", sa.Boolean, nullable=False, default=True),
             *_trace())
    sa.Table("stk_articles", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("code", sa.String(60), nullable=False, unique=True),
             sa.Column("libelle", sa.String(300), nullable=False),
             sa.Column("famille", sa.String(30), sa.ForeignKey("stk_familles.code"), nullable=False),
             sa.Column("nature", sa.String(20), nullable=False),          # stocke, non_stocke, prestation
             sa.Column("unite_stock", sa.String(30), nullable=False),
             sa.Column("unite_achat", sa.String(30), nullable=False),
             sa.Column("coefficient", Q, nullable=False, default=1),       # 1 unité d'achat = n unités de stock
             sa.Column("seuil_min", Q, nullable=True),
             sa.Column("seuil_max", Q, nullable=True),
             sa.Column("qte_totale", Q, nullable=False, default=0),        # toute la société, pour le CMUP
             sa.Column("valeur_totale", M, nullable=False, default=0),     # en monnaie de tenue
             sa.Column("cmup", C, nullable=False, default=0),
             sa.Column("actif", sa.Boolean, nullable=False, default=True),
             sa.Column("a_qualifier", sa.Boolean, nullable=False, default=False),
             sa.CheckConstraint("nature in ('stocke', 'non_stocke', 'prestation')", name="ck_article_nature"),
             sa.CheckConstraint("coefficient > 0", name="ck_article_coefficient"),
             sa.CheckConstraint("qte_totale >= 0", name="ck_article_qte"),
             *_trace())
    sa.Table("stk_magasins", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("code", sa.String(40), nullable=False, unique=True),
             sa.Column("libelle", sa.String(200), nullable=False),
             sa.Column("type", sa.String(20), nullable=False),             # central, chantier, transit
             sa.Column("projet", sa.String(80), nullable=True),
             sa.Column("responsable", sa.Integer, nullable=True),
             sa.Column("adjoint", sa.Integer, nullable=True),
             sa.Column("actif", sa.Boolean, nullable=False, default=True),
             sa.CheckConstraint("type in ('central', 'chantier', 'transit')", name="ck_magasin_type"),
             *_trace())
    sa.Table("stk_soldes", meta,
             sa.Column("article", sa.String(80), sa.ForeignKey("stk_articles.id"), primary_key=True),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), primary_key=True),
             sa.Column("quantite", Q, nullable=False, default=0),
             sa.Column("version", sa.Integer, nullable=False, default=1),
             sa.CheckConstraint("quantite >= 0", name="ck_solde_positif"))
    sa.Table("stk_mouvements", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("numero", sa.String(40), nullable=False, unique=True),
             sa.Column("type", sa.String(30), nullable=False),             # entree_reception, sortie, ...
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("article", sa.String(80), sa.ForeignKey("stk_articles.id"), nullable=False),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), nullable=False),
             sa.Column("quantite", Q, nullable=False),                     # signée : + entrée, − sortie
             sa.Column("valeur", M, nullable=False),                       # signée, monnaie de tenue
             sa.Column("cmup_apres", C, nullable=False),
             sa.Column("devise_tenue", sa.String(3), nullable=False),
             sa.Column("cout_devise", sa.String(3), nullable=True),         # coût d'origine (analyse)
             sa.Column("cout_origine", M, nullable=True),
             sa.Column("taux", sa.String(40), nullable=True),
             sa.Column("projet", sa.String(80), nullable=True),
             sa.Column("poste", sa.String(80), nullable=True),
             sa.Column("source_type", sa.String(40), nullable=False),
             sa.Column("source_id", sa.String(80), nullable=False),
             sa.Column("contre_passe", sa.String(80), nullable=True),
             sa.Column("statut", sa.String(20), nullable=False, default="Validé"),
             *_trace(),
             sa.Index("ix_stk_mvt_article_magasin", "article", "magasin"),
             sa.Index("ix_stk_mvt_source", "source_type", "source_id"),
             sa.Index("ix_stk_mvt_projet", "projet", "poste"))
    sa.Table("stk_bons_sortie", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("numero", sa.String(40), nullable=False, unique=True),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), nullable=False),
             sa.Column("projet", sa.String(80), nullable=False),
             sa.Column("demandeur", sa.Integer, nullable=True),
             sa.Column("date_souhaitee", sa.String(10), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False),           # À servir, Servi, Annulé
             sa.Column("servi_par", sa.Integer, nullable=True),
             sa.Column("servi_le", sa.DateTime, nullable=True),
             sa.Column("motif", sa.Text, nullable=True),
             *_trace())
    sa.Table("stk_bon_sortie_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("bon", sa.String(80), sa.ForeignKey("stk_bons_sortie.id"), nullable=False),
             sa.Column("article", sa.String(80), sa.ForeignKey("stk_articles.id"), nullable=False),
             sa.Column("poste", sa.String(80), nullable=False),
             sa.Column("quantite", Q, nullable=False),
             sa.Column("mouvement", sa.String(80), nullable=True),
             sa.CheckConstraint("quantite > 0", name="ck_bs_qte"))
    sa.Table("stk_reservations", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("article", sa.String(80), sa.ForeignKey("stk_articles.id"), nullable=False),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), nullable=False),
             sa.Column("quantite", Q, nullable=False),
             sa.Column("source_type", sa.String(40), nullable=False),
             sa.Column("source_id", sa.String(80), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False),           # Active, Consommée, Annulée
             *_trace(),
             sa.Index("ix_stk_resa_article_magasin", "article", "magasin", "statut"))

    # ------------------------------------------------------------------ achats
    sa.Table("ach_demandes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("numero", sa.String(60), nullable=False, unique=True),
             sa.Column("projet", sa.String(80), nullable=False),
             sa.Column("devise", sa.String(3), nullable=False),            # devise du budget DQE
             sa.Column("demandeur", sa.Integer, nullable=False),
             sa.Column("date_souhaitee", sa.String(10), nullable=False),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), nullable=True),
             sa.Column("urgence", sa.String(20), nullable=False, default="Normale"),
             sa.Column("justification", sa.Text, nullable=False, default=""),
             sa.Column("statut", sa.String(20), nullable=False),           # Brouillon, Soumise, Approuvée, Annulée
             sa.Column("niveau", sa.Integer, nullable=False, default=0),
             sa.Column("approbations", sa.JSON, nullable=False),
             sa.Column("derogation_dg", sa.Boolean, nullable=False, default=False),
             sa.Column("historique", sa.JSON, nullable=False),
             sa.Column("origine", sa.String(120), nullable=False, default=""),   # import, reprise transitoire…
             *_trace(),
             sa.Index("ix_ach_dem_projet", "projet", "statut"))
    sa.Table("ach_demande_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("demande", sa.String(80), sa.ForeignKey("ach_demandes.id"), nullable=False),
             sa.Column("numero", sa.Integer, nullable=False),
             sa.Column("article", sa.String(80), sa.ForeignKey("stk_articles.id"), nullable=False),
             sa.Column("poste", sa.String(80), nullable=False),
             sa.Column("quantite", Q, nullable=False),                     # en unité de stock
             sa.Column("prix_estime", M, nullable=False),                  # par unité de stock, devise de la demande
             sa.Column("fournisseur_suggere", sa.String(80), nullable=True),
             sa.Column("motif_hors_stock", sa.Text, nullable=True),
             sa.Column("cloturee", sa.Boolean, nullable=False, default=False),
             sa.Column("motif_cloture", sa.Text, nullable=True),
             sa.Column("note", sa.Text, nullable=True),
             sa.UniqueConstraint("demande", "numero", name="un_ligne_demande"),
             sa.CheckConstraint("quantite > 0", name="ck_dl_qte"),
             sa.CheckConstraint("prix_estime >= 0", name="ck_dl_prix"))
    sa.Table("ach_commandes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("numero", sa.String(60), nullable=False, unique=True),
             sa.Column("fournisseur", sa.String(80), nullable=False),
             sa.Column("devise", sa.String(3), nullable=False),
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False),           # Émise, Annulée
             sa.Column("devis", sa.JSON, nullable=False),                  # mise en concurrence
             sa.Column("conditions", sa.Text, nullable=False, default=""),
             sa.Column("historique", sa.JSON, nullable=False),
             *_trace())
    sa.Table("ach_commande_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("commande", sa.String(80), sa.ForeignKey("ach_commandes.id"), nullable=False),
             sa.Column("demande_ligne", sa.String(80), sa.ForeignKey("ach_demande_lignes.id"), nullable=False),
             sa.Column("magasin", sa.String(80), sa.ForeignKey("stk_magasins.id"), nullable=True),
             sa.Column("quantite", Q, nullable=False),
             sa.Column("prix_unitaire", M, nullable=False),               # devise de la commande
             sa.Column("taux_budget", sa.String(40), nullable=False),     # devise commande → devise du budget
             sa.Column("montant_budget", M, nullable=False),              # engagement ferme, devise du budget
             sa.CheckConstraint("quantite > 0", name="ck_cl_qte"),
             sa.CheckConstraint("prix_unitaire >= 0", name="ck_cl_prix"))
    sa.Table("ach_receptions", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("numero", sa.String(60), nullable=False, unique=True),
             sa.Column("commande", sa.String(80), sa.ForeignKey("ach_commandes.id"), nullable=False),
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("bl", sa.String(120), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False, default="Validée"),
             *_trace())
    sa.Table("ach_reception_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("reception", sa.String(80), sa.ForeignKey("ach_receptions.id"), nullable=False),
             sa.Column("commande_ligne", sa.String(80), sa.ForeignKey("ach_commande_lignes.id"), nullable=False),
             sa.Column("qte_acceptee", Q, nullable=False),
             sa.Column("qte_rejetee", Q, nullable=False, default=0),
             sa.Column("motif_rejet", sa.Text, nullable=True),
             sa.Column("mouvement", sa.String(80), nullable=True),
             sa.Column("cout_budget", M, nullable=False, default=0),      # coût réalisé (non stocké, prestation)
             sa.CheckConstraint("qte_acceptee >= 0 and qte_rejetee >= 0", name="ck_rl_qte"))
    sa.Table("ach_factures", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("fournisseur", sa.String(80), nullable=False),
             sa.Column("reference", sa.String(120), nullable=False),
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("echeance", sa.String(10), nullable=False),
             sa.Column("devise", sa.String(3), nullable=False),
             sa.Column("montant_ht", M, nullable=False),
             sa.Column("tva", M, nullable=False, default=0),               # saisie depuis la facture, aucun taux
             sa.Column("statut", sa.String(20), nullable=False),           # Enregistrée, Validée, Rejetée
             sa.Column("valide_par", sa.Integer, nullable=True),
             sa.Column("valide_le", sa.DateTime, nullable=True),
             sa.Column("paiements", sa.JSON, nullable=False),
             sa.Column("historique", sa.JSON, nullable=False),
             sa.UniqueConstraint("fournisseur", "reference", name="un_facture_fournisseur"),
             *_trace())
    sa.Table("ach_facture_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("facture", sa.String(80), sa.ForeignKey("ach_factures.id"), nullable=False),
             sa.Column("commande_ligne", sa.String(80), sa.ForeignKey("ach_commande_lignes.id"), nullable=False),
             sa.Column("quantite", Q, nullable=False),
             sa.Column("prix_unitaire", M, nullable=False),
             sa.Column("ecart_budget", M, nullable=False, default=0),      # écart de prix porté en charge
             sa.CheckConstraint("quantite > 0", name="ck_fl_qte"))


def ajouter_compta(meta):
    """Socle comptable (mémo V8, § 2) : plan, journaux, exercices, périodes, pièces, lignes, règles."""
    sa.Table("cpt_comptes", meta,
             sa.Column("numero", sa.String(20), primary_key=True),
             sa.Column("libelle", sa.String(300), nullable=False),
             sa.Column("classe", sa.Integer, nullable=False),
             sa.Column("collectif", sa.Boolean, nullable=False, default=False),   # 401, 411, 422… (tiers obligatoire)
             sa.Column("actif", sa.Boolean, nullable=False, default=True),
             sa.Column("origine", sa.String(30), nullable=False),                  # regle_defaut, import_plan, sous_compte
             *_trace())
    sa.Table("cpt_journaux", meta,
             sa.Column("code", sa.String(10), primary_key=True),
             sa.Column("libelle", sa.String(200), nullable=False),
             sa.Column("type", sa.String(10), nullable=False),                     # ACH, VTE, BQ, CA, MM, PAI, STK, IMM, OD, AN
             sa.Column("compte_tresorerie", sa.String(20), sa.ForeignKey("cpt_comptes.numero"), nullable=True),
             sa.Column("v7_compte", sa.String(80), nullable=True, unique=True),    # compte de trésorerie V7 relié
             sa.Column("actif", sa.Boolean, nullable=False, default=True),
             *_trace())
    sa.Table("cpt_periodes", meta,
             sa.Column("id", sa.String(7), primary_key=True),                      # AAAA-MM
             sa.Column("exercice", sa.Integer, nullable=False),
             sa.Column("statut", sa.String(30), nullable=False),                   # Ouverte, Clôturée provisoirement, Clôturée définitivement
             sa.Column("historique", sa.JSON, nullable=False),
             sa.Column("version", sa.Integer, nullable=False, default=1))
    sa.Table("cpt_pieces", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("journal", sa.String(10), sa.ForeignKey("cpt_journaux.code"), nullable=False),
             sa.Column("exercice", sa.Integer, nullable=False),
             sa.Column("numero", sa.Integer, nullable=False),
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("libelle", sa.String(300), nullable=False),
             sa.Column("source_type", sa.String(40), nullable=False),
             sa.Column("source_id", sa.String(80), nullable=False),
             sa.Column("evenement", sa.String(40), nullable=False),
             sa.Column("regle_version", sa.Integer, nullable=False),
             sa.Column("devise_tenue", sa.String(3), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False),                   # Validée
             sa.Column("contre_passe", sa.String(80), nullable=True),
             *_trace(),
             sa.UniqueConstraint("journal", "exercice", "numero", name="un_piece_numero"),
             sa.Index("ix_cpt_piece_source", "source_type", "source_id"))
    sa.Table("cpt_lignes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("piece", sa.String(80), sa.ForeignKey("cpt_pieces.id"), nullable=False),
             sa.Column("numero", sa.Integer, nullable=False),
             sa.Column("compte", sa.String(20), sa.ForeignKey("cpt_comptes.numero"), nullable=False),
             sa.Column("tiers", sa.String(80), nullable=True),
             sa.Column("projet", sa.String(80), nullable=True),
             sa.Column("poste", sa.String(80), nullable=True),
             sa.Column("centre", sa.String(80), nullable=True),
             sa.Column("libelle", sa.String(300), nullable=False, default=""),
             sa.Column("debit", M, nullable=False, default=0),                     # monnaie de tenue
             sa.Column("credit", M, nullable=False, default=0),
             sa.Column("devise", sa.String(3), nullable=False),                    # devise d'origine
             sa.Column("montant_devise", M, nullable=False),
             sa.Column("taux", sa.String(40), nullable=False),
             sa.Column("echeance", sa.String(10), nullable=True),
             sa.Column("lettrage", sa.String(20), nullable=True),
             sa.CheckConstraint("debit >= 0 and credit >= 0 and (debit = 0 or credit = 0)", name="ck_ligne_sens"),
             sa.Index("ix_cpt_ligne_compte", "compte"),
             sa.Index("ix_cpt_ligne_analytique", "projet", "poste"))
    sa.Table("regles_comptables", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("evenement", sa.String(40), nullable=False),
             sa.Column("version", sa.Integer, nullable=False),
             sa.Column("journal", sa.String(10), nullable=False),                  # code ou « BQ » (journal du compte)
             sa.Column("schema", sa.JSON, nullable=False),
             sa.Column("date_effet", sa.String(10), nullable=False),
             sa.Column("statut", sa.String(20), nullable=False),                   # Proposée, Active, Remplacée, Rejetée
             sa.Column("motif", sa.Text, nullable=False, default=""),
             sa.Column("propose_par", sa.Integer, nullable=True),
             sa.Column("active_par", sa.Integer, nullable=True),
             sa.Column("active_le", sa.DateTime, nullable=True),
             sa.Column("cree_le", sa.DateTime, nullable=False),
             sa.UniqueConstraint("evenement", "version", name="un_regle_version"))


def ajouter_caisse(meta):
    """Arrêtés de caisse (mémo V8, § 9.1 « Caisses arrêtées ») : comptage des billets, écart avec le solde théorique,
    validation par une autre personne et régularisation de l'écart."""
    sa.Table("caisse_arretes", meta,
             sa.Column("id", sa.String(80), primary_key=True),
             sa.Column("caisse", sa.String(120), nullable=False),          # v7:<id du compte> ou h:<compte>:<devise>
             sa.Column("libelle_caisse", sa.String(300), nullable=False),
             sa.Column("devise", sa.String(3), nullable=False),
             sa.Column("date", sa.String(10), nullable=False),
             sa.Column("solde_theorique", sa.BigInteger, nullable=False),
             sa.Column("billetage", sa.JSON, nullable=False),             # {coupure: nombre}
             sa.Column("autres", sa.BigInteger, nullable=False, default=0),  # pièces, bons, monnaie non détaillée
             sa.Column("montant_compte", sa.BigInteger, nullable=False),
             sa.Column("ecart", sa.BigInteger, nullable=False),
             sa.Column("explication", sa.String(1000), nullable=False, default=""),
             sa.Column("statut", sa.String(20), nullable=False),           # Proposé, Validé, Rejeté
             sa.Column("saisi_par", sa.Integer, nullable=False),
             sa.Column("saisi_le", sa.DateTime, nullable=False),
             sa.Column("decide_par", sa.Integer, nullable=True),
             sa.Column("decide_le", sa.DateTime, nullable=True),
             sa.Column("motif_decision", sa.String(1000), nullable=True),
             sa.Column("mouvement_ecart", sa.String(80), nullable=True),    # mouvement de régularisation
             sa.Column("version", sa.Integer, nullable=False, default=1),
             sa.Index("ix_caisse_arrete_caisse_date", "caisse", "date"))
