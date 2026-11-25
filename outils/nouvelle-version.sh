#!/bin/bash
# Publie une nouvelle version, sur le Mac ou dans Claude :
#   bash outils/nouvelle-version.sh 3.3.0
# 1. vérifie : branche main, rien en attente, section « ## v3.3.0 » dans CHANGELOG.md
# 2. lance tous les tests (et les tests navigateur si Node.js est installé)
# 3. pose l'étiquette v3.3.0 et construit dist/ERP_ANO_Services-v3.3.0.zip
# Envoyer ensuite sur GitHub : git push origin main --follow-tags
set -euo pipefail
cd "$(dirname "$0")/.."
N="${1:?Donnez le numéro, ex. 3.3.0}"
[[ "$N" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Numéro attendu : MAJEUR.MINEUR.CORRECTIF, ex. 3.3.0"; exit 1; }
V="v$N"
[ "$(git branch --show-current)" = main ] || { echo "Passez sur la branche main."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Des changements ne sont pas enregistrés (git status)."; exit 1; }
git rev-parse -q --verify "refs/tags/$V" >/dev/null && { echo "$V existe déjà."; exit 1; }
grep -q "^## $V " CHANGELOG.md || { echo "Ajoutez d'abord une section « ## $V – date : titre » dans CHANGELOG.md."; exit 1; }
DERNIERE=$(git describe --tags --abbrev=0 2>/dev/null || echo v0.0.0)
python3 - "$DERNIERE" "$V" <<'FIN' || { echo "$V doit être plus grand que $DERNIERE."; exit 1; }
import sys
a, b = (tuple(int(x) for x in s.lstrip("v").split(".")) for s in sys.argv[1:])
sys.exit(0 if b > a else 1)
FIN

bash outils/verifier-depot.sh
echo "Tests…"
bash lancer_tests.sh > /tmp/erp_version_tests.log 2>&1 || { tail -40 /tmp/erp_version_tests.log; echo "ÉCHEC : version non publiée."; exit 1; }
grep -E "^Ran" /tmp/erp_version_tests.log
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  bash tests/e2e/lancer_tests_navigateur.sh | tail -1 || { echo "ÉCHEC navigateur : version non publiée."; exit 1; }
else
  echo "(tests navigateur non lancés ici : ils tournent sur GitHub)"
fi

git tag -a "$V" -m "$V"
bash outils/construire-zip.sh "$V"
echo
echo "Version $V prête (précédente : $DERNIERE)."
echo "  Envoyer sur GitHub    : git push origin main --follow-tags"
echo "  Mettre sur le serveur : bash deploiement/deployer.sh $V <ip-du-serveur> <domaine>"
