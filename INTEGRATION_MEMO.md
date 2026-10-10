# Intégration du mémo BatiGestion V7

Version du 10 octobre 2026. Mémo de référence daté du 9 octobre 2026, disponible dans « Circuit financier V7 › Contrôles et mémo ».

## Utiliser le nouveau circuit

1. Conserver une sauvegarde de la base avant le changement de version. Les nouvelles tables s’ajoutent à la première ouverture ; les anciennes opérations sont conservées.
2. Créer les utilisateurs : demandeur, contrôleur N1, finance N2, autorité N3, DG et trésorier. Cette version demande un validateur distinct à chaque niveau et un trésorier distinct du créateur et des validateurs. Plusieurs comptes de finance et, si nécessaire, des délégations nominatives sont donc nécessaires. La DG ne peut pas approuver un budget qu’elle a créé.
3. Dans « Budgets DQE », créer le code chantier et ses postes, le montant contractuel HT, le budget et le coût estimé à terminaison. Faire approuver le budget par un autre utilisateur DG.
4. Dans « Trésorerie », ouvrir un compte par banque/caisse et devise, avec une subdivision comptable propre. Rapprocher les anciens mouvements avant de saisir les soldes initiaux : la saisie initiale ne doit pas reproduire de la trésorerie déjà enregistrée.
5. Dans « Opérations », créer une demande N0 affectée au poste et au bénéficiaire, la soumettre puis effectuer les validations N1, N2, N3 et DG. Au seuil de 100 %, une dérogation DG explicite est obligatoire.
6. Pour un achat : enregistrer commande, réception acceptée et facture. Pour une dépense directe : enregistrer la facture après validation. Le montant facturé doit rester dans l’engagement autorisé ; les paiements restent plafonnés au montant facturé. Cette première intégration saisit un montant de coût sans liquidation automatique de TVA par facture : faire valider le traitement comptable du montant et utiliser la préparation fiscale pour la liquidation.
7. Pour une avance de régie : payer l’avance autorisée, déposer les pièces, les faire accepter par une autre personne, puis restituer le reliquat. L’avance n’est pas comptabilisée en charge lors de son versement ; les seules charges sont les justificatifs acceptés.
8. Vérifier les écritures, la balance exportable, les alertes et le rapprochement bancaire. Les corrections de paiement se font par contre-passation conservée dans l’historique.
9. Faire valider le régime fiscal effectif, les références légales et la date d’effet avant de calculer l’IS ou la TVA préparatoires. Enregistrer les échéances effectivement applicables, leurs prorogations et les preuves de dépôt/règlement.

## Correspondance avec les sections du mémo

| Sections | Intégration et vérification |
|---|---|
| 1 et principe de saisie unique | Une opération relie DQE, contrôles, commande, réceptions, factures, paiements, pièces et écritures. |
| 2 Structure budgétaire | Code chantier, postes configurables, budget initial/révisé, contrat et prévisions. Révisions proposées puis approuvées par une DG indépendante. |
| 3 Calculs | Engagement restant + coûts réalisés ; le paiement ne crée pas un deuxième coût. Disponible, taux, alertes 70/85/95/100 configurables, marge et prévision à terminaison. |
| 4 Cycle financier | Demande et validation, commande, réception, factures, paiements partiels, pièces, écritures et rapprochement. |
| 5 Dépenses | Références uniques, bénéficiaire, chantier, poste, devise, statut financier et statut documentaire séparés. |
| 6 Avances | Paiement en 581, justification acceptée en charge, restitution ; solde à régulariser distinct. |
| 7 Trésorerie | Comptes par devise, transferts, prévisions 7/30/60/90 jours intégrant engagements V7 et échéances fiscales enregistrées, rapprochement, historique des taux et consolidation explicite. Les garanties restent dans les registres existants. |
| 8 et 9 Responsabilités | Contrôles côté service, utilisateurs distincts, délégations datées/plafonnées par devise et chantier, nouvelle validation après modification, exception DG. |
| 10 Journal | Audit transactionnel existant complété par les événements et versions des nouvelles opérations. Aucune suppression de mouvement V7 ; contre-passation. |
| 11 Contrôles | Budget, autorisation, pièce réutilisée, référence de facture, paiement excessif, solde insuffisant et concurrence contrôlés. |
| 12 Indicateurs | Budget, engagement ouvert, charge, paiement, avance, reste, coût final et marge ; alertes dans accueil et rapports. |
| 13 Priorités | Nouveau circuit utilisable ; ancienne saisie des paiements bloquée pour un chantier équipé d’un budget V7. |
| 14 Tests | Tests d’intégration sur base SQLite isolée et ouverture des écrans par Streamlit AppTest. Aucun résultat d’audit de la société n’est déduit des tests. |
| 15 Directives | Contrôles, workflow, imputation obligatoire, liaison des pièces, dérogation DG, audit, tests et séparation des fonctions appliqués au nouveau circuit. |
| Annexe comptable | Nomenclature proposée consultable ; écritures du circuit, balance et export CSV. Le traitement des stocks, immobilisations, TVA et contrats pluri-exercices doit être validé avant de considérer la balance comme une comptabilité légale complète. |
| Annexe fiscale RDC | Fiche fiscale versionnée dans l’audit, IS et TVA préparatoires, calendrier par année des revenus et échéances avec preuve. Les taux proposés ne deviennent applicables qu’après validation explicite. |

## Limites à traiter lors de la mise en service

- Les anciens dossiers DQE et les anciennes écritures restent préparatoires : aucun reclassement automatique des données historiques, stocks ou salaires.
- Le nouveau tableau budgétaire porte sur les opérations du circuit V7. Les dépenses historiques doivent être rapprochées/reprises avant utilisation d’un chantier déjà commencé. Une alerte prévient de leur présence.
- Les comptes V7 utilisent des soldes initiaux distincts des anciens mouvements. Les journaux d’origine affichent aussi les nouveaux flux ; éviter de doubler les soldes d’ouverture et choisir un périmètre de reprise documenté.
- Les factures d’achat du circuit génèrent des écritures simples de coût et dette ; pas de ventilation fiscale automatique ni de stock permanent. Les ventes, la paie et les contrats pluri-exercices ne produisent pas encore automatiquement une comptabilité complète.
- L’émission de la facture normalisée exige une connexion à un dispositif ou système agréé DGI. Aucune homologation ou émission fiscale n’est revendiquée. Les taux réduits, retenues étrangères, cotisations et impôts provinciaux restent à valider selon la société et les textes applicables.
- Les tests utilisent SQLite isolée. Une recette sur une copie de la base PostgreSQL et un rapprochement des données réelles restent nécessaires avant exploitation partagée.

## Lancement et retour à la version précédente

Installer les dépendances de `requirements.txt`, puis lancer `streamlit run app.py`. La rubrique « Circuit financier V7 » apparaît sous Finance. La base est créée ou enrichie selon la configuration existante ; aucun secret n’est livré dans l’archive.

Le paquet complet inclut le code, les ressources, le mémo et les tests. Une archive du code source avant intégration est conservée à côté du paquet de livraison. Pour revenir à l’ancien code, restaurer cette archive après arrêt de l’application ; conserver les tables V7 et la sauvegarde afin de ne pas perdre les nouvelles opérations. Ne pas lancer un remplacement de base sans sauvegarde.
