# Soldes et arrêtés de caisse — V8

Version du 24 octobre 2026. Ajouts au journal de caisse : solde visible, sorties plafonnées au solde, arrêté de caisse avec procès-verbal de comptage. Ce dernier correspond au point « Caisses arrêtées » de la clôture mensuelle (mémo § 9.1).

## Qu'est-ce qu'une caisse

Une caisse est un compte de trésorerie dans **une** devise :

- chaque compte de trésorerie du circuit V7 (caisse, banque ou Mobile money) ;
- le journal de caisse historique, hors comptes V7, par compte (caisse, banque, Mobile money) et par devise.

Les soldes restent dans leur devise, sans conversion : les francs congolais d'une caisse ne sont pas des dollars. Le total converti reste disponible ailleurs, à titre indicatif.

## 1. Solde de caisse en tête du journal

Un bandeau affiche le solde de chaque caisse à la date de fin choisie dans les filtres, avec son dernier mouvement et la date de son dernier arrêté validé. Un solde négatif s'affiche en rouge, avec un message d'alerte. Le filtre « Compte » limite le bandeau aux caisses, aux banques ou au Mobile money.

## 2. Carte « Trésorerie disponible » sur l'accueil

Elle est visible par les personnes qui ont accès à la trésorerie. Elle donne le solde du jour de toutes les caisses, banques et Mobile money. Elle signale aussi :

- une caisse négative ;
- un écart entre la trésorerie de l'application et la comptabilité, pour les personnes qui voient la comptabilité ;
- les arrêtés de caisse en attente de validation.

## 3. Arrêté de caisse (Journal de caisse › Arrêté de caisse)

| Étape | Qui | Ce qui se passe |
|---|---|---|
| Comptage | Caissier (droit Trésorerie en écriture) | Il saisit les billets par coupure, plus les pièces et autres. L'application calcule le montant compté, le solde théorique du journal à la date choisie et l'écart. Une explication est obligatoire s'il y a un écart. |
| Validation | Comptabilité ou DG, **autre personne que le caissier** | La validation refait le calcul du solde théorique. Si des mouvements ont été saisis ou modifiés depuis le comptage, elle est refusée et il faut recompter. |
| Régularisation | Automatique | Un écart validé crée un mouvement daté de l'arrêté. Un manquant est porté au compte 658, un excédent au compte 758. Le mouvement est comptabilisé dans le journal de la caisse. Après validation, le solde de l'application est égal aux billets comptés. |
| Rejet | Comptabilité ou DG | Le motif est obligatoire. Rien ne change ; le caissier recompte. |

Chaque arrêté s'imprime en procès-verbal PDF, avec le billetage, l'écart, les intervenants et des emplacements de signature. Une fois un arrêté validé, on ne peut plus en saisir un à une date antérieure ou égale pour cette caisse. Un seul arrêté peut être en attente par caisse.

Si la DG accorde une dérogation nominative et datée (règle « Valider un arrêté de caisse qu'on a compté »), le caissier peut valider son propre arrêté. C'est le même mécanisme que pour les autres séparations des fonctions.

**Clôture mensuelle** (Comptabilité générale › Périodes) : pour le mois choisi, la liste indique chaque caisse protégée (voir point 4) mouvementée dans le mois ou dont le solde n'est pas nul. Elle précise si la caisse a un arrêté validé daté du mois, postérieur ou égal à son dernier mouvement du mois, et quel écart a été régularisé.

## 4. Une sortie ne peut pas dépasser le solde

Ce contrôle suit le même principe que pour le stock, qui ne peut jamais être négatif. Il s'applique à toutes les saisies :

- l'écran du journal de caisse ;
- les dépenses et les règlements ;
- les imports Excel ;
- les comptes V7 de la même nature.

Le contrôle se fait **à la journée**. Une écriture est refusée si elle rend négatif le solde de fin de journée d'une caisse, à une date quelconque. Elle l'est aussi si ce solde était déjà négatif et qu'elle l'aggrave. Le refus vaut donc aussi pour une sortie antidatée, et pour la suppression d'une entrée qui laisserait un trou.

Une saisie groupée (un import ou un virement interne) est jugée sur son résultat d'ensemble. Une caisse déjà négative dans l'historique repris peut recevoir des entrées, mais aucune nouvelle sortie tant qu'elle n'est pas renflouée.

## Paramètres (Journal de caisse › Paramètres de caisse, DG)

| Paramètre | Valeur par défaut |
|---|---|
| Solde négatif interdit | Caisse et Mobile money : oui. Banque : non (découvert autorisé). |
| Coupures du billetage | USD 100 à 1 ; CDF 20 000 à 10 ; EUR 500 à 5 |
| Compte des manquants de caisse | 658 Charges diverses (un compte du caissier si la DG le décide) |
| Compte des excédents de caisse | 758 Produits divers |

Chaque modification est motivée et tracée au journal d'audit. Pour reprendre un ancien journal de caisse qui était négatif, la DG peut lever temporairement l'interdiction, puis la rétablir.

## Technique

- `caisses.py` : soldes, contrôle, arrêtés, liste de clôture. `db.Transaction` relève les caisses touchées par chaque écriture de mouvement, et `db.transaction` les contrôle avant d'enregistrer.
- Table `caisse_arretes`, créée par la migration Alembic `0005_arretes_caisse`. Elle est incluse dans les sauvegardes et restaurations.
- Les comptes 658 et 758 sont ajoutés aux comptes par défaut.
- `tests/test_caisses.py` (11 tests) couvre :
  - les soldes par caisse et par devise, et à une date ;
  - le refus d'une sortie supérieure au solde, y compris antidatée ;
  - la transaction groupée ;
  - la suppression d'une entrée ;
  - le découvert bancaire et le paramètre DG ;
  - l'historique déjà négatif ;
  - l'arrêté avec manquant (658) et avec excédent (758) ;
  - la séparation des fonctions et le rejet motivé ;
  - un mouvement saisi après le comptage ;
  - l'arrêté d'une caisse V7 et la liste de clôture.
