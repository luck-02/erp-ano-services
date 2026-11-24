# Mettre l'ERP en ligne (V3, plusieurs entreprises)

Rien n'est en ligne tant que ces étapes ne sont pas faites. Aucune donnée réelle
(salaires) ne doit être importée avant l'accord de la direction d'ANO.

## Ce qu'il faut
- Un serveur Linux (Ubuntu 24.04) : Oracle Cloud « Always Free » pour les tests,
  ou un petit serveur payant (~5 €/mois) pour les vraies données.
- Un nom de domaine (ex. erp.votre-domaine.com) pointant vers l'adresse du serveur.

## Étapes (≈ 30 minutes)
1. Pare-feu : n'ouvrir que les ports 22 (SSH), 80 et 443.
   `sudo ufw allow 22,80,443/tcp && sudo ufw enable`
2. Compte dédié et dossiers :
   `sudo useradd --system --home /opt/erp erp && sudo mkdir -p /opt/erp /var/lib/erp && sudo chown erp:erp /var/lib/erp && sudo chmod 700 /var/lib/erp`
3. Copier le dossier `erp-mvp` dans `/opt/erp/` (sans le dossier `donnees`, et sans
   `app/prive/signature.png` : chaque entreprise charge son cachet depuis Paramètres).
4. Installer Caddy (HTTPS automatique) : https://caddyserver.com/docs/install
   puis copier `deploiement/Caddyfile` dans `/etc/caddy/Caddyfile` en mettant le vrai domaine.
5. Copier `deploiement/erp-ano.service` dans `/etc/systemd/system/`, mettre le vrai domaine
   dans `ANO_HOTES`, puis `sudo systemctl enable --now erp-ano caddy`.
6. Créer chaque entreprise cliente (le mot de passe est demandé, jamais affiché) :
   `sudo -u erp env ANO_DONNEES=/var/lib/erp ANO_EN_LIGNE=1 python3 /opt/erp/erp-mvp/app/plateforme.py creer ano "ANO Services" luc`
   Le compte devra changer son mot de passe à la première connexion.
7. Se connecter sur https://erp.votre-domaine.com avec le code entreprise (ex. `ano`).

## Sauvegardes
Une copie de chaque base est faite à chaque démarrage dans
`/var/lib/erp/entreprises/<code>/sauvegardes/`. Copier régulièrement `/var/lib/erp`
hors du serveur (chiffré), par exemple une fois par jour.

## Commandes utiles
- Lister les entreprises : `... plateforme.py liste`
- Suspendre une entreprise (impayé, fin de contrat) : `... plateforme.py desactiver CODE`
- Journal du service : `sudo journalctl -u erp-ano -f`

## Rappels sécurité
- Chaque entreprise a sa propre base : une erreur de requête ne peut pas montrer
  les données d'une autre (tests : `tests/test_multi.py`).
- Le serveur Python n'écoute que 127.0.0.1 : seul Caddy (HTTPS) est joignable depuis Internet.
- Hébergement hors du Gabon = transfert de données personnelles à déclarer à l'APDPVP
  (loi 001/2011 modifiée par la loi 025/2023).
