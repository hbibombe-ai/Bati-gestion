# Taux du jour et totaux consolidés

Version du 16 octobre 2026.

## Principe

- Les écritures restent tenues dans leur devise (USD, CDF, EUR) : **aucun montant n’est converti en base**.
- La finance saisit chaque jour les taux (rubrique **Finance › Taux de change**) : `1 USD = … CDF` et `1 EUR = … USD`, taux BCC ou taux pratiqué, avec sa source.
- Partout où des totaux par devise sont affichés, un **total consolidé indicatif** est ajouté, avec le taux utilisé et sa date : vue d’ensemble, dépenses, justificatifs, comptes tiers, chantiers, fiches tiers.

## Règles

| Règle | Détail |
|---|---|
| Taux utilisé | Le dernier taux connu à la date ; direct, inverse (1/taux) ou via une devise pivot (EUR → CDF via USD). |
| Devise sans taux | Exclue du total et signalée (« hors EUR, aucun taux saisi ») ; **jamais convertie à 1**. |
| Taux ancien | Signalé au-delà de 3 jours (réglable). La vue d’ensemble rappelle à la finance de saisir le taux du jour. |
| Correction | Une nouvelle saisie le même jour corrige le taux ; l’ancien taux, l’auteur et l’heure restent dans la fiche et au journal d’audit. |
| Date | Pas de taux pour une date future. |
| Droits | Saisie : rubriques Trésorerie ou Comptabilité en modification (famille Finance ou Direction). |
| Réglages | Devise des totaux consolidés (par défaut la devise de la société) et ancienneté signalée. |
| Sauvegarde | Les taux font partie du registre V7 (`v7_records`, type `rate`) : sauvegardés et restaurés. |

La consolidation de trésorerie **à taux explicites** du circuit V7 reste l’état de référence daté et justifié. Les totaux consolidés de l’affichage sont indicatifs.

## Fichiers

`devises.py` (nouveau), `vues/taux.py` (nouveau), `ui.py` (totaux consolidés dans `montants_html` et, sur option, `montants_texte`), `app.py`, `vues/accueil.py`, `vues/chantiers.py`, `vues/tiers.py`, `vues/comptes_tiers.py`, `tests/test_devises.py` (9 tests).
