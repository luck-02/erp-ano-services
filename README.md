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
2. **Utilisateurs** : créez le compte de Lola (rôle « Gestion ») avec un mot de passe provisoire ; elle le changera à sa première connexion.

---

## Le travail au quotidien

| Étape | Où | Ce qui se passe |
|---|---|---|
| 1. DA reçue | **+ Nouvelle DA** | Service, lieu, imputation, n° DA (laissez vide : n° automatique DA-2026-001, DA-2026-002…, qui repart à 001 chaque année), dates, agents et salaires de base. La proforma se calcule à droite pendant la saisie. Enregistrer donne le n° (ex. 348-11-ANO-NOM/2026). En tapant le nom d'un intérimaire déjà connu, l'appli le propose et reprend son dernier poste. |
| 2. Proforma | Dossier > **Proforma en PDF** | Imprimer > Enregistrer au format PDF. Passez le statut à « Envoyé ». |
| 3. BC reçu | Dossier > **Bon de commande** | N° et montant : l'écart avec le cumul de la proforma s'affiche tout de suite. |
| 4. Factures | Dossier > **Générer les factures** | Visite médicale (si due) + une facture par mois au prorata. Relancer ne crée jamais de doublon. |
| 5. Chaque mois | **Factures** > **Émettre le mois** | Donne les n° (FA 162/11-MAD/2026…) au mois choisi, et aux mois passés non émis si « rattrapage » est coché. Les PDF s'ouvrent : Imprimer > Enregistrer au format PDF. |
| Exporter une facture | **Factures** (ou fiche dossier) | Sur chaque ligne : **PDF** ou **Word** pour cette facture seule. Plusieurs factures : cochez-les puis « PDF de la sélection » ou « Word de la sélection » (un .zip avec un .docx par facture). Sur la page d'impression, décochez les factures à ne pas exporter. Le Word s'ouvre dans Word ou Pages et se modifie librement. Chrome demande le dossier ; Safari enregistre dans Téléchargements. |
| 6. Envoi / PV / paiement | **Factures** | Cochez les lignes : « Marquer envoyée(s) », « Enregistrer un paiement » (date + n° de confirmation). PV avec un autre montant : bouton **Bis (PV)** sur la facture. |
| Intérimaires | **Intérimaires** | Chaque intérimaire reçoit un matricule fixe (INT-0001, INT-0002…) à sa première DA et le garde à chaque nouvelle DA (reconnu par son nom, sans tenir compte des accents ni des majuscules). Usage interne : jamais imprimé sur les documents. |
| Anciens intérimaires | **Intérimaires** > **+ Ancien intérimaire** | Nom, poste, lieu, dates de l'ancien contrat, dernière visite médicale. Il reçoit un matricule, sans proforma ni facture. À sa prochaine DA, le même matricule et sa dernière visite sont repris. |
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
app/static/          interface (HTML, CSS, JavaScript sans dépendance)
tests/               tests automatiques
donnees/             créé au 1er lancement : base ano.db + sauvegardes (ne pas partager)
```
