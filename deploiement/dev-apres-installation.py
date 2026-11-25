"""Site de test seulement : lancé par erp-installer-dev après chaque mise à jour,
sous le compte erp-dev, avec les mêmes protections que le site de test (aucun accès
à la production). Ne sert jamais en production.

1. Entreprise « essai » (celle de Luc) : remplie UNE FOIS avec le jeu de données fictives
   s'il n'y a encore aucun dossier (compte temporaire, désactivé juste après).
2. Entreprise « verif » : recréée vide à chaque mise à jour puis remplie, pour les tests
   automatiques en ligne. Son mot de passe arrive sur l'entrée standard (tiré au hasard
   par GitHub à chaque envoi, jamais écrit en clair sur le serveur). Sans mot de passe : sautée.

  python3 dev-apres-installation.py <dossier des données> <domaine> < mot de passe
"""
import os
import secrets
import shutil
import sqlite3
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
sys.path.insert(0, os.path.join(RACINE, "app"))
sys.path.insert(0, os.path.join(RACINE, "outils"))

import db  # noqa: E402
import donnees_fictives as F  # noqa: E402
import plateforme as P  # noqa: E402
import securite as S  # noqa: E402

PORT = os.environ.get("ANO_PORT", "8766")


def client(domaine):
    c = F.Client("http://127.0.0.1:%s" % PORT, hote=domaine)
    c.origine = ("https://" if os.environ.get("ANO_HTTPS") else "http://") + domaine
    return c


def remplir_essai(reg, domaine):
    e = reg.trouver("essai")
    if not e:
        return "essai : absente"
    con = sqlite3.connect(e["chemin_db_abs"])
    try:
        if con.execute("SELECT COUNT(*) FROM dossiers").fetchone()[0]:
            return "essai : déjà des dossiers, rien changé"
        mdp = "Tmp-" + secrets.token_urlsafe(18)
        ident = "remplissage-auto"
        if con.execute("SELECT 1 FROM utilisateurs WHERE identifiant = ?", (ident,)).fetchone():
            con.execute("UPDATE utilisateurs SET mdp_hash = ?, actif = 1, doit_changer_mdp = 0, echecs = 0, "
                        "bloque_jusqu = NULL WHERE identifiant = ?", (S.hacher_mdp(mdp), ident))
        else:
            con.execute("INSERT INTO utilisateurs(identifiant, nom, role, mdp_hash, doit_changer_mdp, cree_le) "
                        "VALUES (?,?,?,?,0,?)", (ident, "Remplissage automatique (fictif)", "admin",
                                                 S.hacher_mdp(mdp), db.maintenant()))
        con.commit()
        try:
            c = client(domaine)
            c.connexion("essai", ident, mdp)
            r = F.remplir(c)
        finally:
            # compte inutilisable ensuite (gardé désactivé : il signe les lignes du journal)
            con.execute("DELETE FROM sessions WHERE user_id = (SELECT id FROM utilisateurs WHERE identifiant = ?)", (ident,))
            con.execute("UPDATE utilisateurs SET actif = 0, mdp_hash = ? WHERE identifiant = ?",
                        (S.hacher_mdp(secrets.token_urlsafe(32)), ident))
            con.commit()
        return "essai : remplie (%d dossiers fictifs)" % len(r)
    finally:
        con.close()


def recreer_verif(reg, donnees, domaine, mdp):
    if not mdp:
        return "verif : pas de mot de passe reçu, sautée"
    con = sqlite3.connect(reg.chemin)
    con.execute("DELETE FROM entreprises WHERE code = 'verif'")
    con.commit()
    con.close()
    shutil.rmtree(os.path.join(donnees, "entreprises", "verif"), ignore_errors=True)
    e = reg.creer("verif", "Vérification automatique (fictif)", "direction", mdp)
    c2 = sqlite3.connect(e["chemin_db_abs"])
    c2.execute("UPDATE utilisateurs SET doit_changer_mdp = 0")
    c2.commit()
    c2.close()
    c = client(domaine)
    c.connexion("verif", "direction", mdp)
    r = F.remplir(c)
    return "verif : recréée (%d dossiers fictifs)" % len(r)


def main(argv):
    donnees, domaine = argv[0], argv[1]
    if "erp-dev" not in donnees and not os.environ.get("ANO_ESSAI_LOCAL"):
        sys.exit("Réservé au site de test.")
    mdp = sys.stdin.readline().strip() if not sys.stdin.isatty() else ""
    reg = P.Registre(donnees)
    for etape in (lambda: remplir_essai(reg, domaine), lambda: recreer_verif(reg, donnees, domaine, mdp)):
        try:
            print(etape())
        except Exception as e:  # une étape ratée ne doit pas casser la mise à jour du site
            print("ERREUR : %s" % e)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
