#!/bin/bash
# Met une version sur le serveur, depuis le Mac, en une commande :
#   bash deploiement/deployer.sh v3.3.0 2.29.210.17 2-29-210-17.sslip.io
# Retour arrière : la même commande avec la version précédente (ex. v3.2.0).
# Étapes : zip construit depuis Git -> sauvegarde des bases sur le serveur ->
# installation -> contrôle du site. Les données (/var/lib/erp) ne sont jamais touchées.
# Utilise votre clé SSH habituelle ; aucun mot de passe n'est écrit ni demandé ici.
set -euo pipefail
cd "$(dirname "$0")/.."
V="${1:?Version, ex. v3.3.0}"
IP="${2:?Adresse IP du serveur}"
DOMAINE="${3:-$(echo "$IP" | tr '.' '-').sslip.io}"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Adresse IP attendue, ex. 2.29.210.17"; exit 1; }
[[ "$DOMAINE" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Nom de domaine invalide."; exit 1; }

ZIP=$(bash outils/construire-zip.sh "$V")
DISTANT="/root/erp-versions/$V"
echo "==> Envoi de $ZIP sur $IP"
ssh "root@$IP" "mkdir -p /root/erp-versions"
scp -q "$ZIP" "root@$IP:/root/erp-versions/$V.zip"

echo "==> Sauvegarde, installation et contrôle sur le serveur"
ssh "root@$IP" bash -s -- "$V" "$DOMAINE" <<'DISTANT'
set -euo pipefail
V="$1"; DOMAINE="$2"; D="/root/erp-versions/$V"
command -v unzip >/dev/null || apt-get install -y -q unzip
rm -rf "$D" && mkdir -p "$D" && unzip -q "/root/erp-versions/$V.zip" -d "$D"
if [ -f /opt/erp/erp-mvp/app/sauvegarde_quotidienne.py ]; then
  sudo -u erp env ANO_DONNEES=/var/lib/erp python3 /opt/erp/erp-mvp/app/sauvegarde_quotidienne.py >/dev/null && echo "  sauvegarde des bases faite"
fi
bash "$D/erp-mvp/deploiement/installer-serveur.sh" "$DOMAINE" | tail -3
bash "$D/erp-mvp/deploiement/verifier-en-ligne.sh" "$DOMAINE" | tail -4
ls -1d /root/erp-versions/v* 2>/dev/null | grep -v '\.zip$' | sort -V | head -n -5 | xargs -r rm -rf   # garde les 5 dernières
DISTANT
echo "==> $V en ligne sur https://$DOMAINE"
