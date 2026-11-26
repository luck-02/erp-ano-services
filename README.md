# ERP ANO Services : version MVP (web)

Application web qui reprend l'outil Excel V4 : saisie des DA, proforma automatique, BC, factures mensuelles (rattrapage, facture bis, envoi, paiement), PDF et tableau de bord. Elle tourne **sur votre Mac uniquement** : rien n'est envoyé sur Internet, les données restent dans le dossier `donnees/`.

---

## Installation sur Mac (une seule fois, environ 10 minutes)

### Étape 1 : vérifier que Python est installé
1. Ouvrez **Terminal** (Cmd + Espace, tapez « Terminal », Entrée).
2. Tapez `python3 --version` puis Entrée.
   - S'il affiche `Python 3.9` ou plus : c'est bon, passez à l'étape 2.
   - Si une fenêtre propose d'installer les « outils de ligne de commande » : cliquez **Installer**, attendez la fin, puis recommencez.
   - Sinon : téléchargez Python sur https://www.python.org/downloads/ (bouton jaune « Download Python »), installez-le comme une application normale.

Aucun autre logiciel n'est nécessaire (pas de Node, pas de base de données à installer).

### Étape 2 : copier le dossier
Copiez le dossier `erp-mvp` où vous voulez, par exemple dans `Documents`. **Évitez** un dossier synchronisé (iCloud Drive, Google Drive) : la base contient des salaires.

### Étape 3 : débloquer le lanceur (une seule fois)
macOS bloque les fichiers téléchargés qui ne viennent pas de l'App Store (« Gatekeeper »). Le plus simple :
1. Ouvrez **Terminal** (Launchpad > Autres > Terminal).
2. Tapez `cd ` (avec l'espace), **glissez le dossier `erp-mvp`** dans la fenêtre, puis Entrée.
3. Copiez-collez cette ligne puis Entrée : `xattr -cr . ; chmod +x "Lancer ANO.command"`
4. Fermez Terminal. Le double-clic sur **Lancer ANO.command** marche désormais.

Autre méthode, sans Terminal : double-cliquez sur **Lancer ANO.command**, cliquez **OK** sur le message de blocage, puis ouvrez **Réglages Système > Confidentialité et sécurité**, descendez jusqu'à « Lancer ANO.command a été bloqué » et cliquez **Ouvrir quand même** (mot de passe du Mac demandé), puis **Ouvrir**. Sur les anciens macOS, **clic droit > Ouvrir > Ouvrir** suffit.

---

## Lancer l'application (chaque jour)

1. Double-cliquez sur **Lancer ANO.command**.
   - S'il est bloqué, voir l'étape 3 ci-dessus (une seule fois).
2. Une fenêtre Terminal s'ouvre (laissez-la ouverte) et le navigateur affiche l'application à l'adresse **http://localhost:8765**.
3. Pour arrêter : fermez la fenêtre Terminal.

Si le double-clic ne marche pas : dans Terminal, tapez `cd ` puis glissez le dossier `erp-mvp`, Entrée, puis `python3 app/serveur.py`.

### Première ouverture
L'application demande de créer le **compte de la direction** (administrateur) : nom, identifiant, mot de passe de 12 caractères minimum. Ensuite :
1. **Paramètres** : vérifiez l'entreprise, les taux, et les derniers n° réels sont déjà réglés : dernier devis **348** (le prochain sera 349) et dernière facture **FA 161** (la prochaine sera FA 162). Vous pouvez les corriger dans Paramètres.
   Tout ce qui est propre à l'entreprise se règle aussi dans **Paramètres**, sans toucher au code : identité, taux de charges, TVA (et TVA ou non sur la visite médicale), codes des n° (`ANO` dans 349-11-ANO-NOM/2026, `FA`, `MAD`, `Visite Médicale`), longueur des n° de BC, logo et cachet (PNG). Les réglages d'ANO sont ceux par défaut.
2. **Utilisateurs** : créez le compte de Lola (rôle « Gestion ») avec un mot de passe provisoire ; elle le changera à sa première connexion.

---

## Le travail au quotidien

| Étape | Où | Ce qui se passe |
|---|---|---|
| 1. DA reçue | **+ Nouvelle DA** | Service, lieu, imputation, n° DA (laissez vide : n° automatique DA-2026-001, DA-2026-002…, qui repart à 001 chaque année), dates, agents et salaires de base. La proforma se calcule à droite pendant la saisie. Enregistrer donne le n° (ex. 348-11-ANO-NOM/2026). En tapant le nom d'un intérimaire déjà connu, l'appli le propose et reprend son dernier poste. |
| 2. Proforma | Dossier > **Proforma en PDF** | Imprimer > Enregistrer au format PDF. Passez le statut à « Envoyé ». |
| 3. BC reçu | Dossier > **Bon de commande** | N° et montant : l'écart avec le cumul de la proforma s'affiche tout de suite. |
| 4. Factures | Dossier > **Générer les factures** | Visite médicale (si due) + une facture par mois au prorata. Relancer ne crée jamais de doublon. |
| 5. Chaque mois | **Factures** > **Émettre le mois** | Donne les n° (FA 162/11/2026, et FA 162/Visite médicale/2026 pour la visite émise avec) au mois choisi, et aux mois passés non émis si « rattrapage » est coché. Les PDF s'ouvrent : Imprimer > Enregistrer au format PDF. |
| Exporter une facture | **Factures** (ou fiche dossier) | Sur chaque ligne : **PDF** ou **Word** pour cette facture seule. Plusieurs factures : cochez-les puis « PDF de la sélection » ou « Word de la sélection » (un .zip avec un .docx par facture). Sur la page d'impression, décochez les factures à ne pas exporter. Le Word s'ouvre dans Word ou Pages et se modifie librement. Chrome demande le dossier ; Safari enregistre dans Téléchargements. |
| Corriger | Dossier > **Modifier** ; facture > **Modifier** | La proforma reste modifiable après émission : les factures émises gardent leurs montants, les autres sont recalculées. Une facture (émise ou non, pas payée) se corrige : quantité, unité, montant, date. Le n° ne change pas, une nouvelle copie est gardée. |
| Groupe (ex. 9 infirmiers) | **+ Nouvelle DA** > case « Une seule facture par mois pour tout le groupe » | Une facture « MAD de 9 … » par mois au lieu d'une par agent. |
| 6. Envoi / PV / paiement | **Factures** | Cochez les lignes : « Marquer envoyée(s) », « Enregistrer un paiement » (date + n° de confirmation). PV avec un autre montant : bouton **Bis (PV)** sur la facture. |
| Intérimaires | **Intérimaires** | Chaque intérimaire reçoit un matricule fixe (INT-0001, INT-0002…) à sa première DA et le garde à chaque nouvelle DA (reconnu par son nom, sans tenir compte des accents ni des majuscules). Usage interne : jamais imprimé sur les documents. |
| Anciens intérimaires | **Intérimaires** > **+ Ancien intérimaire** | Nom, poste, lieu, dates de l'ancien contrat, dernière visite médicale. Il reçoit un matricule, sans proforma ni facture. À sa prochaine DA, le même matricule et sa dernière visite sont repris. |
| Documents | Dossier > **Documents** | Une copie de chaque facture est gardée automatiquement au moment où elle est émise (Word, et PDF si LibreOffice est installé : c'est le cas sur le serveur en ligne). Joignez aussi les pièces reçues du client : DA, BC, PV (PDF, PNG ou JPEG, 8 Mo au plus). Direction et Gestion téléchargent ; seule la Direction peut retirer une pièce de la liste (le fichier reste gardé). Les copies de factures ne se retirent pas. |
| Retrouver | Case **Rechercher…** en haut du menu (ou touche **/**) | Un ou plusieurs mots : n° de facture ou de proforma, n° de BC ou de DA, nom ou matricule d'agent, client, service, lieu, mois (« septembre 2026 »), montant (« 11 173 500 »). Sans tenir compte des accents ni des majuscules. Résultats : dossiers, factures, documents (téléchargeables), clients, intérimaires. Filtres : type, client, statut, période, montant HT. Le rôle Lecture ne trouve que des factures. |
| Heures supplémentaires | Dossier > **Heures supplémentaires** > + Nouveau relevé d'heures | 1. Joindre le relevé scanné du client. 2. Saisir la fiche d'attachement en grille calendrier (heures tapées sous chaque jour, de date à date, plusieurs mois possibles) ou par plages horaires (début, fin) : fiche en PDF. 3. Classement semaine par semaine (lundi → dimanche) : 8 premières heures à 28 %, le reste à 56 %, dimanches et jours fériés à 75 % ; modifiable à la main. 4. Proforma H (série à part : 124-10-ANO-MAD/2026). 5. Facture FA H (FA H 110/11/2026) au montant du devis par défaut, modifiable ; envoyée, payée. Taux horaire = coût mensuel ÷ 173,33. Derniers n° et taux dans Paramètres. Fiche à remettre au client en PDF ou Word, archivable, avec signatures de l'agent datées (Avant, Après, Payées, Récupérées, scan facultatif). Jours fériés « à confirmer » : un clic pour les confirmer avant le devis. |
| Export | **Factures** > **Exporter (Excel)** | Tableau des factures affichées (mêmes filtres) pour Excel ou Numbers : n°, mois, agent, HT, TVA, TTC, statut, paiement. Jamais de salaire. |
| 7. Suivi | **Tableau de bord** | En haut, la liste **À faire** (factures à émettre, à envoyer, en retard, proformas sans BC, brouillons), chaque ligne mène au bon écran. Puis par mois : personnes en contrat, à facturer, facturé, payé, impayés, retards, fins de contrat et visites médicales à refaire. |

### Rôles
- **Direction (admin)** : tout, y compris paramètres, utilisateurs, journal et sauvegardes.
- **Gestion** : DA, proformas, BC, factures, paiements, clients.
- **Lecture** : tableau de bord et factures seulement (ne voit pas les salaires).

---

## Règles de calcul (reprises de l'Excel V4)
- Coût mensuel par agent = salaire de base × 1,91 (9 charges + marge 20 %), arrondi au franc.
- Prorata = jours calendaires couverts ÷ jours du mois. Le **cumul de la proforma est arrondi une seule fois** ; chaque facture mensuelle est arrondie au franc.
- Visite médicale 45 000 XAF HT par agent : au début si la dernière visite a plus d'un an (ou n'existe pas), puis à chaque anniversaire. Pour un renouvellement, la dernière visite de l'agent est retrouvée automatiquement.
- TVA 18 % sur les factures de mise à disposition. **Pas de TVA sur la facture de visite médicale** (ligne « TVA (18 %) : 0 », TTC = HT). La modalité de règlement n'est plus imprimée sur les factures (elle sert seulement au calcul de l'échéance). La proforma n'affiche que le cumul HT. Échéance = date de facture + 30 jours, puis fin de mois (30 JFDM).
- Changer un taux dans Paramètres ne modifie pas les proformas déjà créées (chaque DA garde son barème).
- Dès qu'une facture d'un dossier est émise, ses agents, salaires et dates sont verrouillés (un avenant = nouvelle DA).

Cas de référence vérifié : salaire 576 300, du 02/11/2026 au 01/05/2027 → cumul HT **6 648 214 XAF** (= BC 493930) et **8 factures** (1 visite + 7 mois).

---

## Sécurité
- L'application n'écoute que sur ce Mac (127.0.0.1) : un autre ordinateur du réseau ne peut pas s'y connecter.
- Mots de passe : 12 caractères minimum, stockés hachés (PBKDF2-SHA256, 600 000 itérations). Compte bloqué 15 minutes après 5 erreurs.
- Session : cookie HttpOnly / SameSite=Strict, déconnexion après 30 minutes d'inactivité (10 h maximum).
- Protection CSRF (jeton), contrôle de l'hôte et de l'origine, en-têtes de sécurité (CSP stricte, anti-iframe), validation de toutes les saisies côté serveur, requêtes SQL paramétrées.
- **Cachet + signature** : fichier `app/prive/signature.png`, ajouté automatiquement sous « Signature » / « Le responsable » sur la proforma et les factures. Il n'est jamais servi comme fichier public : seuls les comptes Direction et Gestion connectés peuvent l'afficher (le rôle Lecture imprime sans signature). Pour le changer, remplacez ce fichier (PNG à fond transparent). Ne partagez pas le dossier `app/prive/`.
- **Documents** (copies de factures, DA, BC, PV) : rangés dans `documents/` à côté de la base de l'entreprise, sous un nom aléatoire, droits réservés au compte de l'application. Jamais servis en accès direct : seulement par l'application, à un compte Direction ou Gestion connecté de la même entreprise. Le contenu est vérifié (PDF, PNG, JPEG réels), pas seulement l'extension. Ils ne sont jamais modifiés ni effacés ; une copie hors du serveur doit inclure ce dossier.
- **Journal d'activité** : connexions, créations, émissions, paiements, changements de paramètres.
- **Sauvegardes** : une copie de la base à chaque lancement dans `donnees/sauvegardes/` (30 dernières gardées) ; bouton « Faire une sauvegarde maintenant » dans Paramètres. Pensez à copier ce dossier sur une clé USB ou un disque externe chiffré de temps en temps.
- Recommandé : activer **FileVault** sur le Mac (Réglages > Confidentialité et sécurité), car la base n'est pas chiffrée en elle-même.

## Tests automatiques
Dans Terminal, depuis le dossier : `./lancer_tests.sh` (ou `python3 tests/test_metier.py` puis `python3 tests/test_api.py`). Les tests utilisent uniquement des noms fictifs et une base temporaire.

## Structure
```
Lancer ANO.command   lanceur Mac (double-clic)
app/serveur.py       serveur web + sécurité (Python, bibliothèque standard seule)
app/api.py           API : DA, proformas, BC, factures, tableau de bord, utilisateurs
app/metier.py        règles de calcul (coût, prorata, visites, numéros)
app/db.py            base SQLite, valeurs initiales, sauvegardes, matricules
app/docx_facture.py  export des factures en Word (.docx)
app/documents.py     documents gardés : copies des factures émises, pièces du client
app/static/          interface (HTML, CSS, JavaScript sans dépendance)
tests/               tests automatiques
donnees/             créé au 1er lancement : base ano.db + sauvegardes (ne pas partager)
```

## Version en ligne, plusieurs entreprises (V3)

Sur ce Mac, rien ne change : l'application reste réservée à ANO, avec ses données actuelles.

Sur un serveur, chaque entreprise cliente a sa propre base de données et ses propres fichiers (logo, cachet, sauvegardes). On se connecte avec un **code entreprise**, un identifiant et un mot de passe. Les entreprises sont créées avec `app/plateforme.py` (voir `deploiement/INSTALLER-SUR-UN-SERVEUR.md`). Une nouvelle entreprise démarre vierge : sans client, avec les compteurs à 0 et une identité à compléter dans Paramètres.

Tests d'isolation entre entreprises : `python3 tests/test_multi.py` (inclus dans `lancer_tests.sh`).

### Essayer plusieurs entreprises sur ce Mac (données fictives)

Double-cliquez sur **« Essai plusieurs entreprises.command »**. Deux entreprises fictives s'ouvrent sur http://localhost:8766 : code `alpha` (mot de passe provisoire `Essai-Alpha-2026`) et code `beta` (`Essai-Beta-2026`). L'identifiant est `direction` pour les deux. Leurs données sont rangées à part, dans `donnees-essai/`. La vraie installation d'ANO (port 8765, dossier `donnees/`) n'est jamais touchée. Pour tout effacer et recommencer, supprimez le dossier `donnees-essai/`.

## Vérifications avant chaque mise en ligne

`bash avant-mise-en-ligne.sh` lance tous les tests : calculs, API, sécurité, plusieurs entreprises, puis 43 vérifications dans un vrai navigateur (`tests/e2e/`, Playwright installé automatiquement la première fois, Node.js requis). Ces vérifications couvrent le parcours complet ANO, les PDF, Word et CSV, l'isolation entre entreprises, l'accessibilité de base et l'affichage sur téléphone. Si un test échoue, on ne met pas en ligne.

Supervision : `/api/sante` répond `{"ok": true}` sans connexion (pour un service de surveillance). Sauvegarde de toutes les entreprises : `python3 app/sauvegarde_quotidienne.py` (lancée chaque nuit sur le serveur).

Après la mise en ligne, sur le serveur : `bash deploiement/verifier-en-ligne.sh <nom-du-site>` contrôle le HTTPS, les en-têtes de sécurité, les accès refusés sans connexion, l'invisibilité des fichiers internes, les services, les droits et les sauvegardes (29 contrôles web + 8 contrôles serveur).

## Versions et dépôt Git

Le dossier est un dépôt Git : `git log --oneline` liste les versions, `git tag` leurs étiquettes, et `CHANGELOG.md` dit ce que chacune apporte. Le cachet (`app/prive/`) et les données (`donnees/`) ne sont jamais versionnés.

### Deux branches : `dev` (travail) et `main` (production)

- **`dev`** : toutes les nouvelles modifications arrivent ici. À chaque envoi, GitHub relance tous les tests. Rien ne part sur le serveur.
- **`main`** : seulement ce qui a été vérifié sur `dev`. Une étiquette de version posée sur `main` met en ligne.

Au quotidien (Mac) :
1. `git checkout dev && git pull` : récupérer la dernière version de travail.
2. Modifier, puis `git commit -am "…"` et `git push` : les tests tournent sur GitHub (onglet « Actions »).
3. Essayer : sur le site de test (ci-dessous), ou en local avec « Lancer ANO.command ».

**Site de test** : https://dev.2-29-210-17.sslip.io (badge « TEST » à côté du nom et onglet « [TEST] », données fictives,
compte et données séparés de la production). Après chaque envoi sur `dev`, une fois les tests verts,
GitHub le met à jour tout seul (onglet « Actions », étape « Mise à jour du site de test »).
Installation, une seule fois, depuis le Mac (dossier erp-mvp) :
`git fetch && git archive origin/dev | ssh root@2.29.210.17 'rm -rf /root/erp-dev-src && mkdir /root/erp-dev-src && tar xf - -C /root/erp-dev-src && bash /root/erp-dev-src/deploiement/installer-dev.sh'`
Le script affiche une fois le mot de passe provisoire de l'entreprise fictive « essai ». Retirer : même commande avec `installer-dev.sh --retirer`.

Passer en production, quand `dev` est validée :
1. `git checkout main && git pull && git merge dev` puis `git push`.
2. Suivre « Livrer une version » ci-dessous (`nouvelle-version.sh`, puis `git push origin main --follow-tags`).
3. `git checkout dev` pour reprendre le travail.

Livrer une version :
1. Décrire la version en haut de `CHANGELOG.md` (`## v3.4.0 – date : titre`), puis `git commit -am "…"`.
2. `bash outils/nouvelle-version.sh 3.4.0` : contrôle du dépôt, tous les tests, étiquette, zip dans `dist/`.
3. `git push origin main --follow-tags` : GitHub relance les tests et publie le zip dans « Releases ».
4. `bash deploiement/deployer.sh v3.4.0 <ip> <domaine>` : sauvegarde, installation et contrôle sur le serveur.
   En cas de problème, relancer avec la version précédente (ex. `v3.3.0`) : les données ne bougent pas.

Les tests tournent aussi sur GitHub à chaque envoi (`.github/workflows/ci.yml`).

### Mise en ligne automatique (cycle en V)

Une fois activée, l'étape 4 se fait toute seule : l'étiquette envoyée à l'étape 3 déclenche sur GitHub (`.github/workflows/version.yml`) :

| Branche descendante | Vérifiée par (branche montante) |
|---|---|
| Besoin : section du `CHANGELOG.md`, cahier des charges | 4. Recette en ligne : `verifier-en-ligne.sh` sur le serveur puis depuis Internet |
| Conception : API (`docs/openapi.yaml`), MCD | 2. Tests système : parcours complet dans Chromium |
| Codage | 1. Tests unitaires et d'intégration (calculs, API, sécurité, entreprises, déploiement) |

Puis 3. publication du zip dans « Releases » et mise en ligne. Si la recette échoue sur le serveur, la version précédente est remise automatiquement.

**Activer (une seule fois)**, depuis le Mac, dans le dossier `erp-mvp` :
```
ssh root@2.29.210.17 'cat > /usr/local/sbin/erp-deployer && chmod 755 /usr/local/sbin/erp-deployer' < deploiement/erp-deployer
ssh root@2.29.210.17 'bash -s' -- 2-29-210-17.sslip.io < deploiement/activer-deploiement-auto.sh
```
La deuxième commande affiche 4 secrets à créer dans GitHub (dépôt > Settings > Secrets and variables > Actions) : `DEPLOY_HOST`, `DEPLOY_DOMAINE`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_SSH_KEY`. La clé ne permet qu'une seule chose sur le serveur : lancer `erp-deployer` avec un zip de version. Tant que les secrets n'existent pas, GitHub saute la mise en ligne. Désactiver : `ssh root@2.29.210.17 'bash -s' -- --desactiver < deploiement/activer-deploiement-auto.sh`.

## Documentation technique

Dans `docs/` : description de l'API au format OpenAPI (`openapi.yaml`, lisible dans Swagger), MCD et diagrammes UML en Mermaid (`docs/diagrammes/`). Voir `docs/LISEZ-MOI.md`.
