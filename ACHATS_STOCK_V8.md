# Achats, stock et socle comptable — V8

Version du 16 octobre 2026. Mise en œuvre du mémo V8 : § 4 (stock permanent), § 5 (circuit d’achat), une première partie du § 2 et du § 3 (socle comptable et comptabilisation des achats et du stock), § 10 (droits, séparation des fonctions, dérogations).

Décisions retenues : **monnaie de tenue USD** (à enregistrer par la DG dans l’application, avec la référence de la décision) ; circuit transitoire du 16 octobre remplacé par le circuit du § 5.

## Circuit d’achat (Achats & Stocks › Achats et stock)

| Étape | Qui | Effet automatique | Contrôle bloquant |
|---|---|---|---|
| 1. Besoin du chantier | Équipe chantier (`demandes_achat`) | Le disponible du magasin part en bon de sortie, avec réservation ; le manque devient une demande d’achat | Pas d’achat d’une quantité disponible en stock, sauf motif |
| 2. Soumission N0 | Demandeur | Engagement prévisionnel sur le poste DQE | Article qualifié ; seuils 70 / 85 / 95 / 100 % affichés et confirmés |
| 3. N1 → N2 → N3 → DG | Niveaux et délégations de la politique V7 | « Approuvée » ; toute modification relance le circuit | Validateurs distincts ; au-delà de 100 %, dérogation DG explicite |
| 4. Bon de commande | Acheteur (`chiffrage_achats`) | Plusieurs demandes, un fournisseur ; engagement ferme converti dans la devise du budget au taux du jour | Quantité ≤ approuvée ; prix ≤ estimation + tolérance ; nombre de devis au-delà du seuil |
| 5. Réception | Magasin (`magasin`) | Entrée en stock au coût d’achat converti en monnaie de tenue, CMUP recalculé, écriture STK ; pour un non-stocké ou une prestation, coût réalisé | Cumul reçu ≤ commandé + tolérance ; réceptionnaire ≠ demandeur |
| 6. Facture | Comptabilité fournisseurs (`factures_achat`) | Rapprochement à 3 voies ; écriture ACH ; écart de prix porté sur le stock restant, ou en charge du poste si l’article est sorti | Quantité ≤ reçue ; prix = commandé + tolérance ; total = lignes ; référence unique par fournisseur ; saisie ≠ validation ; acheteur ≠ validateur |
| 7. Paiement | Trésorerie | Mouvement de trésorerie V7 ; écriture BQ ; écart de change en 676 / 776 | Compte de même devise ; ≤ reste dû ; solde suffisant ; trésorier ≠ demandeur, validateurs et comptabilité |
| 8. Sortie vers le chantier | Magasin | Sortie au CMUP, écriture STK analytique, coût réalisé sur le poste DQE | Stock disponible (physique − réservé) suffisant |

Statuts des lignes, déduits des documents : Brouillon → Soumise → Approuvée → Partiellement commandée → Commandée → Partiellement reçue → Reçue → Facturée → Soldée. Une ligne non livrée se solde par une clôture motivée, qui libère l’engagement restant. Chaque demande affiche sa chaîne : commandes, réceptions, factures.

Budget DQE : les engagements et coûts du circuit sont intégrés au calcul V7 (`gestion_v7.metrics`) : prévisionnel à la soumission, ferme à la commande, réalisé à la sortie (stocké) ou à la réception (non stocké, prestation). Le paiement ne crée jamais un second coût.

## Paramètres, tous dynamiques

| Paramètre | Fixé par | Sans valeur |
|---|---|---|
| Monnaie de tenue | DG, avec référence de décision ; figée dès le premier mouvement de stock | Valorisation du stock et écritures bloquées |
| Tolérances quantité et prix | DG | Commandes, réceptions et factures bloquées |
| Seuil de mise en concurrence et nombre de devis | DG, par devise | Pas d’exigence de devis |
| Niveaux de validation, seuils d’alerte | Politique V7 existante | — |
| Familles d’articles et leurs comptes | Comptabilité | — |
| Articles, unités, coefficients, seuils, magasins | Achats (écran ou import Excel) | — |
| Règles comptables | Finance propose, DG active (versionnées, datées) | Règles par défaut du mémo § 3.2 |
| Plan de comptes | Comptabilité, import du plan validé | Comptes des règles par défaut seulement |
| Taux de change | Finance, chaque jour | Opération en devise bloquée |
| Dérogations à la séparation des fonctions | DG : nominatives, datées, motivées, listées | — |

## Socle comptable (Comptabilité & Documents › Comptabilité générale)

- Tables relationnelles : `cpt_comptes`, `cpt_journaux`, `cpt_periodes`, `cpt_pieces`, `cpt_lignes`, `regles_comptables`.
- `comptabilisation.py` est le seul module qui écrit les pièces. Chaque pièce est équilibrée en monnaie de tenue, numérotée sans trou par journal et par exercice, et renvoie à son opération source. Chaque ligne garde sa devise, son montant et son taux d’origine, ainsi que le tiers et l’analytique (chantier et poste, ou centre de coûts).
- Journaux créés : ACH, STK, OD, et un journal BQ, CA ou MM par compte de trésorerie, à son premier paiement.
- Périodes : l’exercice s’ouvre avec ses 12 périodes à la première écriture. Une clôture provisoire est faite par la comptabilité ; la réouverture motivée et la clôture définitive par la DG. Aucune écriture n’est possible dans une période fermée.
- Comptes : seuls les comptes des règles par défaut sont créés (32, 33, 401, 445, 521, 55, 57, 602, 604, 605, 6032, 6033, 676, 776). Un sous-compte (321, 5211…) est créé automatiquement sous un compte parent existant. **Le plan SYSCOHADA complet n’est pas écrit dans le code** : il s’importe depuis le fichier validé par l’expert-comptable (CSV ou Excel : numero, libelle, collectif).
- États : balance, grand livre, pièces par journal. Contrôle permanent : valeur du stock = soldes des comptes de stock.

## Ce qui reste à faire (lots suivants du mémo)

- **Lot 1, suite** : la comptabilisation de la trésorerie, des dépenses, des avances et du circuit V7 est faite (voir COMPTABILITE_V8.md). Restent le lettrage, l’import du plan SYSCOHADA et la table de passage V7 → SYSCOHADA validée par l’expert-comptable.
- **Lot 2, suite** : transferts entre magasins, retours (chantier, fournisseur), inventaires avec gel du magasin et validation des écarts (les droits `magasin_inventaire` et `magasin_ecarts` existent déjà), frais d’approche, stock d’ouverture par le journal AN, quantités en unité d’achat (le coefficient est enregistré, mais les quantités se saisissent en unité de stock).
- **Lots 3 à 7** : ventes et situations, paie, immobilisations et engins, clôture et états SYSCOHADA, facture normalisée DGI.

## Reprise de l’existant

- Les dossiers préparatoires « Demandes », « Commandes », « Réceptions », « Magasins » et « Articles » passent en lecture seule.
- Les demandes du circuit transitoire non encore transmises au V7 se reprennent en brouillon. Il faut être DG : onglet Paramètres, « Reprise ». Les articles libres sont rapprochés du référentiel par libellé, sinon créés « à qualifier » ; la soumission reste bloquée tant que les achats ne les ont pas qualifiés.
- Les opérations V7 déjà transmises restent dans l’ancien mode, jusqu’à leur solde.

## Droits (rubrique Utilisateurs)

Nouvelles rubriques : `factures_achat`, `magasin`, `magasin_inventaire`, `magasin_ecarts`. `chiffrage_achats` devient « Achats — bons de commande ». Les rubriques `approbation_chantier` et `approbation_coordonnateur` du circuit transitoire sont supprimées : le chef de chantier et le coordonnateur valident au niveau N1. Les postes standards ont été ajustés ; les accès réglés pour une personne restent prioritaires.

## Vérifications

- `tests/test_achats_v8.py` (21 tests) : scénario 1 du mémo de bout en bout (CMUP, statuts, coût réalisé à la sortie, balance équilibrée, stock = comptes 32, fournisseur soldé, numérotation sans trou) ; stock disponible et stock jamais négatif ; validateurs distincts ; dérogation au-delà de 100 % ; modification qui relance le circuit ; tolérances, paramètres manquants, mise en concurrence ; commande regroupant plusieurs demandes ; contrôles de réception et de facture ; séparation des fonctions et dérogation nominative ; commande en CDF au taux historique ; monnaie de tenue obligatoire et figée ; écart de change 776 ; période clôturée ; contre-passation ; règle proposée par la Finance et activée par la DG ; prestation ; reprise ; import Excel.
- `tests/test_migrations.py` et `tests/test_sauvegardes.py` (lot 0).
- `tests/test_comptabilite_lot1.py` (9 tests) : comptabilisation V7 et trésorerie historique.
- Toute la suite existante est verte (159 tests). Les trois tests d’écran Streamlit (AppTest) sont à lancer chez vous. Les écrans ont été parcourus avec un Streamlit simulé pour les 10 profils de test, ainsi que les formulaires de besoin, de commande et de réception.
