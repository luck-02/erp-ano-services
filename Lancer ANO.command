#!/bin/bash
# Double-cliquez sur ce fichier pour ouvrir l'ERP ANO Services.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 n'est pas installé. Voir le README, étape 1."
  read -r -p "Appuyez sur Entrée pour fermer."
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Python 3.9 ou plus récent est nécessaire. Voir le README, étape 1."
  read -r -p "Appuyez sur Entrée pour fermer."
  exit 1
}
python3 app/serveur.py
