#!/bin/bash
# Installe l'ERP sur un serveur Ubuntu 24.04 (Hetzner, Oracle Cloud ou autre).
# À lancer SUR LE SERVEUR, depuis le dossier erp-mvp décompressé :
#     sudo bash deploiement/installer-serveur.sh                 (adresse gratuite <ip>.sslip.io)
#     sudo bash deploiement/installer-serveur.sh erp.mondomaine.com
# Relancer le script = mise à jour du programme ; les données (/var/lib/erp) ne sont jamais touchées.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Lancez avec sudo."; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/erp/erp-mvp
DONNEES=/var/lib/erp

# 1. nom de domaine : celui donné, sinon une adresse gratuite basée sur l'IP publique
DOMAINE="${1:-}"
if [ -z "$DOMAINE" ]; then
  IP="$(curl -4fsS https://ifconfig.me || true)"
  [ -n "$IP" ] || { echo "IP publique introuvable : donnez le nom de domaine en argument."; exit 1; }
  DOMAINE="$(echo "$IP" | tr '.' '-').sslip.io"
fi
echo "==> Adresse de l'ERP : https://$DOMAINE"

# 2. paquets : Python, Caddy (HTTPS automatique), mises à jour de sécurité automatiques
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 curl gnupg debian-keyring debian-archive-keyring apt-transport-https unattended-upgrades
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
dpkg-reconfigure -f noninteractive unattended-upgrades
# LibreOffice (sans interface) : copie PDF de chaque facture émise. Facultatif :
# sans lui, l'ERP garde seulement la copie Word.
apt-get install -y -q --no-install-recommends libreoffice-writer-nogui fonts-crosextra-carlito fonts-liberation \
  || echo "==> LibreOffice non installé : les factures émises seront gardées en Word seulement."

# 3. pare-feu de la machine : SSH + HTTP/HTTPS seulement (les images Oracle bloquent 80/443 par défaut)
# (Oracle : règle REJECT dans INPUT -> on insère juste avant ; Hetzner et autres : rien à faire ici)
if command -v iptables >/dev/null; then
  for port in 80 443; do
    REJ="$(iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')"
    if [ -n "$REJ" ] && ! iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
      iptables -I INPUT "$REJ" -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
    fi
  done
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save || true; fi
fi

# 4. compte dédié, programme et données (droits minimaux)
id erp >/dev/null 2>&1 || useradd --system --home /opt/erp --shell /usr/sbin/nologin erp
mkdir -p "$APP" "$DONNEES"
( cd "$SRC" && tar cf - --exclude '.git' --exclude 'donnees' --exclude 'donnees-essai' --exclude 'node_modules' \
    --exclude 'app/prive/signature.png' --exclude 'app/prive/logo.png' . ) | ( cd "$APP" && tar xf - )
chown -R root:root /opt/erp && chmod -R u=rwX,go=rX /opt/erp   # lisible par erp, jamais modifiable
chown erp:erp "$DONNEES" && chmod 700 "$DONNEES"

# 5. services : ERP, sauvegarde quotidienne, Caddy
sed "s/erp.exemple.com/$DOMAINE/" "$SRC/deploiement/erp-ano.service" > /etc/systemd/system/erp-ano.service
cp "$SRC/deploiement/erp-sauvegarde.service" "$SRC/deploiement/erp-sauvegarde.timer" /etc/systemd/system/
sed "s/erp.exemple.com/$DOMAINE/" "$SRC/deploiement/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now erp-ano erp-sauvegarde.timer
systemctl restart erp-ano caddy

# 6. vérification
sleep 3
if curl -fsS http://127.0.0.1:8765/api/sante >/dev/null; then
  echo "==> ERP démarré."
else
  echo "==> L'ERP ne répond pas : sudo journalctl -u erp-ano -n 50"; exit 1
fi
cat <<FIN

Terminé. Prochaine étape : créer une entreprise (le mot de passe est demandé, jamais affiché) :
  sudo -u erp env ANO_DONNEES=$DONNEES ANO_EN_LIGNE=1 python3 $APP/app/plateforme.py creer alpha "Alpha Interim (fictif)" direction
Puis ouvrir https://$DOMAINE (le certificat HTTPS peut prendre 1 minute la première fois).
Supervision : https://$DOMAINE/api/sante répond {"ok": true} quand tout va bien.
FIN
