"""Plateforme multi-entreprises (V3) : registre des entreprises clientes.

Chaque entreprise a SA PROPRE base SQLite et son propre dossier privé
(logo, cachet, sauvegardes). Une requête n'ouvre jamais que la base de
l'entreprise de l'utilisateur connecté : les données d'une entreprise ne
peuvent donc pas apparaître chez une autre, même en cas d'erreur dans une
requête SQL.

Le registre (donnees/plateforme.db) ne contient que les noms et les
emplacements : aucune donnée métier, aucun salaire.

Ligne de commande (administration de la plateforme, sur le serveur) :
    python3 app/plateforme.py liste
    python3 app/plateforme.py creer CODE "Nom de l'entreprise" IDENTIFIANT_ADMIN
    python3 app/plateforme.py desactiver CODE
    python3 app/plateforme.py activer CODE
"""
import datetime as dt
import os
import re
import sqlite3
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import db  # noqa: E402
import securite as S  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS entreprises (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    nom TEXT NOT NULL,
    chemin_db TEXT NOT NULL,          -- relatif au dossier des données
    dossier_prive TEXT NOT NULL,      -- relatif au dossier des données ; '' = app/prive (installation d'origine)
    actif INTEGER NOT NULL DEFAULT 1,
    cree_le TEXT NOT NULL
);
"""
MOTIF_CODE = re.compile(r"[a-z0-9][a-z0-9-]{1,29}")


class ErreurPlateforme(Exception):
    pass


def normaliser_code(code):
    return (code or "").strip().lower()


class Registre:
    def __init__(self, donnees):
        self.donnees = donnees
        self.chemin = os.path.join(donnees, "plateforme.db")

    def _con(self):
        con = sqlite3.connect(self.chemin, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        return con

    def initialiser(self, en_ligne=False):
        """Crée le registre. Hors ligne (installation sur un poste), la base
        d'origine donnees/ano.db devient l'entreprise « ano » SANS être
        déplacée ni modifiée."""
        os.makedirs(self.donnees, mode=0o700, exist_ok=True)
        con = self._con()
        con.executescript(SCHEMA)
        vide = con.execute("SELECT COUNT(*) FROM entreprises").fetchone()[0] == 0
        ancienne = os.path.exists(os.path.join(self.donnees, "ano.db"))
        if vide and (ancienne or not en_ligne):
            con.execute("INSERT INTO entreprises(code, nom, chemin_db, dossier_prive, cree_le) VALUES (?,?,?,?,?)",
                        ("ano", "ANO Services", "ano.db", "", db.maintenant()))
        con.close()
        try:
            os.chmod(self.chemin, 0o600)
        except OSError:
            pass

    def _complet(self, r):
        if r is None:
            return None
        e = dict(r)
        e["chemin_db_abs"] = os.path.join(self.donnees, e["chemin_db"])
        e["origine"] = e["dossier_prive"] == ""
        # ANO_PRIVE : dossier privé de l'installation d'origine (tests : dossier temporaire)
        origine = os.environ.get("ANO_PRIVE") or os.path.join(ICI, "prive")
        e["prive_abs"] = origine if e["origine"] else os.path.join(self.donnees, e["dossier_prive"])
        base = os.path.dirname(e["chemin_db_abs"])
        e["sauvegardes_abs"] = os.path.join(base, "sauvegardes")
        return e

    def trouver(self, code):
        """Entreprise active par son code, ou None."""
        code = normaliser_code(code)
        if not MOTIF_CODE.fullmatch(code):
            return None
        con = self._con()
        try:
            return self._complet(con.execute("SELECT * FROM entreprises WHERE code = ? AND actif = 1", (code,)).fetchone())
        finally:
            con.close()

    def actives(self):
        con = self._con()
        try:
            return [self._complet(r) for r in con.execute("SELECT * FROM entreprises WHERE actif = 1 ORDER BY id")]
        finally:
            con.close()

    def toutes(self):
        con = self._con()
        try:
            return [self._complet(r) for r in con.execute("SELECT * FROM entreprises ORDER BY id")]
        finally:
            con.close()

    def choisir(self, code):
        """Code donné -> cette entreprise ; pas de code -> la seule entreprise
        active s'il n'y en a qu'une (installation sur un poste)."""
        if code:
            return self.trouver(code)
        a = self.actives()
        return a[0] if len(a) == 1 else None

    def creer(self, code, nom, identifiant_admin, mdp_admin):
        """Nouvelle entreprise vierge (aucun client, compteurs à 0, identité
        à compléter) + son premier compte Direction, qui devra changer son
        mot de passe à la première connexion."""
        code = normaliser_code(code)
        if not MOTIF_CODE.fullmatch(code):
            raise ErreurPlateforme("Code : 2 à 30 caractères, minuscules, chiffres ou tirets (ex. acme-interim).")
        nom = (nom or "").strip()
        if not nom or len(nom) > 80:
            raise ErreurPlateforme("Nom de l'entreprise obligatoire (80 caractères au plus).")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", identifiant_admin or ""):
            raise ErreurPlateforme("Identifiant : 3 à 40 caractères (lettres, chiffres, . _ -).")
        p = S.probleme_mdp(mdp_admin, identifiant_admin)
        if p:
            raise ErreurPlateforme(p)
        dossier = os.path.join("entreprises", code)
        chemin_db = os.path.join(dossier, "erp.db")
        con = self._con()
        try:
            if con.execute("SELECT 1 FROM entreprises WHERE code = ?", (code,)).fetchone():
                raise ErreurPlateforme("Le code « %s » est déjà pris." % code)
            os.makedirs(os.path.join(self.donnees, dossier, "prive"), mode=0o700, exist_ok=True)
            chemin_abs = os.path.join(self.donnees, chemin_db)
            db.initialiser(chemin_abs, vierge=True, nom=nom, code=code)
            c2 = db.connecter(chemin_abs)
            c2.execute("INSERT INTO utilisateurs(identifiant, nom, role, mdp_hash, doit_changer_mdp, cree_le) "
                       "VALUES (?,?,?,?,1,?)", (identifiant_admin, "Direction", "admin", S.hacher_mdp(mdp_admin),
                                                 db.maintenant()))
            c2.close()
            con.execute("INSERT INTO entreprises(code, nom, chemin_db, dossier_prive, cree_le) VALUES (?,?,?,?,?)",
                        (code, nom, chemin_db, os.path.join(dossier, "prive"), db.maintenant()))
        finally:
            con.close()
        return self.trouver(code)

    def activer(self, code, actif):
        con = self._con()
        try:
            n = con.execute("UPDATE entreprises SET actif = ? WHERE code = ?", (1 if actif else 0, normaliser_code(code))).rowcount
        finally:
            con.close()
        if not n:
            raise ErreurPlateforme("Entreprise inconnue.")


def _main(argv):
    import getpass
    donnees = os.environ.get("ANO_DONNEES", os.path.join(os.path.dirname(ICI), "donnees"))
    reg = Registre(donnees)
    reg.initialiser(en_ligne=os.environ.get("ANO_EN_LIGNE") == "1")
    if len(argv) >= 1 and argv[0] == "liste":
        for e in reg.toutes():
            print("%-20s %-40s %s  créée le %s" % (e["code"], e["nom"], "active" if e["actif"] else "DÉSACTIVÉE", e["cree_le"]))
        return 0
    if len(argv) == 4 and argv[0] == "creer":
        mdp = getpass.getpass("Mot de passe provisoire du compte %s (12 caractères min.) : " % argv[3])
        if getpass.getpass("Confirmez : ") != mdp:
            print("Les deux saisies diffèrent.")
            return 1
        try:
            e = reg.creer(argv[1], argv[2], argv[3], mdp)
        except ErreurPlateforme as x:
            print("Refusé : %s" % x)
            return 1
        print("Entreprise « %s » créée (code %s). Le compte %s devra changer son mot de passe "
              "à la première connexion." % (e["nom"], e["code"], argv[3]))
        return 0
    if len(argv) == 2 and argv[0] in ("activer", "desactiver"):
        try:
            reg.activer(argv[1], argv[0] == "activer")
        except ErreurPlateforme as x:
            print("Refusé : %s" % x)
            return 1
        print("OK")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
