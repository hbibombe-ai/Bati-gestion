# Circuit des demandes d’achat, postes et profils

Version du 16 octobre 2026. Ajout additif à BatiGestion V8 : aucune table nouvelle, aucune donnée existante transformée.

## Le circuit

| Étape | Qui (rubrique de droits) | Ce qui se passe |
|---|---|---|
| 1. Demande d’achat | Équipe chantier (`demandes_achat`) | Plusieurs lignes : poste DQE, article, unité, quantité. Prix et fournisseur **facultatifs**. Saisie à l’écran ou import Excel. Brouillon, puis soumission. |
| 2. Validation du besoin | Chef de chantier ou directeur de projet (`approbation_chantier`) | Valide ou rejette, avec commentaire. Jamais le demandeur lui-même. |
| 3. Chiffrage | Service achats (`chiffrage_achats`) | Fournisseur et prix de chaque ligne ; confirme ou corrige les prix proposés par le chantier ; quantité servie par le stock. À l’écran ou par import Excel. Ni le demandeur ni le valideur du chantier. |
| 4. Coordonnateur | Coordonnateur de projet (`approbation_coordonnateur`) | Valide au-delà du seuil de la devise, et toujours si un poste DQE dépasse son disponible. Personne n’ayant pas encore agi sur la demande. |
| 5. Circuit financier V7 | Inchangé | Une opération « Achat » par fournisseur et par poste DQE, créée au nom du demandeur et soumise automatiquement, puis N1 → N2 → N3 → DG, commande, réception, facture, paiement, comme aujourd’hui. |
| 6. Commande groupée | Achats (famille Finance ou Direction) | Une même référence de bon de commande pour plusieurs opérations approuvées d’un même fournisseur, tous chantiers confondus. |

Une demande entièrement servie par le stock passe au statut « Servie par stock » sans créer d’opération. Un rejet renvoie la demande au demandeur, qui la modifie et la soumet de nouveau (les validations repartent de zéro).

**Seuils** (onglet « Réglages », DG) : par devise, en centimes. **Par défaut 0 : le coordonnateur valide toutes les demandes** tant que la DG n’a pas fixé de seuil. Le compte de coût des opérations créées est le 602 (Achats de matières) par défaut.

**Choix assumé** : la validation du chef de chantier porte sur le besoin (quantités, sans prix). Le contrôle N1 du circuit V7 porte ensuite sur le montant chiffré ; il n’est donc pas considéré comme déjà fait. Le chef de chantier peut être la personne qui fait le N1.

## Rubrique Utilisateurs

- **Famille de rôle** (inchangée : Direction, Finance, RH, Conducteur de travaux, Consultation) : fixe ce que les services autorisent.
- **Poste** : modèle de départ des accès. 13 postes standards : chef d’équipe, conducteur de travaux, magasinier chantier, chef de chantier, directeur de projet, coordonnateur de projet, acheteur, responsable achats, magasinier central, comptable fournisseurs, DAF, directeur général, administrateur ERP.
- **Accès par personne : toujours prioritaires.** Comme avant, l’administrateur ajoute ou retire une rubrique pour une personne ; seuls les écarts avec le modèle sont enregistrés. « Revenir au modèle du poste » efface ces écarts.
- **Chantiers affectés** : vide = tous. Limite les demandes d’achat créées, validées (chantier, coordonnateur) et vues. Ne s’applique pas encore aux autres écrans.
- **Profils personnalisés** (onglet « Postes et profils ») : code, libellé, famille, description et accès, éventuellement à partir d’un poste existant. Un profil désactivé renvoie ses usagers au modèle de leur famille. Modifier un profil ferme les sessions de ses usagers.
- **Séparation des tâches** : un profil ne peut pas cumuler chiffrage + validation coordonnateur, chiffrage + approbation DG, ni gestion des utilisateurs + chiffrage. Pour une personne, le cumul reste possible (avertissement affiché) ; le circuit empêche quand même qu’elle agisse deux fois sur la même demande.
- Seule la direction générale accorde la gestion des utilisateurs, l’approbation DG ou l’audit, et crée ou modifie un compte administrateur.

## Import Excel (centre d’import, mode « Opérations en cours »)

| Fonction | Feuilles | Effet |
|---|---|---|
| Demandes d’achat | `Demandes_Achat` + `Lignes_Demande_Achat` | Une demande en brouillon par référence, à soumettre (bouton « Soumettre mes brouillons »). |
| Chiffrage des demandes | `Chiffrage_Achats` | Fournisseur, prix et quantité servie par le stock pour des demandes validées par le chantier. Prix vide = prix proposé confirmé. |

Mêmes contrôles qu’à l’écran, fichier refusé en entier à la première erreur, aperçu, idempotence et traçabilité du centre d’import. Les modèles sont dans `modeles/` et téléchargeables dans l’application.

## Fichiers

| Fichier | Contenu |
|---|---|
| `achats_circuit.py` | Services du circuit (nouveau) |
| `vues/demandes_achat.py` | Écran « Achats & Stocks › Demandes d’achat » (nouveau) |
| `imports/adapters/achats.py` | Import Excel des demandes et du chiffrage (nouveau) |
| `auth.py` | 4 rubriques de droits, postes, profils personnalisés, chantiers affectés |
| `vues/utilisateurs.py` | Onglets « Comptes » et « Postes et profils » |
| `gestion_v7.py` | Type d’enregistrement `purchase_request` ; commande extraite en `_order_tx` (comportement inchangé) |
| `imports/schema.py`, `imports/validation.py`, `imports/adapters/__init__.py` | Nouvelles feuilles et périmètres |
| `migration.py` | Les seuils du circuit sont inclus dans la sauvegarde |
| `app.py` | Nouvelle page ; poste affiché sous le nom de l’usager connecté |
| `tests/test_circuit_achats.py`, `tests/test_ecrans_achats.py` | Recette |

Stockage : demandes dans `v7_records` (type `purchase_request`) ; postes, chantiers affectés, profils et seuils dans `settings` (`poste_utilisateur:<id>`, `projets_utilisateur:<id>`, `profils_personnalises`, `achats_politique`). Aucune migration de base n’est nécessaire.

## Vérifications

- 31 tests nouveaux (`tests/test_circuit_achats.py`) : cycle complet jusqu’à la facture, seuils, dépassement budgétaire, stock, séparation des responsabilités, périmètres, rejet et nouvelle soumission, commande groupée, sauvegarde, import Excel (droits, périmètre, devise, chiffrage incomplet refusé), postes, profils et dérogations par personne.
- Tests existants toujours verts : intégration V7 (27), import (20, dont 2 réservés à PostgreSQL), droits par utilisateur (13), amendements, factures, pièces jointes.
- **À faire chez vous** : `tests/test_ecrans_imports.py`, `tests/test_modif_facture_ecran.py` et le nouveau `tests/test_ecrans_achats.py` utilisent Streamlit AppTest, qui n’a pas pu être installé dans l’environnement de développement. Les écrans ont été parcourus avec un Streamlit simulé (9 profils, toutes les étapes, formulaires de saisie, de chiffrage et de commande), mais pas dans un navigateur. Lancer `python -m unittest discover tests` et ouvrir les deux écrans avant la mise en service.
