# Versions

Numérotation : `vMAJEUR.MINEUR.CORRECTIF`.
- MAJEUR : une étape du plan produit (V1 paramétrable, V3 en ligne, V4 inscription autonome…).
- MINEUR : une nouvelle fonction dans l'étape.
- CORRECTIF : une correction sans nouvelle fonction.

Chaque version est une étiquette Git (`git tag`). Revenir à une version : `git checkout v3.1.0`.

## En cours (branche dev)

- Factures : nom de l'entreprise sous la 1re ligne de la désignation, avant l'agent, comme sur les factures d'ANO (« ANO SERVICE ») ; réglable dans Paramètres > Numérotation (vide = raison sociale en majuscules), à l'écran, en PDF et en Word.

- Un n° de facture émis reste lié à son agent : la facture du mois émise après sa visite médicale reprend le n° de la visite (FA 87/Visite médicale/2026 puis FA 87/12/2026), et inversement ; modifier la DA (ordre des agents, dates, montants) ne change jamais le n° ni l'agent d'une facture émise ; un agent qui a des factures émises ne peut être ni retiré ni remplacé.

- Recherche globale (case en haut du menu, touche « / ») : dossiers, factures, documents, clients, intérimaires ; plusieurs mots, accents ignorés, n° et montants avec espaces ; filtres type, client, statut, période, montant HT ; Lecture = factures seulement ; jamais hors de l'entreprise connectée.

- Mise en page : la page ne défile plus jamais de côté, quelles que soient la largeur et le zoom (le menu restait coupé sur la page dossier) ; un tableau trop large défile dans son cadre.

- Site de test : jeu de données fictives (`outils/donnees_fictives.py` : agent seul, groupe de 9, prolongation, prorata, « bis », facture corrigée, visite à l'anniversaire, trop-perçu, DA annulée). L'entreprise « essai » est remplie une fois ; l'entreprise « verif » est recréée à chaque mise à jour pour les tests en ligne (`tests/en_ligne/verifier_dev_api.py`, `tests/e2e/en_ligne_dev.js`).
- `plateforme.py mdp CODE IDENTIFIANT` : mot de passe oublié, nouveau mot de passe provisoire.
- Champs de recherche des dossiers et intérimaires : libellés pour les lecteurs d'écran.

- `deploiement/vider-production.sh` : remet la production à zéro (copie complète gardée d'abord dans /root/sauvegardes-erp, confirmation « VIDER », `--restaurer` pour revenir en arrière) ; le site de test n'est pas touché.
- Branche `dev` : tests GitHub à chaque envoi ; `main` reste la production.
- Site de test https://dev.<ip>.sslip.io à côté de la production (compte `erp-dev`, port 8766, données
  `/var/lib/erp-dev`, production illisible pour lui), mis à jour automatiquement à chaque envoi sur `dev`
  après les tests ; repère discret : badge « TEST » près du nom, onglet « [TEST] ». Installation : `deploiement/installer-dev.sh`.
- `erp-deployer` accepte aussi « deployer-dev dev-<commit> » (site de test seulement, code copié sans
  être exécuté en root).

## v3.5.0 – 25/11/2026 : retours de test de Luc et Lola, cas réels
- N° des factures calqués sur les vraies : facture du mois FA 159/11/2026 (11 = mois d'émission),
  visite médicale FA 159/Visite médicale/2026 avec le même n° quand elle part avec la facture du mois,
  un n° à elle quand elle est seule. Codes toujours réglables dans Paramètres.
- Facture groupée (ex. 9 infirmiers sur un même BC) : une seule facture « MAD de 9 … » par mois, quantité 1 mois.
- Coût d'un groupe arrondi une seule fois, comme la proforma Excel (9 × 674 220 → 11 589 842 par mois).
- Proforma : ligne des noms sous le service demandeur (DUPONT_MBINA_… pour plusieurs agents) ;
  « (9) Infirmiers_IDEP » accepté dans le n°.
- Proforma modifiable même après émission : les factures émises gardent leurs montants, les autres sont recalculées.
- Facture modifiable (émise ou non) : quantité, unité, montant HT, date, remarque. Le n° ne change pas,
  TVA et TTC recalculés, nouvelle copie gardée, avant/après dans le journal. Une facture payée ne se modifie pas.
- Unité de la facture au choix (Jours, Mois, Heures, Forfait…).
- Tableau de bord : le facturé est comparé au payé en TTC ; le reste à encaisser n'est plus jamais négatif ;
  un paiement plus grand que sa facture reste permis mais est signalé.
- Salaire de base dans la liste des dossiers.
- Bouton « Tout désélectionner » dans les factures.
- Compte Lecture : une page qui ne lui est pas ouverte renvoie au tableau de bord au lieu d'une erreur.
- Écrans : formulaires qui passent à la ligne d'eux-mêmes (la période ne déborde plus sur ordinateur),
  aperçu de la proforma sous le formulaire sur les écrans étroits.
- Champs obligatoires marqués d'un astérisque rouge ; textes d'aide dans une icône « i » affichée au survol.
- Logo et cachet : toute image (JPEG, PNG, WebP…), convertie en PNG dans le navigateur.

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
