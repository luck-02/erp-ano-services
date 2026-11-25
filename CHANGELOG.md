# Versions

Numérotation : `vMAJEUR.MINEUR.CORRECTIF`.
- MAJEUR : une étape du plan produit (V1 paramétrable, V3 en ligne, V4 inscription autonome…).
- MINEUR : une nouvelle fonction dans l'étape.
- CORRECTIF : une correction sans nouvelle fonction.

Chaque version est une étiquette Git (`git tag`). Revenir à une version : `git checkout v3.1.0`.

## v3.4.0 – 25/11/2026 : mise en ligne automatique (cycle en V)
- Une étiquette de version envoyée sur GitHub enchaîne : tests unitaires et d'intégration, tests système dans Chromium, publication du zip, mise en ligne, recette depuis Internet. Chaque étape attend que la précédente soit verte.
- Le serveur n'accepte de GitHub qu'une seule commande (« deployer vX.Y.Z ») avec une clé dédiée : pas de terminal, pas d'autre commande, pas de mot de passe.
- Sur le serveur : sauvegarde des bases avant chaque mise en ligne, recette après ; si la recette échoue, la version précédente est remise automatiquement.
- `deploiement/activer-deploiement-auto.sh` : activation en une fois (et `--desactiver`).
- Tests de la commande de déploiement (`tests/test_deploiement.sh`) : commandes refusées, zip piégé, retour arrière.

## v3.3.0 – 25/11/2026 : livraison automatisée (DevOps)
- Tests automatiques sur GitHub à chaque envoi : calculs, API, sécurité, plusieurs entreprises (Python 3.9 et 3.13), parcours complet dans Chromium, contrôle du dépôt (aucun cachet, aucune base, aucun secret).
- Étiquette de version envoyée sur GitHub = tests + zip publié dans « Releases ».
- `outils/nouvelle-version.sh` : vérifications, tests, étiquette et zip en une commande.
- `deploiement/deployer.sh` : mise en ligne depuis le Mac en une commande (sauvegarde des bases avant, contrôle du site après) ; retour arrière = même commande avec la version précédente.
- Fichier `VERSION` rempli automatiquement dans chaque zip ; version affichée par `verifier-en-ligne.sh` sur le serveur.

## v3.2.0 – 25/11/2026 : documents gardés sur le serveur, mise en ligne
- Copie figée de chaque facture émise (Word, et PDF quand LibreOffice est installé).
- Pièces reçues du client (DA, BC, PV) jointes au dossier : PDF, PNG ou JPEG, 8 Mo au plus.
- Écran « Documents » dans chaque dossier ; Direction et Gestion seulement ; retrait réservé à la Direction.
- Mise en ligne sur un serveur Hetzner : script d'installation corrigé (pare-feu, IPv4), LibreOffice installé.
- `deploiement/verifier-en-ligne.sh` : contrôle du site en ligne (HTTPS, en-têtes, accès refusés, fichiers internes).
- Documentation technique dans `docs/` : API OpenAPI (Swagger), MCD et diagrammes UML.
- Correction : la fiche dossier débordait sur téléphone.
- Noms d'agents réels retirés des tests et des exemples.

## v3.1.0 – 24/11/2026 : prêt pour l'hébergement
- Kit serveur : Caddy (HTTPS), service systemd durci, sauvegarde chaque nuit, script `installer-serveur.sh`.
- Tests dans un vrai navigateur (`tests/e2e/`) et `avant-mise-en-ligne.sh`.
- `/api/sante` pour la supervision.

## v3.0.0 – 24/11/2026 : plusieurs entreprises
- Une base par entreprise, registre `plateforme.db`, connexion avec un code entreprise.
- Cookie lié à l'entreprise, aucun renseignement donné sur les codes inconnus.
- Essai local de deux entreprises fictives (`Essai plusieurs entreprises.command`).
- Tests d'isolation entre entreprises (`tests/test_multi.py`).

## v1.0.0 – 24/11/2026 : réglages par entreprise
- Écran Paramètres : codes des n° de proforma et de facture, TVA de la visite médicale, nombre de chiffres du BC.
- Logo et cachet chargés depuis l'application.
- Plus de nom d'entreprise écrit en dur dans l'interface.

## v0.9.0 – 24/11/2026 : MVP sur un poste
- DA, proforma calculée, BC, factures mensuelles au prorata, visites médicales, facture bis, paiements.
- Export PDF (impression) et Word, tableau de bord, rôles Direction / Gestion / Lecture, journal, sauvegardes.
