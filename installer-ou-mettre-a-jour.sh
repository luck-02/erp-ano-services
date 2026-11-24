#!/bin/bash
# Installe ou met à jour l'ERP dans Documents/ERP-ANO, sans jamais toucher aux
# données déjà présentes, et lève le blocage macOS (Gatekeeper) une fois pour toutes.
# Usage (Terminal) : tapez  bash  puis un espace, glissez CE fichier dans la fenêtre, Entrée.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Documents/ERP-ANO"
mkdir -p "$DEST"
# 1. le programme (les dossiers de données ne sont jamais écrasés)
( cd "$SRC" && tar cf - --exclude 'donnees' --exclude 'donnees-essai' --exclude 'sauvegardes' . ) | ( cd "$DEST" && tar xf - )
# 2. première installation : reprend les données du dossier téléchargé s'il y en a
if [ ! -d "$DEST/donnees" ] && [ -d "$SRC/donnees" ]; then
  cp -R "$SRC/donnees" "$DEST/donnees"
  echo "Données reprises depuis $SRC/donnees"
fi
# 3. lève la quarantaine macOS et rend les lanceurs exécutables
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
chmod +x "$DEST"/*.command "$DEST"/*.sh
echo ""
echo "ERP installé dans : $DEST"
echo "À l'avenir : double-cliquez sur « Lancer ANO.command » dans ce dossier."
echo "Pour une mise à jour : téléchargez le nouveau zip, décompressez-le, et relancez cette même commande."
open "$DEST"
open "$DEST/Lancer ANO.command"
