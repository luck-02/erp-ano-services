#!/bin/bash
# Installe le SITE DE TEST (branche dev) à côté de la production, sur le même serveur.
# À lancer UNE FOIS en root, depuis le Mac, dans le dossier erp-mvp (branche dev) :
#   git archive origin/dev | ssh root@2.29.210.17 'rm -rf /root/erp-dev-src && mkdir /root/erp-dev-src && tar xf - -C /root/erp-dev-src && bash /root/erp-dev-src/deploiement/installer-dev.sh'
#
# Ce que ça crée, sans toucher au programme ni aux données de production :
#   - adresse  : https://dev.<ip>.sslip.io (ou le nom donné en argument)
#   - compte   : erp-dev (ne peut pas lire /var/lib/erp, les données de production)
#   - programme: /opt/erp-dev/erp-mvp   données : /var/lib/erp-dev   port local : 8766
#   - une entreprise fictive « essai » (mot de passe provisoire affiché une fois)
#   - la mise à jour automatique à chaque envoi sur la branche dev (si le déploiement
#     automatique de la production est déjà activé)
# Seul changement côté production : une ligne « import » dans /etc/caddy/Caddyfile, vérifiée
# avant d'être appliquée (rechargement de Caddy sans coupure).
# Retirer le site de test : bash installer-dev.sh --retirer
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Lancez en root."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [ "${1:-}" = "--retirer" ]; then
  systemctl disable --now erp-ano-dev 2>/dev/null || true
  rm -f /etc/systemd/system/erp-ano-dev.service /etc/caddy/autres/dev.caddy /usr/local/sbin/erp-installer-dev
  [ -f /etc/erp-deploiement.conf ] && sed -i '/^DOMAINE_DEV=/d' /etc/erp-deploiement.conf
  systemctl daemon-reload; systemctl reload caddy
  echo "Site de test arrêté. Ses fichiers restent dans /opt/erp-dev et /var/lib/erp-dev (à effacer à la main si besoin)."
  exit 0
fi

# 1. la production doit être en place (Caddy, Python, programme)
[ -d /opt/erp/erp-mvp ] && command -v caddy >/dev/null && systemctl is-active --quiet erp-ano \
  || { echo "Installez d'abord la production (installer-serveur.sh)."; exit 1; }
DOMAINE_DEV="${1:-}"
if [ -z "$DOMAINE_DEV" ]; then
  IP="$(curl -4fsS https://ifconfig.me || hostname -I | awk '{print $1}')"
  DOMAINE_DEV="dev.$(echo "$IP" | tr '.' '-').sslip.io"
fi
[[ "$DOMAINE_DEV" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Nom de site invalide."; exit 1; }
echo "==> Site de test : https://$DOMAINE_DEV"

# 2. compte et données à part
id erp-dev >/dev/null 2>&1 || useradd --system --home /opt/erp-dev --shell /usr/sbin/nologin erp-dev
mkdir -p /var/lib/erp-dev /opt/erp-dev
chown erp-dev:erp-dev /var/lib/erp-dev && chmod 700 /var/lib/erp-dev

# 3. programme de mise à jour du site de test (le code de dev est copié, jamais lancé en root)
install -m 755 "$SRC/deploiement/erp-installer-dev" /usr/local/sbin/erp-installer-dev
/usr/local/sbin/erp-installer-dev "$SRC" "$DOMAINE_DEV"

# 4. entreprise fictive « essai » (une seule fois)
if ! sudo -u erp-dev env ANO_DONNEES=/var/lib/erp-dev ANO_EN_LIGNE=1 python3 /opt/erp-dev/erp-mvp/app/plateforme.py liste 2>/dev/null | grep -q .; then
  MDP="Essai-$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')"
  sudo -u erp-dev env ANO_DONNEES=/var/lib/erp-dev MDP="$MDP" python3 -c '
import os, sys; sys.path.insert(0, "/opt/erp-dev/erp-mvp/app"); import plateforme as P
r = P.Registre("/var/lib/erp-dev"); r.initialiser(en_ligne=True)
r.creer("essai", "Essai (fictif)", "direction", os.environ["MDP"])'
  CREE=1
fi

# 5. adresse HTTPS : un fichier à part pour Caddy, vérifié avant rechargement
mkdir -p /etc/caddy/autres
sed "s/dev.exemple.com/$DOMAINE_DEV/" "$SRC/deploiement/Caddyfile-dev" > /etc/caddy/autres/dev.caddy
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.avant-dev
grep -q '^import /etc/caddy/autres/' /etc/caddy/Caddyfile \
  || printf '\n# Autres sites sur ce serveur (site de test dev.…)\nimport /etc/caddy/autres/*.caddy\n' >> /etc/caddy/Caddyfile
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  cp /etc/caddy/Caddyfile.avant-dev /etc/caddy/Caddyfile; rm -f /etc/caddy/autres/dev.caddy
  echo "Configuration Caddy refusée : rien n'a changé pour la production."; exit 1
fi
systemctl reload caddy

# 6. mise à jour automatique depuis GitHub (même clé limitée que la production)
if [ -f /etc/erp-deploiement.conf ]; then
  sed -i '/^DOMAINE_DEV=/d' /etc/erp-deploiement.conf
  printf 'DOMAINE_DEV=%s\n' "$DOMAINE_DEV" >> /etc/erp-deploiement.conf
  install -m 755 "$SRC/deploiement/erp-deployer" /usr/local/sbin/erp-deployer
  AUTO="oui : chaque envoi sur la branche dev met ce site à jour après les tests"
else
  AUTO="non (activez d'abord le déploiement automatique, puis relancez ce script)"
fi

sleep 2
cat <<FIN

==> Site de test prêt : https://$DOMAINE_DEV (certificat HTTPS : 1 minute la première fois)
    Mise à jour automatique : $AUTO
FIN
if [ -n "${CREE:-}" ]; then
  cat <<FIN
    Connexion : code entreprise « essai », identifiant « direction »,
    mot de passe provisoire (à changer à la première connexion) : $MDP
FIN
fi
