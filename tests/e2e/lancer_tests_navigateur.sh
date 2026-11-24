#!/bin/bash
# Tests dans un vrai navigateur (Playwright + Chromium), données fictives.
# Première fois : installe Playwright et Chromium dans ce dossier (≈ 150 Mo, Node.js requis :
# https://nodejs.org, version LTS). Ensuite : relancer simplement ce script.
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js n'est pas installé : téléchargez la version LTS sur https://nodejs.org puis relancez."
  exit 1
fi
if ! node -e "require('playwright')" >/dev/null 2>&1; then
  echo "Installation de Playwright (une seule fois)..."
  npm install --no-audit --no-fund && npx playwright install chromium || exit 1
fi
node parcours_complet.js
