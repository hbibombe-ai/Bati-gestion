"""Registre des modèles d'import : fonctions, feuilles, champs, relations et versions.

Aucune table n'est choisie à partir du fichier : seules les feuilles et colonnes déclarées ici sont lues,
puis converties par les adaptateurs (imports/adapters) qui appellent les services métier.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import regles as R

VERSION_MODELE = "2026.10-1"
MODES = {
    "archives": "Archives historiques",
    "reprise": "Reprise à une date de bascule",
    "en_cours": "Opérations en cours",
}
EFFETS_MODE = {
    "archives": "Conserve les faits et pièces antérieurs pour consultation. Aucun effet sur la caisse, les coûts, "
                "les budgets actifs ou le grand livre.",
    "reprise": "Prépare des soldes, cumuls, reliquats et engagements restants à la date de bascule. Rien n'est actif "
               "avant la validation Finance puis l'activation par la DG (personnes distinctes de l'importateur).",
    "en_cours": "Crée des fiches de référence, des pointages ou des demandes N0 en brouillon qui suivent ensuite "
                "le circuit habituel (N1 → N2 → N3 → DG). Aucune validation ni aucun paiement n'est créé.",
}
PARAMETRES = ["version_modele", "source_systeme", "mode_import", "date_bascule", "reference_lot"]
ENTITES_DOCUMENT = ["tiers", "chantier", "personnel", "facture_fournisseur", "avance", "besoin", "budget",
                    "ecriture", "compte_tresorerie", "lot"]
COMPTE_RATTACHEMENT = ["cash", "bank", "mobile"]
ROLES_TIERS = {"client": "client", "fournisseur": "supplier", "sous-traitant": "subcontractor",
               "sous_traitant": "subcontractor"}


@dataclass(frozen=True)
class Champ:
    nom: str
    type: str = "text"          # ref, text, date, month, money, qty, int, pct, decimal, enum, bool, filename, sha256
    requis: bool = False
    valeurs: tuple = ()
    max_len: int = 500
    confidentiel: bool = False  # salaires et paie : RH et DG seulement
    aide: str = ""


@dataclass(frozen=True)
class Feuille:
    nom: str
    champs: tuple
    cle: str = "reference_externe"       # identifiant stable de la ligne dans la feuille
    parent: tuple | None = None          # (champ, feuille parente) pour les lignes enfants
    relations: tuple = ()                # ((champ, entité), ...) résolues dans le fichier ou la base
    modes: frozenset = frozenset({"archives"})   # modes avec effet métier réellement développés
    module: str = ""                     # module de droits (auth.DROITS) exigé en écriture
    roles: tuple = ()                    # rôles autorisés (contrôle serveur, en plus du module)
    entite: str = ""                     # nom logique pour la table de correspondance
    statut: str = "réalisé"              # réalisé, préparatoire (archives seulement)

    @property
    def colonnes(self) -> list[str]:
        return [c.nom for c in self.champs]

    def champ(self, nom: str) -> Champ:
        return next(c for c in self.champs if c.nom == nom)


C = Champ
DEV = tuple(R.CURRENCIES)
FEUILLES: dict[str, Feuille] = {f.nom: f for f in [
    Feuille("Tiers", (C("reference_externe", "ref", True, aide="Code tiers stable, ex. F0012"),
                      C("nom", "text", True), C("roles", "text", True, aide="client ; fournisseur ; sous-traitant"),
                      C("telephone"), C("email"), C("adresse", max_len=2000), C("identification", aide="RCCM, NIF…")),
            modes=frozenset({"archives", "reprise", "en_cours"}), module="tiers", roles=("admin", "finance"),
            entite="tiers"),
    Feuille("Chantiers", (C("reference_externe", "ref", True), C("nom", "text", True),
                          C("client_ref", "ref", aide="Code d’un tiers client (fichier ou base)"), C("lieu"),
                          C("devise", "enum", True, DEV), C("date_debut", "date"), C("date_fin", "date"),
                          C("montant_contrat", "money"), C("budget_historique", "money"),
                          C("etat", "enum", True, tuple(R.STATUSES)), C("avancement", "pct", True)),
            relations=(("client_ref", "tiers"),), modes=frozenset({"archives", "reprise", "en_cours"}),
            module="chantiers", roles=("admin", "chantier"), entite="chantier"),
    Feuille("Budgets", (C("reference_externe", "ref", True, aide="Code chantier V7 unique"),
                        C("chantier_ref", "ref", True), C("devise", "enum", True, DEV),
                        C("montant_contrat", "money", True), C("cout_estime_terminaison", "money", True),
                        C("chiffre_affaires_final", "money")),
            relations=(("chantier_ref", "chantier"),), modes=frozenset({"archives", "reprise", "en_cours"}),
            module="depenses", roles=("admin", "finance", "chantier"), entite="budget"),
    Feuille("Lignes_Budget", (C("budget_ref", "ref", True), C("numero_ligne", "int", True),
                              C("code_dqe", "ref", True), C("libelle", "text", True), C("unite"),
                              C("quantite", "qty"), C("prix_unitaire", "money"), C("budget_initial", "money", True),
                              C("budget_revise", "money"), C("prevision", "money")),
            cle="", parent=("budget_ref", "Budgets"), modes=frozenset({"archives", "reprise", "en_cours"}),
            module="depenses", roles=("admin", "finance", "chantier")),
    Feuille("Cumuls_Budget", (C("reference_externe", "ref", True), C("chantier_ref", "ref", True),
                              C("code_dqe", "ref", True), C("devise", "enum", True, DEV),
                              C("couts_executes", "money", True), C("engagements_ouverts", "money", True),
                              C("date_arrete", "date", True)),
            relations=(("chantier_ref", "chantier"),), modes=frozenset({"archives", "reprise"}),
            module="depenses", roles=("admin", "finance"), entite="cumul"),
    Feuille("Besoins", (C("reference_externe", "ref", True), C("chantier_ref", "ref", True),
                        C("code_dqe", "ref", True), C("objet", "text", True), C("beneficiaire_ref", "ref", True),
                        C("nature", "enum", True, ("Achat", "Dépense", "Avance")), C("quantite", "qty"),
                        C("unite"), C("prix_unitaire", "money"), C("montant", "money"),
                        C("devise", "enum", True, DEV), C("echeance", "date", True),
                        C("compte", "text", aide="Compte de coût, 605 par défaut")),
            relations=(("chantier_ref", "chantier"), ("beneficiaire_ref", "tiers")),
            modes=frozenset({"archives", "en_cours"}), module="depenses", roles=("admin", "finance", "chantier"),
            entite="besoin"),
    Feuille("Commandes", (C("reference_externe", "ref", True), C("besoin_ref", "ref"), C("tiers_ref", "ref"),
                          C("date", "date", True), C("devise", "enum", True, DEV), C("montant", "money", True)),
            module="achats", statut="préparatoire"),
    Feuille("Receptions", (C("reference_externe", "ref", True), C("commande_ref", "ref", True),
                           C("date", "date", True), C("quantite", "qty"), C("montant", "money"), C("preuve")),
            parent=("commande_ref", "Commandes"), module="achats", statut="préparatoire"),
    Feuille("Factures_Fournisseurs", (C("reference_externe", "ref", True), C("numero_facture", "text", True),
                                      C("tiers_ref", "ref", True), C("chantier_ref", "ref", True),
                                      C("code_dqe", "ref"), C("date_facture", "date", True),
                                      C("date_echeance", "date", True), C("devise", "enum", True, DEV),
                                      C("montant", "money", True)),
            relations=(("tiers_ref", "tiers"), ("chantier_ref", "chantier")), modes=frozenset({"archives", "reprise"}),
            module="comptes", roles=("admin", "finance"), entite="facture_fournisseur"),
    Feuille("Avances", (C("reference_externe", "ref", True), C("beneficiaire_ref", "ref", True),
                        C("chantier_ref", "ref", True), C("code_dqe", "ref"), C("objet", "text", True),
                        C("date_versement", "date", True), C("devise", "enum", True, DEV),
                        C("montant_verse", "money", True), C("montant_justifie_declare", "money", True),
                        C("montant_restitue", "money", True), C("compte_charge", "text")),
            relations=(("beneficiaire_ref", "tiers"), ("chantier_ref", "chantier")),
            modes=frozenset({"archives", "reprise"}), module="comptes", roles=("admin", "finance"), entite="avance"),
    Feuille("Paiements", (C("reference_externe", "ref", True), C("facture_ref", "ref"), C("avance_ref", "ref"),
                          C("date", "date", True), C("devise", "enum", True, DEV), C("montant", "money", True),
                          C("compte", "text", aide="Référence du compte ou cash, bank, mobile")),
            modes=frozenset({"archives", "reprise"}), module="comptes", roles=("admin", "finance"), entite="paiement"),
    Feuille("Devis", (C("reference_externe", "ref", True), C("tiers_ref", "ref", True), C("chantier_ref", "ref"),
                      C("date", "date", True), C("devise", "enum", True, DEV), C("statut_commercial")),
            module="commercial", statut="préparatoire"),
    Feuille("Lignes_Devis", (C("devis_ref", "ref", True), C("numero_ligne", "int", True), C("designation", "text", True),
                             C("quantite", "qty", True), C("prix_unitaire", "money", True)),
            cle="", parent=("devis_ref", "Devis"), module="commercial", statut="préparatoire"),
    Feuille("Factures_Clients", (C("reference_externe", "ref", True), C("tiers_ref", "ref", True),
                                 C("chantier_ref", "ref"), C("devis_ref", "ref"), C("date", "date", True),
                                 C("echeance", "date"), C("devise", "enum", True, DEV)),
            module="commercial", statut="préparatoire"),
    Feuille("Lignes_Facture", (C("facture_ref", "ref", True), C("numero_ligne", "int", True),
                               C("designation", "text", True), C("quantite", "qty", True),
                               C("prix_unitaire", "money", True)),
            cle="", parent=("facture_ref", "Factures_Clients"), module="commercial", statut="préparatoire"),
    Feuille("Reglements_Clients", (C("reference_externe", "ref", True), C("facture_ref", "ref", True),
                                   C("date", "date", True), C("devise", "enum", True, DEV), C("montant", "money", True),
                                   C("compte", "text")),
            parent=("facture_ref", "Factures_Clients"), module="commercial", statut="préparatoire"),
    Feuille("Comptes_Tresorerie", (C("reference_externe", "ref", True), C("libelle", "text", True),
                                   C("devise", "enum", True, DEV), C("compte_comptable", "ref", True,
                                                                      aide="Subdivision 52… ou 57…"),
                                   C("rattachement", "enum", True, tuple(COMPTE_RATTACHEMENT)),
                                   C("solde_ouverture", "money", True), C("date_solde", "date", True),
                                   C("reference_releve", "text", True, aide="Relevé bancaire ou PV de comptage")),
            modes=frozenset({"archives", "reprise"}), module="tresorerie", roles=("admin", "finance"),
            entite="compte_tresorerie"),
    Feuille("Mouvements_Tresorerie", (C("reference_externe", "ref", True), C("compte_ref", "ref", True),
                                      C("date", "date", True), C("sens", "enum", True, ("entree", "sortie")),
                                      C("devise", "enum", True, DEV), C("montant", "money", True),
                                      C("libelle", "text", True), C("piece")),
            module="tresorerie", statut="préparatoire"),
    Feuille("Ecritures", (C("reference_externe", "ref", True), C("date", "date", True), C("journal", "text", True),
                          C("libelle", "text", True), C("devise", "enum", True, DEV)),
            modes=frozenset({"archives", "reprise"}), module="comptabilite", roles=("admin", "finance"),
            entite="ecriture"),
    Feuille("Lignes_Ecriture", (C("ecriture_ref", "ref", True), C("numero_ligne", "int", True),
                                C("compte", "ref", True), C("libelle"), C("debit", "money", True),
                                C("credit", "money", True)),
            cle="", parent=("ecriture_ref", "Ecritures"), modes=frozenset({"archives", "reprise"}),
            module="comptabilite", roles=("admin", "finance")),
    Feuille("Personnel", (C("reference_externe", "ref", True, aide="Matricule"), C("nom", "text", True),
                          C("fonction", "text", True), C("service"), C("telephone"),
                          C("date_engagement", "date", True), C("lieu", "enum", True, ("Bureau", "Chantier")),
                          C("chantier_ref", "ref"), C("actif", "bool", True),
                          C("type_contrat", "enum", False, tuple(R.HR_CONTRACTS)), C("reference_contrat"),
                          C("fin_contrat", "date"), C("salaire_base", "money", confidentiel=True),
                          C("devise_salaire", "enum", False, DEV, confidentiel=True),
                          C("periode_salaire", "enum", False, tuple(R.HR_PAY_PERIODS), confidentiel=True),
                          C("salaire_effet", "date", confidentiel=True)),
            relations=(("chantier_ref", "chantier"),), modes=frozenset({"archives", "reprise", "en_cours"}),
            module="personnel", roles=("admin", "rh"), entite="personnel"),
    Feuille("Affectations", (C("reference_externe", "ref", True), C("matricule", "ref", True),
                             C("date_debut", "date", True), C("lieu", "enum", True, ("Bureau", "Chantier")),
                             C("chantier_ref", "ref")),
            relations=(("matricule", "personnel"), ("chantier_ref", "chantier")),
            modes=frozenset({"archives", "reprise", "en_cours"}), module="personnel", roles=("admin", "rh"),
            entite="affectation"),
    Feuille("Presences", (C("matricule", "ref", True), C("date", "date", True),
                          C("statut", "enum", True, tuple(R.ATTENDANCE_STATUSES)), C("heures", "qty", True),
                          C("lieu", "ref", aide="« bureau » ou référence de chantier ; vide = affectation datée"),
                          C("observation")),
            cle="", relations=(("matricule", "personnel"),), modes=frozenset({"archives", "reprise", "en_cours"}),
            module="pointage", roles=("admin", "rh", "chantier")),
    Feuille("Paie", (C("matricule", "ref", True), C("mois", "month", True), C("devise", "enum", True, DEV),
                     C("brut", "money", True, confidentiel=True), C("net", "money", True, confidentiel=True),
                     C("elements", "text", confidentiel=True, max_len=2000)),
            cle="", module="paie", roles=("admin", "rh"), statut="préparatoire"),
    Feuille("Stocks", (C("reference_externe", "ref", True), C("article", "text", True), C("unite"),
                       C("quantite", "qty", True), C("emplacement"), C("chantier_ref", "ref")),
            module="achats", statut="préparatoire"),
    Feuille("Materiels", (C("reference_externe", "ref", True), C("designation", "text", True), C("numero_serie"),
                          C("etat"), C("emplacement"), C("chantier_ref", "ref")),
            module="charroi", statut="préparatoire"),
    Feuille("Situations", (C("reference_externe", "ref", True), C("chantier_ref", "ref", True),
                           C("periode", "month", True), C("avancement", "pct", True), C("quantites", "qty"),
                           C("montant", "money", True), C("devise", "enum", True, DEV), C("facture_ref", "ref")),
            module="projets", statut="préparatoire"),
    Feuille("Fiscalite", (C("reference_externe", "ref", True), C("periode", "text", True), C("impot", "text", True),
                          C("base", "money"), C("montant", "money", True), C("devise", "enum", True, DEV),
                          C("echeance", "date", True), C("paiement_ref"), C("date_paiement", "date")),
            module="comptabilite", statut="préparatoire"),
    Feuille("Taux", (C("reference_externe", "ref", True), C("devise_source", "enum", True, DEV),
                     C("devise_cible", "enum", True, DEV), C("taux", "decimal", True), C("date", "date", True)),
            module="comptabilite", statut="préparatoire"),
    Feuille("Documents", (C("reference_externe", "ref", True), C("entite_cible", "enum", True, tuple(ENTITES_DOCUMENT)),
                          C("reference_cible", "ref", True), C("nom_fichier", "filename", True),
                          C("type", "enum", True, tuple(R.PIECE_TYPES)), C("date", "date", True),
                          C("empreinte_sha256", "sha256")),
            modes=frozenset({"archives", "reprise", "en_cours"}), module="justificatifs",
            roles=("admin", "finance", "chantier"), entite="document"),
]}


@dataclass(frozen=True)
class Fonction:
    cle: str
    libelle: str
    feuilles: tuple
    description: str = ""


FONCTIONS: dict[str, Fonction] = {f.cle: f for f in [
    Fonction("tiers", "Tiers", ("Tiers",), "Clients, fournisseurs et sous-traitants ; rapprochement par code."),
    Fonction("chantiers", "Chantiers", ("Chantiers",), "Chantiers, client, devise, dates, état et avancement."),
    Fonction("budgets", "DQE et budgets", ("Budgets", "Lignes_Budget", "Cumuls_Budget"),
             "Budgets V7 à approuver ; cumuls de coûts et engagements à la date de bascule."),
    Fonction("besoins", "Besoins de dépense", ("Besoins",), "Une demande N0 en brouillon par ligne."),
    Fonction("achats", "Achats et réceptions", ("Commandes", "Receptions"), "Archives seulement (préparatoire)."),
    Fonction("fournisseurs", "Factures fournisseurs, paiements et avances",
             ("Factures_Fournisseurs", "Paiements", "Avances"),
             "Archives des montants initiaux ; reprise des dettes et avances restantes."),
    Fonction("commercial", "Devis et factures clients",
             ("Devis", "Lignes_Devis", "Factures_Clients", "Lignes_Facture", "Reglements_Clients"),
             "Archives seulement (préparatoire)."),
    Fonction("tresorerie", "Trésorerie", ("Comptes_Tresorerie", "Mouvements_Tresorerie"),
             "Comptes V7 et soldes d’ouverture rapprochés ; mouvements anciens en archives."),
    Fonction("comptabilite", "Comptabilité", ("Ecritures", "Lignes_Ecriture"),
             "Balance d’ouverture équilibrée à approuver ; écritures anciennes en archives."),
    Fonction("personnel", "Personnel et affectations", ("Personnel", "Affectations"),
             "Fiches et affectations ; salaires réservés RH et DG."),
    Fonction("presences", "Présences", ("Presences",), "Un pointage par personne et par jour."),
    Fonction("paie", "Paie", ("Paie",), "Archives seulement : aucun paiement n’est déclenché."),
    Fonction("stocks", "Stocks et matériels", ("Stocks", "Materiels"), "Archives et dossiers préparatoires."),
    Fonction("situations", "Situations de travaux", ("Situations",), "Archives seulement (préparatoire)."),
    Fonction("fiscalite", "Fiscalité et taux", ("Fiscalite", "Taux"), "Archives ; paramètres à confirmer séparément."),
    Fonction("documents", "Pièces et documents", ("Documents",), "Manifeste Excel + fichiers PDF, JPEG ou PNG."),
]}
ORDRE_FEUILLES = list(FEUILLES)   # ordre d'import : référentiels, chantiers, budgets, dossiers, reliquats, compta…
FONCTIONS["globale"] = Fonction("globale", "Reprise globale", tuple(ORDRE_FEUILLES),
                                "Toutes les feuilles liées, importées dans un ordre contrôlé.")


def fonction(cle: str) -> Fonction:
    if cle not in FONCTIONS:
        raise ValueError("Fonction d’import inconnue.")
    return FONCTIONS[cle]
