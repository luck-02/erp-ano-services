#!/bin/bash
# Remet la PRODUCTION à zéro : plus aucune entreprise, aucun dossier, aucune facture, aucun document.
# Le programme, Caddy, la sauvegarde quotidienne et le site de test (dev) ne sont pas touchés.
# Une copie complète des données est gardée AVANT d'effacer : /root/sauvegardes-erp/avant-vidage-<date>.tar.gz
#
# À lancer en root sur le serveur (une confirmation est demandée) :
#   bash vider-production.sh
# Pour revenir en arrière (remet les données d'avant le vidage) :
#   bash vider-production.sh --restaurer /root/sauvegardes-erp/avant-vidage-<date>.tar.gz
set -euo pipefail
DONNEES="${ERP_DONNEES:-/var/lib/erp}"
APP="${ERP_APP:-/opt/erp/erp-mvp}"
COPIES="${ERP_COPIES:-/root/sauvegardes-erp}"
[ "$(id -u)" -eq 0 ] || [ -n "${ERP_VIDAGE_TEST:-}" ] || { echo "Lancez en root."; exit 1; }
[ -d "$DONNEES" ] || { echo "Dossier de données $DONNEES introuvable."; exit 1; }
case "$DONNEES" in *erp-dev*) echo "Ce script ne sert qu'à la production."; exit 1;; esac

en_erp() { if [ -n "${ERP_VIDAGE_TEST:-}" ]; then env "$@"; else sudo -u erp env "$@"; fi; }
demarrer() {
  systemctl start erp-ano
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS http://127.0.0.1:8765/api/sante >/dev/null 2>&1 && { echo "==> ERP redémarré."; return 0; }
    sleep 1
  done
  echo "==> L'ERP ne répond pas : journalctl -u erp-ano -n 50"; return 1
}

if [ "${1:-}" = "--restaurer" ]; then
  ARCHIVE="${2:?chemin de la copie .tar.gz}"
  [ -f "$ARCHIVE" ] || { echo "Copie introuvable : $ARCHIVE"; exit 1; }
  systemctl stop erp-ano
  find "$DONNEES" -mindepth 1 -delete
  tar xzf "$ARCHIVE" -C "$DONNEES"
  chown -R erp:erp "$DONNEES" 2>/dev/null || true
  demarrer
  echo "Données d'avant le vidage remises en place."
  exit 0
fi

echo "Entreprises actuellement en production :"
en_erp ANO_DONNEES="$DONNEES" ANO_EN_LIGNE=1 python3 "$APP/app/plateforme.py" liste || true
echo
echo "TOUT sera effacé en production (entreprises, comptes, dossiers, factures, documents, copies quotidiennes)."
echo "Une copie complète est gardée d'abord dans $COPIES. Le site de test n'est pas touché."
read -r -p "Tapez VIDER pour confirmer : " REPONSE
[ "$REPONSE" = "VIDER" ] || { echo "Annulé, rien n'a changé."; exit 1; }

# 1. copie complète, lisible par root seulement
umask 077
mkdir -p "$COPIES"
ARCHIVE="$COPIES/avant-vidage-$(date +%Y%m%d-%H%M%S).tar.gz"
systemctl stop erp-ano
tar czf "$ARCHIVE" -C "$DONNEES" .
tar tzf "$ARCHIVE" >/dev/null || { echo "Copie illisible : rien n'est effacé."; demarrer; exit 1; }
echo "==> Copie gardée : $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# 2. effacement, puis registre vide
find "$DONNEES" -mindepth 1 -delete
en_erp ANO_DONNEES="$DONNEES" ANO_EN_LIGNE=1 python3 -c '
import os, sys; sys.path.insert(0, os.path.join(sys.argv[1], "app")); import plateforme as P
P.Registre(os.environ["ANO_DONNEES"]).initialiser(en_ligne=True)' "$APP"
chown -R erp:erp "$DONNEES" 2>/dev/null || true
chmod 700 "$DONNEES"
demarrer
N=$(en_erp ANO_DONNEES="$DONNEES" ANO_EN_LIGNE=1 python3 "$APP/app/plateforme.py" liste | grep -c . || true)
echo "==> Production vierge : $N entreprise(s)."
cat <<FIN

Créer la première entreprise (le mot de passe provisoire est demandé, jamais affiché ;
il faudra le changer à la première connexion) :
  sudo -u erp env ANO_DONNEES=$DONNEES ANO_EN_LIGNE=1 python3 $APP/app/plateforme.py creer ano "ANO Services" direction
Revenir en arrière si besoin :
  bash $0 --restaurer $ARCHIVE
FIN
