# Matrice de couverture de l’import généralisé

Livraison du 10 octobre 2026. La matrice distingue ce qui est réalisé, ce qui est préparatoire (archives seulement) et ce qui reste à développer. Elle n’annonce pas une couverture totale : la recette sur données réelles reste à faire.

| Fonction | Feuilles | Archives | Reprise (bascule D) | Opérations en cours | Statut |
|---|---|---|---|---|---|
| Tiers | Tiers | Oui | Création ou rapprochement par code | Idem | **Réalisé** |
| Chantiers | Chantiers | Oui | Création ou rapprochement ; client et avancement contrôlés | Idem | **Réalisé** |
| DQE et budgets | Budgets, Lignes_Budget | Oui | Budget V7 « À approuver », approuvé à l’activation DG | Budget à approuver (circuit V7 habituel) | **Réalisé** |
| Cumuls budgétaires | Cumuls_Budget | Oui | Coûts exécutés et engagements ouverts repris une seule fois | — | **Réalisé** |
| Besoins de dépense | Besoins | Oui | — | Une demande N0 en brouillon par ligne | **Réalisé** |
| Factures fournisseurs | Factures_Fournisseurs, Paiements | Oui | Initial et paiements en archives ; dette restante reprise et réglable | — | **Réalisé** (reliquats) |
| Avances | Avances, Paiements | Oui | Reliquat à justifier ou restituer, preuve exigée | — | **Réalisé** (reliquats) |
| Trésorerie | Comptes_Tresorerie | Oui | Compte V7 et solde d’ouverture rapproché, activé par la DG | — | **Réalisé** |
| Mouvements de trésorerie anciens | Mouvements_Tresorerie | Oui | — | — | Préparatoire (archives) |
| Comptabilité | Ecritures, Lignes_Ecriture | Oui | Balance d’ouverture équilibrée, anti double comptage avec la trésorerie | — | **Réalisé** |
| Personnel et affectations | Personnel, Affectations | Oui | Fiches, affectations datées ; salaires RH/DG | Idem | **Réalisé** |
| Présences | Presences | Oui | Un pointage par personne et par jour ; doublons Kobo résolus | Idem | **Réalisé** |
| Pièces et documents | Documents + fichiers | Oui | Manifeste + fichiers vérifiés (type, taille, SHA-256, doublon) | Idem | **Réalisé** |
| Achats et réceptions | Commandes, Receptions | Oui | — | — | Préparatoire — à développer : rattachement aux opérations V7 existantes (commande / réception) |
| Factures fournisseurs en cours | — | — | — | — | À développer : facture d’une opération V7 déjà approuvée (service `invoice`) |
| Paiements courants | — | — | — | — | Hors import par principe : exécutés dans le circuit après autorisation |
| Devis et factures clients | Devis, Lignes_Devis, Factures_Clients, Lignes_Facture, Reglements_Clients | Oui | — | — | Préparatoire — à développer : créances clients restantes, sans recréer une recette déjà reprise |
| Paie | Paie | Oui (RH/DG) | — | — | Préparatoire : aucune paie historique ne déclenche de paiement |
| Stocks et matériels | Stocks, Materiels | Oui | — | — | Préparatoire : la gestion active des stocks et immobilisations exige ses propres services |
| Situations de travaux | Situations | Oui | — | — | Préparatoire — à développer : rapprochement des cumuls avec les factures clients |
| Fiscalité et taux | Fiscalite, Taux | Oui | — | — | Préparatoire : paramètres fiscaux à confirmer séparément (fiche fiscale V7) |
| Reprise globale | Toutes | Oui | Toutes les feuilles réalisées, dans l’ordre contrôlé | Idem | **Réalisé** pour les fonctions ci-dessus |

## Composants livrés

| Spécification §10 | Fichier |
|---|---|
| Registre des modèles, champs, relations, versions | `imports/schema.py` |
| Lecture bornée, formules, macros, normalisation, modèles | `imports/excel.py` |
| Erreurs par feuille / ligne / champ, droits, résolution des références | `imports/validation.py` |
| Adaptateurs métier | `imports/adapters/` (référentiels, budgets, reliquats, trésorerie, documents) |
| Aperçu, confirmation, transaction, lots, idempotence | `imports/service.py` |
| Totaux avant / après, soldes, reliquats, écarts | `imports/reconciliation.py` |
| Centre de reprise et composants des pages métier | `vues/imports.py` (+ encarts dans tiers, chantiers, personnel, circuit V7) |
| Tables additives : lots, aperçus, correspondances | `imports/tables.py` (création automatique) |
| Événements de reprise V7 | `gestion_v7.py` : type `carryover`, `metrics`, alertes, règlement / justification / restitution des reliquats |
| Sauvegarde et restauration | `migration.py` : lots, correspondances et `imports_limites` inclus |
| Modèles Excel par fonction | `modeles/` (également téléchargeables dans l’application) |

## Recette automatisée (10 octobre 2026)

| Test de la spécification | Test automatisé | SQLite | PostgreSQL 16 |
|---|---|---|---|
| Fichier valide pour chaque module | `test_fichier_valide_relations_audit_et_idempotence`, tests Reprise et Workflow | OK | OK |
| Erreur sur la dernière ligne | `test_erreur_derniere_ligne_aucune_ecriture_partielle` (contrôle et panne en exécution) | OK | OK |
| Fichier identique et double clic | `test_double_confirmation_meme_apercu_et_apercus_concurrents` | OK | OK |
| Deux confirmations concurrentes | `Concurrence` (4 fils simultanés ; deux lots pour la même facture) | — (SQLite sérialise) | OK |
| Archives seules | `test_archives_seules_sans_effet` | OK | OK |
| Facture 1 000 payée 600 | `test_facture_1000_payee_600_reliquat_400_sans_redebit` | OK | OK |
| Avance 500 justifiée à 350 | `test_avance_500_justifiee_350_reliquat_150` | OK | OK |
| Budget 10 000 / 3 000 / 2 000 | `test_budget_10000_couts_3000_engagements_2000_disponible_5000` | OK | OK |
| Utilisateur sans droits et données RH | `test_droits_et_donnees_rh_confidentielles` | OK | OK |
| Validation et paiement courants | `test_besoins_en_brouillon_sans_validation_importee`, `test_activation_dg_distincte_et_finance_requise` | OK | OK |
| Sauvegarde puis restauration | `test_sauvegarde_restauration_lots_correspondances_pieces_parametres` | OK | OK |
| Rapports après reprise | `test_tresorerie_et_balance_sans_double_comptabilisation` (totaux par devise et écarts par compte) | OK | OK |

Les 27 tests d’intégration V7 existants restent verts. Les écrans (centre, tiers, chantiers, personnel, circuit V7) s’ouvrent sans exception pour les cinq rôles (Streamlit AppTest). Un import complet a aussi été vérifié dans un navigateur.

Ces tests ne sont ni un audit des données de MY DESTINY ni une recette sur la base de production. La reprise pilote sur un chantier et la signature du rapprochement par Finance et la DG restent nécessaires.
