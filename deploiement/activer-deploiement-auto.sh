#!/bin/bash
# À lancer UNE FOIS, en root sur le serveur, pour que GitHub puisse déployer seul.
# Depuis le Mac, dans le dossier erp-mvp :
#   ssh root@2.29.210.17 'bash -s' -- 2-29-210-17.sslip.io < deploiement/activer-deploiement-auto.sh
#   (puis, séparément, la commande forcée :)
#   ssh root@2.29.210.17 'cat > /usr/local/sbin/erp-deployer && chmod 755 /usr/local/sbin/erp-deployer' < deploiement/erp-deployer
#
# Ce que ça crée :
# - un compte « deploiement » sans mot de passe ni shell utilisable ;
# - une clé SSH qui ne peut faire QU'UNE chose : lancer /usr/local/sbin/erp-deployer
#   (pas de terminal, pas de transfert de ports, aucune autre commande) ;
# - le droit sudo pour ce seul programme.
# La clé privée s'affiche UNE fois, à coller dans GitHub (secret DEPLOY_SSH_KEY), puis est effacée du serveur.
# Désactiver plus tard : bash activer-deploiement-auto.sh --desactiver
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Lancez en root."; exit 1; }

if [ "${1:-}" = "--desactiver" ]; then
  rm -f /etc/sudoers.d/erp-deploiement /home/deploiement/.ssh/authorized_keys
  echo "Déploiement automatique désactivé (la clé de GitHub ne marche plus)."
  exit 0
fi

DOMAINE="${1:?Donnez le nom du site, ex. 2-29-210-17.sslip.io}"
[[ "$DOMAINE" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Nom de site invalide."; exit 1; }

id deploiement >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploiement
passwd -l deploiement >/dev/null
install -d -m 700 -o root -g root /var/lib/erp-deploiement
printf 'DOMAINE=%s\n' "$DOMAINE" > /etc/erp-deploiement.conf
chmod 644 /etc/erp-deploiement.conf

# sudo : ce seul programme, sans mot de passe
printf 'deploiement ALL=(root) NOPASSWD: /usr/local/sbin/erp-deployer\nDefaults!/usr/local/sbin/erp-deployer env_keep += "SSH_ORIGINAL_COMMAND"\n' > /etc/sudoers.d/erp-deploiement
chmod 440 /etc/sudoers.d/erp-deploiement
visudo -cf /etc/sudoers.d/erp-deploiement >/dev/null

# clé dédiée, limitée à la commande forcée
T=$(mktemp -d)
ssh-keygen -q -t ed25519 -N '' -C "github-actions-erp" -f "$T/cle"
install -d -m 700 -o deploiement -g deploiement /home/deploiement/.ssh
printf 'restrict,command="sudo /usr/local/sbin/erp-deployer" %s\n' "$(cat "$T/cle.pub")" > /home/deploiement/.ssh/authorized_keys
chown deploiement:deploiement /home/deploiement/.ssh/authorized_keys
chmod 600 /home/deploiement/.ssh/authorized_keys

IP="$(curl -4fsS https://ifconfig.me || hostname -I | awk '{print $1}')"
cat <<FIN

==> Prêt. Dans GitHub : dépôt > Settings > Secrets and variables > Actions > New repository secret.
Créez ces 4 secrets (copier-coller exact) :

DEPLOY_HOST
$IP

DEPLOY_DOMAINE
$DOMAINE

DEPLOY_KNOWN_HOSTS
$(ssh-keyscan -t ed25519 localhost 2>/dev/null | sed "s/^localhost/$IP/")

DEPLOY_SSH_KEY   (tout le bloc, lignes BEGIN et END comprises)
$(cat "$T/cle")

FIN
rm -rf "$T"
[ -x /usr/local/sbin/erp-deployer ] || echo "Reste à installer /usr/local/sbin/erp-deployer (deuxième commande du mode d'emploi)."
echo "La clé privée vient d'être effacée du serveur : elle n'existe plus que dans GitHub."
