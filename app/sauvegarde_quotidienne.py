"""Sauvegarde de toutes les entreprises (à lancer chaque jour sur le serveur,
voir deploiement/erp-sauvegarde.timer). Copie cohérente de chaque base SQLite
dans son dossier « sauvegardes » ; les 30 dernières copies sont gardées.
Aucune donnée n'est envoyée ailleurs : copier ensuite /var/lib/erp hors du
serveur (chiffré) reste à faire par l'administrateur."""
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import db  # noqa: E402
import plateforme  # noqa: E402

if __name__ == "__main__":
    donnees = os.environ.get("ANO_DONNEES", os.path.join(os.path.dirname(ICI), "donnees"))
    reg = plateforme.Registre(donnees)
    erreurs = 0
    for e in reg.toutes():
        try:
            chemin = db.sauvegarder(e["chemin_db_abs"], e["sauvegardes_abs"])
            print("%s : %s" % (e["code"], chemin or "aucune base"))
        except Exception as x:      # une entreprise en échec n'empêche pas les autres
            erreurs += 1
            print("%s : ÉCHEC %s" % (e["code"], x), file=sys.stderr)
    sys.exit(1 if erreurs else 0)
