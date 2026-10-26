# Comptabilisation des opérations existantes — V8, lot 1 (suite)

Version du 16 octobre 2026. Cette étape complète le socle comptable (voir ACHATS_STOCK_V8.md). Le circuit financier V7, le journal de caisse, les dépenses et les comptes tiers produisent désormais leurs pièces automatiquement, par `comptabilisation.py`, avec les règles versionnées (Finance propose, DG active).

## Date de démarrage

La DG fixe, avec la monnaie de tenue, une **date de démarrage comptable** (Achats et stock › Paramètres). Les opérations existantes ne sont comptabilisées qu’à partir de cette date. Sans date, rien n’est comptabilisé pour ces opérations, mais le stock et les achats V8 le restent. Une fois que des écritures existent, la date ne peut plus être reculée ni retirée.

## Ce qui est comptabilisé

| Opération | Journal | Écriture (règle par défaut) |
|---|---|---|
| Solde d’ouverture d’un compte V7 | BQn / CAn / MMn | Trésorerie / compte d’ouverture (paramètre, par ex. 12) |
| Facture sur opération V7 | ACH | Charge du poste (compte de l’opération) / 401, avec analytique chantier et poste DQE |
| Paiement V7 | BQn / CAn / MMn | 401 / trésorerie ; écart de change en 676 / 776 au taux historique |
| Avance V7 versée | trésorerie | 581 / trésorerie |
| Justification validée | OD | Charge du poste / 581 |
| Restitution du reliquat | trésorerie | Trésorerie / 581 |
| Virement entre comptes | les deux journaux | Départ : 585 / trésorerie ; arrivée : trésorerie / 585 |
| Contre-passation d’un paiement | trésorerie | Écriture inverse, datée du jour |
| Dépense (journal de caisse) | CAH / BQH / MMH | Compte de la catégorie / trésorerie |
| Encaissement client | CAH / BQH / MMH | Trésorerie / 411 (tiers client) |
| Paiement fournisseur | CAH / BQH / MMH | 401 si le paiement est affecté à des factures, sinon 4091 (avance) / trésorerie |
| Mouvement manuel | CAH / BQH / MMH | Compte de contrepartie de l’imputation, sinon 471 (attente) |
| Facture fournisseur historique | ACH | Compte des factures historiques / 401 |

Une modification de mouvement contre-passe la pièce et en génère une nouvelle. Une suppression la contre-passe. Imputer un mouvement manuel solde le compte d’attente.

## Paramètres (Comptabilité générale › Paramètres)

- **Comptes des catégories de dépense** : obligatoires. Une dépense dont la catégorie n’a pas de compte est refusée en entier, pour qu’aucune dépense ne reste sans écriture.
- **Comptes du journal de caisse historique** : caisse 57, banque 521, mobile money 55 par défaut.
- **Compte d’attente** (471), **compte d’ouverture**, **compte des factures fournisseurs historiques**.
- Tout changement est motivé et tracé au journal d’audit. Les comptes doivent être numériques. Un sous-compte est créé automatiquement sous un compte parent existant.
- Le compte de contrepartie d’un mouvement manuel se saisit dans la boîte d’imputation du journal de caisse.

## Contrôle permanent

Pour chaque journal de trésorerie et chaque devise, le solde de l’application (mouvements depuis la date de démarrage) doit être égal au solde du compte de trésorerie, en devise d’origine. Ce contrôle est le critère de sortie du lot 1 du mémo. Il s’affiche dans l’onglet Paramètres, et tout écart est signalé.

## Vérifications

`tests/test_comptabilite_lot1.py` (9 tests) couvre :

- achat V7 facturé puis payé en deux fois, avec l’analytique chantier et poste ;
- contre-passation d’un paiement ;
- avance versée, justifiée puis restituée ;
- virement ;
- facture en CDF payée avec un écart de change 776 ;
- dépense par catégorie : refus sans compte, modification, suppression ;
- mouvement manuel en attente puis imputé ;
- fournisseur 401 et 4091, encaissement client 411 ;
- aucune écriture avant la date de démarrage.

Chaque test vérifie que la balance est équilibrée et que la trésorerie concorde avec les comptes.

## Reste à faire

- Lettrage des comptes tiers.
- Plan SYSCOHADA complet et table de passage V7 → SYSCOHADA, à valider par l’expert-comptable puis à importer.
- Reprise des soldes antérieurs à la date de démarrage, par un journal d’à-nouveaux (AN).
