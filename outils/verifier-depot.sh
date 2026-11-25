#!/bin/bash
# Refuse un dépôt qui contiendrait des données réelles ou un fichier privé,
# puis vérifie la syntaxe des scripts. Lancé par la CI et par nouvelle-version.sh.
cd "$(dirname "$0")/.." || exit 1
KO=0
echec() { echo "ÉCHEC $1"; KO=1; }

if git rev-parse --git-dir >/dev/null 2>&1; then
  FICHIERS=$(git ls-files)
else
  FICHIERS=$(find . -type f -not -path './.git/*' | sed 's|^\./||')
fi

# 1. fichiers interdits : bases, cachet, dossier privé, données, clés
INTERDITS=$(echo "$FICHIERS" | grep -E '(^|/)(donnees|donnees-essai)/|^app/prive/|\.db$|\.sqlite3?$|signature\.png$|\.pem$|\.key$|id_(rsa|ed25519)|\.env$' || true)
[ -z "$INTERDITS" ] || echec "fichiers à ne jamais versionner : $INTERDITS"

# 2. secrets évidents (clé privée, jeton GitHub)
if echo "$FICHIERS" | grep -vE '^outils/verifier-depot\.sh$' | tr '\n' '\0' | xargs -0 grep -lIE -- '-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}' 2>/dev/null; then
  echec "secret trouvé dans les fichiers ci-dessus"
fi

# 3. syntaxe : Python, JavaScript, scripts shell
python3 -m py_compile app/*.py tests/*.py 2>&1 || echec "erreur de syntaxe Python"
find app tests -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null
if command -v node >/dev/null; then
  for f in app/static/app.js tests/e2e/parcours_complet.js; do node --check "$f" || echec "erreur de syntaxe JavaScript : $f"; done
fi
while IFS= read -r f; do
  [ -n "$f" ] || continue
  bash -n "$f" || echec "erreur de syntaxe shell : $f"
done <<< "$(echo "$FICHIERS" | grep -E '\.(sh|command)$')"

[ "$KO" -eq 0 ] && echo "Dépôt propre : aucun fichier privé, syntaxe correcte."
exit "$KO"
