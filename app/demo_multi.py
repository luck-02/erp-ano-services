"""Essai local de la V3 : plusieurs entreprises FICTIVES sur ce Mac.

Dossier de données séparé (donnees-essai/) et port séparé (8766) : la vraie
installation d'ANO (donnees/, port 8765) n'est jamais touchée.
Lancement : double-clic sur « Essai plusieurs entreprises.command ».
"""
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.path.join(os.path.dirname(ICI), "donnees-essai")
os.environ.update(ANO_DONNEES=DONNEES, ANO_PORT="8766", ANO_EN_LIGNE="1")
sys.path.insert(0, ICI)

import plateforme  # noqa: E402
import serveur  # noqa: E402

# Entreprises fictives et mots de passe provisoires (à changer à la 1re connexion)
ESSAI = [("alpha", "Alpha Intérim (fictif)", "direction", "Essai-Alpha-2026"),
         ("beta", "Beta Services (fictif)", "direction", "Essai-Beta-2026")]

if __name__ == "__main__":
    reg = plateforme.Registre(DONNEES)
    reg.initialiser(en_ligne=True)
    for code, nom, ident, mdp in ESSAI:
        if not reg.trouver(code):
            reg.creer(code, nom, ident, mdp)
    print("\n  ESSAI plusieurs entreprises (données fictives uniquement)")
    for code, nom, ident, mdp in ESSAI:
        print("  - %-24s code : %-6s identifiant : %-10s mot de passe provisoire : %s" % (nom, code, ident, mdp))
    import threading
    import webbrowser
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8766/")).start()
    serveur.demarrer(ouvrir_navigateur=False)
