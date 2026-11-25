# Versions

Numérotation : `vMAJEUR.MINEUR.CORRECTIF`.
- MAJEUR : une étape du plan produit (V1 paramétrable, V3 en ligne, V4 inscription autonome…).
- MINEUR : une nouvelle fonction dans l'étape.
- CORRECTIF : une correction sans nouvelle fonction.

Chaque version est une étiquette Git (`git tag`). Revenir à une version : `git checkout v3.1.0`.

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
