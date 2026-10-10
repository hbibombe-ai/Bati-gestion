# Bâti Gestion — MY DESTINY SARL (intégration du mémo V7)

Le **Circuit financier V7** intègre désormais budgets DQE, validations N0 → N1 → N2 → N3 → DG, paiements partiels, avances, écritures et préparation fiscale RDC. Lire [le guide de mise en service](INTEGRATION_MEMO.md) avant activation. Le mémo complet est téléchargeable dans l’application. Les recommandations fiscales restent à vérifier pour le régime effectif de MY DESTINY.

Logiciel de gestion de MY DESTINY SARL pour ses activités de construction : chantiers, devis et factures, dépenses et justificatifs, caisse et trésorerie, clients et fournisseurs, personnel, pointage et paie, ainsi que les dossiers d'achats, de stocks, de matériel, de comptabilité et les registres.

C'est la réécriture en Python ([Streamlit](https://streamlit.io)) du prototype BatiGestion, qui fonctionnait dans un seul fichier HTML. Les règles de gestion du prototype ont été reprises à l'identique :
- montants en centimes ;
- trois monnaies tenues séparément (USD, CDF, EUR), sans conversion automatique ;
- aucun taux fiscal ou social inventé ;
- en-tête de la société figé sur chaque document au moment de sa création ;
- contre-passation des paiements fournisseurs plutôt que leur suppression.

## Ce qui change par rapport au prototype

| Prototype (fichier HTML) | Version Python |
| --- | --- |
| Données dans le navigateur d'un seul appareil | **Base de données centrale** (PostgreSQL en ligne), partagée par toute l'équipe |
| Aucun identifiant, « utilisateur local non authentifié » | **Identifiant et mot de passe personnels**, mot de passe changé à la première connexion, blocage après 5 erreurs |
| Tout le monde voit tout, y compris les salaires | **Droits par rôle** ; seuls la direction et les RH voient les salaires et la paie |
| Pas de trace des modifications | **Journal d'audit** : chaque création, modification, suppression et connexion est enregistrée, avec l'auteur, l'heure, et les valeurs avant et après |
| Justificatifs « préparés », jamais validés | **Validation des justificatifs** par la finance ou la direction, par une autre personne que celle qui a déposé la pièce |
| Impression par le navigateur | **PDF générés** : devis, factures, bulletins, états de paie, journal de caisse, fiches |
| — | **Reprise des données du prototype** : sa sauvegarde JSON s'importe en un clic |

## Rôles

| Rôle | Accès |
| --- | --- |
| Direction générale (administrateur) | Tout ; crée les comptes ; valide les justificatifs ; consulte le journal d'audit |
| Finance et comptabilité | Devis, factures, dépenses, justificatifs (avec validation), caisse, trésorerie, tiers, comptes tiers, achats, comptabilité, registres, reprise historique |
| Ressources humaines et paie | Personnel, salaires, pointages, paie, dossiers RH |
| Conducteur de travaux | Chantiers, dépenses de chantier, dépôt des justificatifs, pointages, achats, stocks, matériel, dossiers de chantier |
| Consultation | Lecture des chantiers, des comptes et des rapports, sans rien modifier et sans voir les salaires |

## Rubriques

- **Accueil :** vue d'ensemble, recherche globale, rapports et alertes (chantiers en retard, créances et dettes échues, contrats à échéance, prévision de trésorerie à 7, 30, 60 et 90 jours).
- **Commercial :** devis, factures (conversion d'un devis en facture, règlements), prospects, appels d'offres, contrats, sous-traitance.
- **Chantiers :** budget, avancement et décaissements par monnaie ; lignes DQE, situations de travaux, avenants, HSE et qualité.
- **Achats et stocks :** demandes, engagements, commandes, réceptions, magasins, articles, transferts, consommations, inventaires.
- **Matériel et charroi :** équipements et véhicules, maintenance, carburant.
- **RH et paie :**
  - fiches du personnel, contrats, affectations datées, pointage quotidien ;
  - présence journalière par téléphone avec **KoboCollect** : présence du jour, import contrôlé des fiches ;
  - préparation des bulletins (montants saisis, ou assiette × taux) et états de paie ;
  - congés, missions, avances.
- **Finance :**
  - dépenses : chacune crée une seule sortie dans le journal ;
  - justificatifs : PDF, JPEG ou PNG, 5 Mo au plus, détection des doublons ;
  - journal de caisse : imputation, n° de pièce, taux historique ;
  - trésorerie par compte (caisse, banque, Mobile money).
- **Tiers :** carnet unique de clients, fournisseurs et sous-traitants ; comptes tiers avec balance âgée, factures fournisseurs, avances, affectations et contre-passations.
- **Comptabilité et documents :** plan comptable, écritures et échéances fiscales préparatoires, registre documentaire, garanties, tâches, centres de coûts, reprise historique depuis le modèle Excel.
- **Administration :**
  - société MY DESTINY : identité, adresses qualifiées, historique ;
  - utilisateurs, paramètres et sauvegardes, journal d'audit, mon compte.

## Essayer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

À la première ouverture, connectez-vous avec l'identifiant **admin** et le mot de passe **changez-moi**, puis choisissez un mot de passe personnel. En local, les données sont enregistrées dans `donnees/bati_gestion.db` (SQLite).

## Reprendre les données du prototype

1. Dans le prototype, ouvrez « Entreprise et sauvegarde » puis cliquez sur **Exporter une sauvegarde**. Vous obtenez le fichier `bati-sauvegarde-AAAA-MM-JJ.json`. Si vous avez préparé des lots historiques ou des pièces, exportez aussi les brouillons (`bati-brouillons-AAAA-MM-JJ.json`).
2. Dans Bâti Gestion, connecté en administrateur, ouvrez **Paramètres et sauvegarde**, puis **Restaurer ou reprendre des données**.
3. Choisissez « Sauvegarde du prototype », chargez le fichier, cochez la confirmation et cliquez sur **Importer**. Recommencez avec le fichier des brouillons si vous en avez un.

Les anciennes sauvegardes (versions 1 et 2 du prototype) sont mises à niveau automatiquement. Les mouvements historiques sans date ni compte apparaissent dans le journal de caisse, sous « mouvements à compléter ».

## Mettre en ligne (gratuit)

Hébergement proposé : **Streamlit Community Cloud** pour l'application et **Neon** (ou Supabase) pour la base PostgreSQL.

> La base PostgreSQL est indispensable en ligne : sur Streamlit Community Cloud, le disque est effacé à chaque redémarrage.

1. **Base de données.** Sur [neon.tech](https://neon.tech), dans votre projet, créez une base (par exemple `bati`) et copiez son adresse de connexion (`postgresql://…`). Les tables de Bâti Gestion ne portent pas les mêmes noms que celles de l'application de suivi des chantiers, mais une base séparée reste plus claire.
2. **Code.** Créez un nouveau dépôt GitHub (par exemple `bati-gestion`). Déposez le **contenu** de ce dossier à la racine du dépôt, y compris les dossiers `vues`, `static` et `.streamlit`, mais sans `donnees/` ni `.streamlit/secrets.toml`. Streamlit Community Cloud n'accepte qu'une seule application privée par compte : rendez ce dépôt public si la place est déjà prise. Il ne contient ni mot de passe ni donnée.
3. **Application.** Sur [share.streamlit.io](https://share.streamlit.io), cliquez sur **Create app**, choisissez le dépôt et le fichier `app.py`.
4. **Secrets, avant de déployer.** Dans **Paramètres avancés › Secrets**, collez le contenu de `.streamlit/secrets.toml.example`, puis remplacez les valeurs :
   - le mot de passe initial de l'administrateur ;
   - `CLE_SECRETE` : une longue suite de caractères aléatoires ;
   - l'adresse de la base Neon.
5. **Première connexion.** Connectez-vous avec l'identifiant administrateur et le mot de passe initial des secrets, puis changez-le.
6. **Données et comptes.**
   - Importez les données du prototype (voir plus haut).
   - Complétez la fiche « Société MY DESTINY ».
   - Créez un compte par personne dans **Utilisateurs**.

## Présence journalière par KoboCollect

Rubrique **RH & Paie › Présence KoboCollect** (direction, RH, conducteurs de travaux).

1. **Formulaire.** Onglet « Formulaire et réglages » : téléchargez le formulaire (XLSForm). Il contient la liste à jour des
   agents actifs (nom et matricule) et des lieux (bureau, chantiers en cours). Dans KoboToolbox : **Nouveau › Importer un
   XLSForm**, puis **Déployer**. Quand le personnel ou les chantiers changent, retéléchargez-le et faites
   **Remplacer le formulaire › Redéployer**.
2. **Collecte.** Chaque pointeur remplit une fiche par lieu et par jour dans KoboCollect : il choisit le lieu, puis ajoute
   une ligne par agent (présence, heure d'arrivée, heure de départ, pause, observation). Les heures travaillées sont
   calculées : départ − arrivée − pause.
3. **Import.** Onglet « Importer les fiches » : **Récupérer les fiches KoboCollect** (automatique) ou chargement de l'export
   Excel de Kobo (XLS, « Valeurs et en-têtes XML »). Chaque ligne est contrôlée avec les règles du pointage manuel
   (agent connu et actif, date entre l'engagement et aujourd'hui, un seul pointage par agent et par jour, heures nulles
   pour absence, congé, maladie et repos). Les lignes en conflit avec un pointage déjà saisi ne remplacent celui-ci
   que si vous cochez la case prévue. Une ligne déjà traitée n'est jamais importée deux fois.
4. **Suivi.** Onglet « Présence du jour » : présents, absents, heures par lieu et agents actifs non pointés.

Les pointages importés apparaissent dans « Personnel et pointage » avec l'observation « KoboCollect, pointeur … » ; chaque
import est inscrit au journal d'audit.

**Récupération automatique.** Dans KoboToolbox : Paramètres du compte › Sécurité › **Clé API**. Ajoutez-la aux secrets :

```toml
[kobo]
jeton = "votre-cle-api-kobo"
```

puis indiquez dans l'onglet « Formulaire et réglages » le serveur et l'identifiant du formulaire (la suite de caractères
après `/forms/` dans l'adresse du formulaire). Sans clé API, l'import par fichier Excel reste possible.

## Rubriques historiques et périmètre de l’intégration

Ces limites étaient déjà celles du prototype ; elles restent signalées dans l'application :
- Les dossiers d'achats, de stocks, de matériel et de comptabilité sont des fiches **préparatoires**. Ils ne modifient ni les stocks, ni la trésorerie, ni la comptabilité.
- La paie est une **préparation** : les montants sociaux et fiscaux sont saisis ou calculés avec un taux saisi, sans barème légal intégré. Il n'y a pas encore de circuit de validation RH, finance et DG.
- Pas de comptabilité SYSCOHADA générée automatiquement (grand livre, balance, clôtures).
- Le circuit N0 à N3 puis DG est disponible dans Circuit financier V7, avec délégations et dérogation budgétaire DG. Les anciennes pages ne créent pas de nouveaux paiements pour un chantier muni d’un budget V7.
- L'application demande une connexion internet ; le mode hors ligne du prototype n'existe plus. Une application gratuite de Streamlit se met en veille après quelques jours sans visite et se réveille en une trentaine de secondes.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `app.py` | Connexion, navigation selon le rôle |
| `auth.py` | Comptes, mots de passe, sessions, droits par rôle |
| `db.py` | Tables, accès à la base, transactions et journal d'audit |
| `regles.py` | Règles de gestion reprises du prototype (monnaies, trésorerie, comptes tiers, paie, dossiers) |
| `pdf.py` | Génération des documents PDF |
| `kobo.py` | Présence par KoboCollect : formulaire XLSForm, récupération des fiches, contrôles et import |
| `migration.py` | Sauvegarde, restauration, reprise des données du prototype |
| `reprise.py` | Modèle Excel de reprise historique et ses contrôles |
| `ui.py`, `nav.py` | Style, champs et tableaux communs, liens entre pages |
| `vues/` | Une rubrique par fichier |
| `.streamlit/config.toml` | Couleurs et polices |
