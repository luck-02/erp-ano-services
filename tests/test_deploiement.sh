#!/bin/bash
# Tests de la commande de déploiement du serveur (deploiement/erp-deployer), avec un
# installateur et une recette factices : commandes refusées, zip piégé, version
# incohérente, déploiement réussi, retour automatique à la version précédente.
# Lancer : bash tests/test_deploiement.sh
set -u
cd "$(dirname "$0")/.." || exit 1
DEPLOYER="$PWD/deploiement/erp-deployer"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export ERP_DEPLOIEMENT_TEST="$T/serveur"
mkdir -p "$ERP_DEPLOIEMENT_TEST"
echo "DOMAINE=erp.exemple.test" > "$ERP_DEPLOIEMENT_TEST/erp-deploiement.conf"
OK=0; KO=0
verif() { if [ "$2" = "$3" ]; then OK=$((OK+1)); echo "  ok    $1"; else KO=$((KO+1)); echo "  ÉCHEC $1 (attendu $3, obtenu $2)"; fi; }

# zip factice : version, recette ok|ko, contenu de VERSION, préfixe des chemins
faux_zip() {
  python3 - "$T/$1.zip" "$1" "$2" "${3:-$1}" "${4:-erp-mvp/}" "$T/journal" <<'FIN'
import sys, zipfile
sortie, v, recette, version, pre, journal = sys.argv[1:]
with zipfile.ZipFile(sortie, "w") as z:
    z.writestr(pre + "VERSION", version + "\n")
    z.writestr(pre + "deploiement/installer-serveur.sh", '#!/bin/bash\necho "installe %s" >> %s\n' % (v, journal))
    z.writestr(pre + "deploiement/verifier-en-ligne.sh",
               '#!/bin/bash\necho "0 controle, 0 echec"\n' + ("" if recette == "ok" else "exit 1\n"))
FIN
}
lancer() { SSH_ORIGINAL_COMMAND="$1" bash "$DEPLOYER" < "$2" > "$T/sortie" 2>&1; echo $?; }
actuelle() { cat "$ERP_DEPLOIEMENT_TEST/actuelle" 2>/dev/null || echo aucune; }

faux_zip v1.0.0 ok; faux_zip v1.1.0 ko; faux_zip v1.2.0 ok v9.9.9; faux_zip v1.3.0 ok v1.3.0 "../"
verif "autre commande refusée"           "$(lancer 'bash -i' "$T/v1.0.0.zip")" 2
verif "version mal écrite refusée"       "$(lancer 'deployer v1;id' "$T/v1.0.0.zip")" 2
verif "argument en trop refusé"          "$(lancer 'deployer v1.0.0 x' "$T/v1.0.0.zip")" 2
verif "première version installée"       "$(lancer 'deployer v1.0.0' "$T/v1.0.0.zip")" 0
verif "version en place notée"           "$(actuelle)" v1.0.0
verif "recette en échec signalée"        "$(lancer 'deployer v1.1.0' "$T/v1.1.0.zip")" 5
verif "retour auto à la version d'avant" "$(actuelle)" v1.0.0
verif "dernière installation = v1.0.0"   "$(tail -1 "$T/journal")" "installe v1.0.0"
verif "VERSION incohérente refusée"      "$(lancer 'deployer v1.2.0' "$T/v1.2.0.zip")" 4
verif "zip hors de erp-mvp/ refusé"      "$(lancer 'deployer v1.3.0' "$T/v1.3.0.zip")" 4
: > "$T/vide.zip"
verif "zip vide refusé"                  "$(lancer 'deployer v1.4.0' "$T/vide.zip")" 4
verif "rien installé par les refus"      "$(grep -c . "$T/journal")" 3

# --- site de test (branche dev)
python3 - "$T/dev.zip" <<'FIN'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("erp-mvp/app/serveur.py", "# faux\n")
FIN
verif "dev : commande mal écrite refusée"   "$(lancer 'deployer-dev v1.0.0' "$T/dev.zip")" 2
verif "dev : site pas installé = rien fait" "$(lancer 'deployer-dev dev-abc1234' "$T/dev.zip")" 0
echo "DOMAINE_DEV=dev.erp.exemple.test" >> "$ERP_DEPLOIEMENT_TEST/erp-deploiement.conf"
printf '#!/bin/bash\necho "dev $1 $2" >> %s\n' "$T/journal-dev" > "$ERP_DEPLOIEMENT_TEST/erp-installer-dev"
chmod +x "$ERP_DEPLOIEMENT_TEST/erp-installer-dev"
printf '#!/bin/bash\necho "0 controle, 0 echec"\n' > "$ERP_DEPLOIEMENT_TEST/recette-dev"
verif "dev : site de test mis à jour"       "$(lancer 'deployer-dev dev-abc1234' "$T/dev.zip")" 0
verif "dev : installé avec le domaine dev"  "$(awk '{print $1, $3}' "$T/journal-dev")" "dev dev.erp.exemple.test"
verif "dev : production inchangée"          "$(actuelle)" v1.0.0
printf '#!/bin/bash\nexit 1\n' > "$ERP_DEPLOIEMENT_TEST/recette-dev"
verif "dev : recette en échec signalée"     "$(lancer 'deployer-dev dev-def5678' "$T/dev.zip")" 5
verif "dev : production toujours inchangée" "$(actuelle)" v1.0.0
verif "dev : zip piégé refusé"              "$(lancer 'deployer-dev dev-0000000' "$T/v1.3.0.zip")" 4

echo "$OK contrôle(s) réussi(s), $KO échec(s)."
[ "$KO" -eq 0 ]
