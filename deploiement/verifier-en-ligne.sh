#!/bin/bash
# Contrôle de l'ERP en ligne : HTTPS, en-têtes de sécurité, accès protégés,
# fichiers internes invisibles. Ne crée aucune donnée, n'utilise aucun mot de passe réel.
#   Sur le serveur (contrôles complets) :  bash deploiement/verifier-en-ligne.sh 2-29-210-17.sslip.io
#   Depuis un Mac (contrôles web seuls)  :  bash verifier-en-ligne.sh 2-29-210-17.sslip.io
D="${1:?Donnez le nom du site, ex. 2-29-210-17.sslip.io}"
U="https://$D"
OK=0; KO=0
ok()  { echo "  ok    $1"; OK=$((OK+1)); }
ko()  { echo "  ÉCHEC $1"; KO=$((KO+1)); }
verif() { if eval "$2"; then ok "$1"; else ko "$1"; fi; }
code() { curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$@"; }

echo "Site : $U"
echo "1. HTTPS et disponibilité"
verif "certificat HTTPS valide" "curl -fsS --max-time 15 -o /dev/null $U/"
verif "/api/sante répond {\"ok\": true}" "curl -fsS --max-time 15 $U/api/sante | grep -q '\"ok\": true'"
C=$(code "http://$D/"); verif "http:// redirige vers https:// (code $C)" "[ '$C' = 308 ] || [ '$C' = 301 ]"
T=$(curl -s -o /dev/null -w "%{time_total}" --max-time 15 "$U/"); verif "page d'accueil en moins de 2 s (${T} s)" "awk 'BEGIN{exit !($T < 2)}'"

echo "2. En-têtes de sécurité"
H=$(curl -sSI --max-time 15 "$U/" | tr -d '\r')
for e in "strict-transport-security: max-age=" "content-security-policy: default-src 'self'" \
         "x-content-type-options: nosniff" "x-frame-options: DENY" "referrer-policy: no-referrer"; do
  verif "en-tête ${e%%:*}" "grep -qi \"^$e\" <<<\"\$H\""
done
verif "pas de version de logiciel affichée" "! grep -qiE '^server:.*[0-9]' <<<\"\$H\""

echo "3. Accès protégés (sans connexion)"
for p in /api/dossiers /api/factures /api/signature /api/parametres /api/journal /api/utilisateurs \
         /api/dossiers/1/documents /api/documents/1; do
  C=$(code "$U$p"); verif "$p refusé sans connexion (code $C)" "[ '$C' = 401 ]"
done
C=$(code -X POST -H 'Content-Type: application/json' -d '{}' "$U/api/installation")
verif "installation impossible en ligne (code $C)" "[ '$C' = 403 ] || [ '$C' = 400 ]"
R=$(curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
    -d '{"entreprise":"zz-verif-inconnue","identifiant":"personne","mot_de_passe":"Faux-mot-de-passe-123"}' "$U/api/connexion")
verif "entreprise inconnue : message neutre" "grep -q 'Identifiant ou mot de passe incorrect' <<<\"\$R\""
C=$(code -X POST -H 'Content-Type: application/json' -H 'Origin: https://site-pirate.example' -d '{}' "$U/api/connexion")
verif "requête venant d'un autre site refusée (code $C)" "[ '$C' = 403 ] || [ '$C' = 400 ]"

echo "4. Fichiers internes invisibles"
for p in /donnees/plateforme.db /plateforme.db /app/serveur.py /serveur.py /prive/signature.png \
         /signature.png /../app/serveur.py /static/../serveur.py /.git/config /etc/passwd; do
  C=$(code --path-as-is "$U$p"); verif "$p introuvable (code $C)" "[ '$C' = 404 ] || [ '$C' = 400 ]"
done

if [ "$(id -u)" -eq 0 ] && [ -d /var/lib/erp ]; then
  echo "5. Serveur (lancé en root sur la machine)"
  echo "  info  version installée : $(cat /opt/erp/erp-mvp/VERSION 2>/dev/null || echo inconnue)"
  verif "service ERP actif" "systemctl is-active --quiet erp-ano"
  verif "Caddy actif" "systemctl is-active --quiet caddy"
  verif "sauvegarde quotidienne programmée" "systemctl is-active --quiet erp-sauvegarde.timer"
  verif "mises à jour de sécurité automatiques" "systemctl is-enabled --quiet unattended-upgrades"
  verif "l'ERP n'écoute que en local (127.0.0.1:8765)" "ss -ltn | grep ':8765 ' | grep -q '127.0.0.1:8765' && ! ss -ltn | grep ':8765 ' | grep -qv '127.0.0.1'"
  verif "données accessibles au seul compte erp (700)" "[ \"\$(stat -c '%a %U' /var/lib/erp)\" = '700 erp' ]"
  verif "programme non modifiable par le compte erp" "! sudo -u erp test -w /opt/erp/erp-mvp/app/serveur.py"
  verif "pas de cachet/logo réel dans le programme" "[ ! -e /opt/erp/erp-mvp/app/prive/signature.png ]"
  verif "documents des entreprises hors du programme" "[ ! -e /opt/erp/erp-mvp/app/documents ] && [ ! -e /opt/erp/erp-mvp/documents ]"
  if command -v soffice >/dev/null; then echo "  info  LibreOffice présent : copies PDF des factures actives"; else echo "  info  LibreOffice absent : copies des factures en Word seulement"; fi
  N=$(ls /var/lib/erp/sauvegardes 2>/dev/null | wc -l); echo "  info  sauvegardes présentes : $N"
  echo "  info  entreprises : $(sudo -u erp env ANO_DONNEES=/var/lib/erp ANO_EN_LIGNE=1 python3 /opt/erp/erp-mvp/app/plateforme.py liste | awk '{print $1}' | paste -sd' ' -)"
fi

echo
echo "$OK contrôle(s) réussi(s), $KO échec(s)."
[ "$KO" -eq 0 ]
