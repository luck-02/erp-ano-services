#!/bin/bash
# Construit le zip d'une version À PARTIR DE GIT (jamais du dossier de travail) :
# seuls les fichiers versionnés y entrent, donc ni cachet ni données.
#   bash outils/construire-zip.sh v3.3.0     ->  dist/ERP_ANO_Services-v3.3.0.zip
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:?Donnez la version, ex. v3.3.0}"
git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null || { echo "Étiquette $VERSION introuvable (git tag)."; exit 1; }
mkdir -p dist
SORTIE="dist/ERP_ANO_Services-$VERSION.zip"
# le fichier VERSION est rempli par git archive (voir .gitattributes)
git archive --format=zip --prefix=erp-mvp/ -o "$SORTIE" "$VERSION"
echo "$SORTIE"
