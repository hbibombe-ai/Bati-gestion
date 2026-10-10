# Import généralisé depuis Excel — notice utilisateur

Version du 10 octobre 2026, modèle `2026.10-1`. Elle met en œuvre les « Instructions générales pour le développement Python » du 10 octobre 2026.

## 1. Où importer

- **Centre de reprise et d’import** (Comptabilité & Documents) : toutes les fonctions et la reprise globale. Il présente les lots, leur rapprochement et les reliquats repris.
- **Pages métier** : un encart « Importer depuis Excel » est disponible dans Clients et fournisseurs, Chantiers, Personnel et pointage, et dans Circuit financier V7 (onglet « Reprises et imports »). Il applique les mêmes contrôles et les mêmes droits.

Les droits sont ceux de la saisie manuelle. Ils sont revérifiés par le serveur à chaque confirmation, à partir du compte en base.

## 2. Trois modes

| Mode | Effet |
|---|---|
| Archives historiques | Les lignes sont conservées pour consultation dans le lot. Aucun effet sur la caisse, les coûts, les budgets actifs ou le grand livre. |
| Reprise à une date de bascule | Prépare des soldes, des cumuls, des reliquats et des engagements restants. **Rien n’est actif** avant la validation Finance puis l’activation par la DG. |
| Opérations en cours | Crée des fiches de référence, des pointages et des demandes N0 en brouillon. Celles-ci suivent ensuite le circuit N1 → N2 → N3 → DG. |

L’écran affiche le mode, la date de bascule et les effets attendus avant toute confirmation.

## 3. Pas à pas

1. Choisir la fonction et le mode, puis télécharger le modèle. Ses feuilles Instructions et Parametres sont pré-remplies.
2. Remplir les feuilles utiles. Ne modifier ni les noms de feuilles ni les en-têtes. Ne mettre ni formule, ni macro, ni cellule fusionnée.
3. Charger le classeur, ainsi que les pièces PDF/JPEG/PNG si la feuille Documents est utilisée, puis cliquer sur **Contrôler le fichier**.
4. Lire l’aperçu, qui présente :
   - les erreurs bloquantes ;
   - les alertes, dont celles qui demandent une **décision** ;
   - les créations, les correspondances et les doublons ;
   - les effets financiers et les totaux **par devise**.

   Le rapport de contrôle se télécharge.
5. Cocher les décisions demandées, puis cliquer sur **Confirmer l’import**. Tout le lot réussit dans une seule transaction, ou rien n’est enregistré.
6. En reprise uniquement :
   - **Validation Finance** : une personne de Finance, autre que l’importateur, vérifie le rapprochement avec les relevés et comptages ;
   - **Activation DG** : une DG distincte de l’importateur et du validateur Finance active le lot. Les budgets sont approuvés, les soldes et la balance d’ouverture sont comptabilisés, les reliquats deviennent effectifs.

## 4. Règles communes

- Seul le format `.xlsx` est accepté, dans la limite de 8 Mo et de 5 000 lignes utiles par lot. Ces limites se règlent dans le paramètre `imports_limites`.
- Sont refusés : les macros, les liaisons externes, les formules, les feuilles inconnues, les en-têtes répétés ou modifiés, les cellules fusionnées et les champs obligatoires manquants.
- Formats :
  - dates au format `AAAA-MM-JJ` (le format `JJ/MM/AAAA`, ambigu, est refusé) ;
  - périodes de paie au format `AAAA-MM` ;
  - références en texte, zéros initiaux conservés.
- Nombres : un seul séparateur décimal, virgule **ou** point, sans séparateur de milliers. Les écritures `1 234,56`, `1.234,56` et `1,234.56` sont refusées. Les montants sont calculés en `Decimal`, avec 2 décimales au plus, puis stockés en centimes.
- Devises : USD, CDF et EUR sont tenus séparément. Il n’y a aucune conversion implicite et jamais de total multi-devises.
- Doublons : ils sont signalés dans le fichier, dans la base et entre fonctions liées. La table de correspondance garantit qu’**une même ligne source ne produit qu’une fois son effet**.
- Recharger le même fichier dans le même contexte restitue le lot existant, sans nouvel effet.
- Une colonne « statut approuvé » n’est jamais acceptée : l’import ne crée ni signature ni validation.

## 5. Reprise sans double comptage

| Cas | Ce que fait l’import |
|---|---|
| Facture de 1 000 USD payée 600 USD avant la date de bascule D | La facture et le paiement de 600 sont conservés en **archives**. Une **dette reprise de 400** est préparée. La caisse n’est pas redébitée. Après activation, le reliquat se règle depuis « Reliquats repris » par un trésorier indépendant, à une date ≥ D. |
| Avance de 500 dont 350 déclarés justifiés | Un **reliquat de 150** est créé, à justifier (pièce contrôlée par une autre personne) ou à restituer. La justification déclarée reste à prouver. Aucun versement fictif n’est créé. |
| Budget de 10 000, coûts de 3 000, engagements de 2 000 | Le budget est créé « À approuver » et les cumuls sont repris comme événements distincts. Après activation, le **disponible est de 5 000**, sans faux paiement. Un engagement repris se solde lorsqu’il est remplacé par une demande du circuit. |
| Soldes de trésorerie | Ils sont pris au début du jour D, avec la référence du relevé ou du comptage. Ils sont refusés si le compte est déjà mouvementé. |
| Balance d’ouverture | Elle doit être équilibrée (débit = crédit) et datée du jour D. Elle est refusée si la trésorerie de la même devise est aussi reprise par des soldes d’ouverture : il faut choisir une seule méthode. |

Les paiements, factures ou avances datés **à partir de D** ne sont pas importés en reprise : ils se saisissent dans le circuit V7.

## 6. Corrections

- **Avant l’activation**, un lot peut être rejeté avec un motif, ou remplacé par un fichier corrigé portant la même `reference_lot` (une case de confirmation est demandée). Les reliquats et les budgets du lot sont alors rejetés, mais conservés pour l’historique.
- **Après l’activation**, aucune suppression automatique n’est possible. On passe par une correction ou une contre-passation contrôlée.
- Les fiches de référence créées (tiers, chantiers, personnel) sont conservées même si le lot est rejeté, et peuvent être archivées depuis leur page.

## 7. Cas particuliers

- **Paie, devis et factures clients, achats et réceptions, stocks et matériels, situations, fiscalité** : mode Archives seulement. Ce sont des fonctions préparatoires (voir `IMPORTS_MATRICE.md`).
- **Factures** : aucune facture normalisée DGI n’est générée et rien n’est transmis à la DGI.
- **Présences** : un seul pointage par personne et par jour. Une ligne identique à un pointage existant (saisi ou KoboCollect) est ignorée ; une ligne différente est refusée comme conflit.
- **Salaires** : les colonnes de salaire et la paie sont réservées aux RH et à la DG. Un fichier qui en contient est refusé pour les autres rôles, et son contenu n’est pas affiché.
- **Données exclues** : les mots de passe, secrets, clés DGI et droits d’accès ne sont jamais repris depuis un classeur.

## 8. Mise en service

Avant de mettre en service :

1. Sauvegarder la base.
2. Tester la restauration sur une base séparée.
3. Arrêter les saisies pendant la bascule.
4. Faire une reprise pilote sur un chantier.
5. Faire signer le rapprochement des soldes par Finance et la DG.
6. Rouvrir les saisies.

Le fichier source, le rapport de contrôle et le rapprochement avant / après restent attachés au lot.
