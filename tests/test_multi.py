"""Tests V3 : plusieurs entreprises sur un même serveur « en ligne ».

Vérifie qu'une entreprise ne voit JAMAIS les données d'une autre (une base
par entreprise), que la connexion ne révèle pas les codes d'entreprise, et
les réglages HTTPS (cookie Secure, nom de domaine autorisé). Données
fictives uniquement.

Lancer : python3 tests/test_multi.py
"""
import base64
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import http.client

ICI = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ano_multi_")
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
DOMAINE = "erp.exemple.test"
os.environ.update(ANO_DONNEES=TMP, ANO_PORT=str(PORT), ANO_EN_LIGNE="1", ANO_HTTPS="1", ANO_PROXY="1",
                  ANO_HOTES=DOMAINE, ANO_PRIVE=os.path.join(TMP, "prive-origine"))
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "app"))

import serveur  # noqa: E402
import plateforme  # noqa: E402

MDP_A, MDP_B = "Provisoire-Alpha-1", "Provisoire-Beta-22"
NOUVEAU_A, NOUVEAU_B = "Alpha-Interim-2027!", "Beta-Services-2027!"


class Client:
    def __init__(self, hote=DOMAINE):
        self.cookie, self.csrf, self.hote = None, None, hote

    def req(self, methode, chemin, corps=None, entetes=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        h = {"Host": self.hote, "X-Forwarded-For": "203.0.113.%d" % (id(self) % 200)}
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf and methode != "GET":
            h["X-CSRF-Token"] = self.csrf
        data = None
        if corps is not None:
            data = json.dumps(corps).encode()
            h["Content-Type"] = "application/json"
        h.update(entetes or {})
        c.request(methode, chemin, body=data, headers=h)
        r = c.getresponse()
        txt = r.read()
        self.set_cookie = r.getheader("Set-Cookie")
        if self.set_cookie:
            v = self.set_cookie.split(";")[0]
            self.cookie = v if v.split("=", 1)[1] else None
        self.derniere = r
        c.close()
        try:
            return r.status, json.loads(txt)
        except ValueError:
            return r.status, txt

    def connexion(self, entreprise, ident, mdp):
        corps = {"identifiant": ident, "mot_de_passe": mdp}
        if entreprise is not None:
            corps["entreprise"] = entreprise
        st, j = self.req("POST", "/api/connexion", corps)
        if st == 200:
            self.csrf = j["csrf"]
        return st, j


def da(client_id, nom):
    return {"client_id": client_id, "service": "Achats", "lieu": "Libreville", "date_debut": "2026-12-01",
            "date_fin": "2027-02-28", "visite_mode": "Auto", "date_proforma": "2026-11-20", "nom_numero": nom,
            "agents": [{"nom": nom, "poste": "Assistant", "salaire_base": 400000}]}


class TestsMultiEntreprises(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = plateforme.Registre(TMP)
        reg.initialiser(en_ligne=True)
        assert reg.actives() == []                      # en ligne : aucune entreprise d'office
        reg.creer("alpha", "Alpha Intérim (fictif)", "dir-a", MDP_A)
        reg.creer("beta", "Beta Services (fictif)", "dir-b", MDP_B)
        threading.Thread(target=serveur.demarrer, kwargs={"ouvrir_navigateur": False}, daemon=True).start()
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.a, cls.b = Client(), Client()
        for c, code, ident, mdp, nouveau in ((cls.a, "alpha", "dir-a", MDP_A, NOUVEAU_A),
                                             (cls.b, "BETA ", "dir-b", MDP_B, NOUVEAU_B)):
            st, j = c.connexion(code, ident, mdp)
            assert st == 200, j
            assert j["utilisateur"]["doit_changer_mdp"]
            st, j = c.req("POST", "/api/moi/mot-de-passe", {"actuel": mdp, "nouveau": nouveau})
            assert st == 200, j

    def test_01_creation_refusee(self):
        reg = plateforme.Registre(TMP)
        for args in (("alpha", "Doublon", "x-admin", "Un-mot-de-passe-long-1"),     # code déjà pris
                     ("A", "Trop court", "x-admin", "Un-mot-de-passe-long-1"),
                     ("../etc", "Chemin", "x-admin", "Un-mot-de-passe-long-1"),
                     ("gamma", "Gamma", "x-admin", "court")):
            with self.assertRaises(plateforme.ErreurPlateforme):
                reg.creer(*args)
        self.assertFalse(os.path.exists(os.path.join(TMP, "entreprises", "gamma")))

    def test_02_connexion_ne_revele_rien(self):
        st, e = Client().req("GET", "/api/etat")
        self.assertEqual((st, e), (200, {"installation_requise": False, "multi": True}))
        st, j = Client().req("POST", "/api/installation", {"entreprise": "alpha", "identifiant": "pirate", "nom": "x",
                                                           "mot_de_passe": "Pirate-Pirate-12"})
        self.assertEqual(st, 403)                       # pas d'installation en ligne
        st1, j1 = Client().connexion("inconnue", "dir-a", NOUVEAU_A)
        st2, j2 = Client().connexion("alpha", "dir-a", "Mauvais-Mot-De-Passe")
        st3, j3 = Client().connexion(None, "dir-a", NOUVEAU_A)     # sans code : refusé
        st4, j4 = Client().connexion("beta", "dir-a", NOUVEAU_A)    # bon compte, autre entreprise
        self.assertEqual({st1, st2, st3, st4}, {401})
        self.assertEqual(len({j1["erreur"], j2["erreur"], j3["erreur"], j4["erreur"]}), 1)

    def test_03_cookie_securise(self):
        c = Client()
        st, j = c.connexion("alpha", "dir-a", NOUVEAU_A)
        self.assertEqual(st, 200)
        self.assertIn("Secure", c.set_cookie)
        self.assertIn("HttpOnly", c.set_cookie)
        self.assertTrue(c.cookie.split("=", 1)[1].startswith("alpha."))
        self.assertIn("Strict-Transport-Security", dict(c.derniere.getheaders()))
        st, j = Client(hote="autre.exemple:%d" % PORT).req("GET", "/api/etat")
        self.assertEqual(st, 400)                       # domaine non autorisé
        st, j = c.req("POST", "/api/clients", {"code": "X", "nom": "X"}, {"Origin": "http://%s" % DOMAINE})
        self.assertEqual(st, 403)                       # origine http refusée quand HTTPS est actif

    def test_04_entreprise_vierge(self):
        st, p = self.b.req("GET", "/api/parametres")
        d = p["parametres"]
        self.assertEqual((d["raison_sociale"], d["nif"], d["banque"], d["code_entreprise"], d["dernier_num_proforma"],
                          d["dernier_num_facture"]), ("Beta Services (fictif)", "", "", "BETA", 0, 0))
        st, c = self.b.req("GET", "/api/clients")
        self.assertEqual(c["clients"], [])              # aucun client d'ANO chez une autre entreprise
        st, img = self.b.req("GET", "/api/logo")
        self.assertEqual(img, serveur.api.PNG_VIDE)     # pas le logo d'ANO
        st, j = self.b.req("GET", "/api/signature")
        self.assertEqual(st, 404)

    def test_05_isolation_des_donnees(self):
        a, b = self.a, self.b
        st, cl = a.req("POST", "/api/clients", {"code": "CLA", "nom": "Client de Alpha"})
        self.assertEqual(st, 200, cl)
        st, cl = a.req("GET", "/api/clients")
        cid = cl["clients"][0]["id"]
        st, j = a.req("POST", "/api/dossiers", da(cid, "AGENT FICTIF ALPHA"))
        self.assertEqual(st, 200, j)
        did = j["id"]
        self.assertTrue(j["numero_proforma"].startswith("1-11-ALPHA-"))
        st, j = a.req("PUT", "/api/images/signature", {"png": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"a" * 30).decode()})
        self.assertEqual(st, 200)
        # Beta ne voit rien d'Alpha, même en devinant les n°
        st, l = b.req("GET", "/api/dossiers")
        self.assertEqual((st, l["dossiers"]), (200, []))
        st, j = b.req("GET", "/api/dossiers/%d" % did)
        self.assertEqual(st, 404)
        st, j = b.req("GET", "/api/factures")
        self.assertEqual(j["factures"], [])
        st, j = b.req("GET", "/api/interimaires")
        self.assertEqual(j["interimaires"], [])
        st, j = b.req("GET", "/api/clients")
        self.assertEqual(j["clients"], [])
        st, j = b.req("GET", "/api/signature")
        self.assertEqual(st, 404)                       # le cachet d'Alpha reste chez Alpha
        st, t = b.req("GET", "/api/tableau-de-bord")
        self.assertEqual(t["personnes_en_contrat"], 0)
        st, j = b.req("GET", "/api/journal")
        self.assertNotIn("ALPHA", json.dumps(j).upper())     # aucune action d'Alpha dans le journal de Beta
        # et les n° de Beta ne bougent pas avec ceux d'Alpha
        st, cl = b.req("POST", "/api/clients", {"code": "CLB", "nom": "Client de Beta"})
        st, cl = b.req("GET", "/api/clients")
        st, j = b.req("POST", "/api/dossiers", da(cl["clients"][0]["id"], "AGENT FICTIF BETA"))
        self.assertTrue(j["numero_proforma"].startswith("1-11-BETA-"))

    def test_06_jeton_d_une_autre_entreprise(self):
        jeton = self.a.cookie.split("=", 1)[1].split(".", 1)[1]
        pirate = Client()
        pirate.cookie, pirate.csrf = "ano_session=beta." + jeton, self.a.csrf
        st, j = pirate.req("GET", "/api/moi")
        self.assertEqual(st, 401)                       # le jeton d'Alpha n'ouvre rien chez Beta
        pirate.cookie = "ano_session=" + jeton          # ancien format, sans code
        st, j = pirate.req("GET", "/api/moi")
        self.assertEqual(st, 401)
        pirate.cookie = "ano_session=../alpha." + jeton
        st, j = pirate.req("GET", "/api/moi")
        self.assertEqual(st, 401)

    def test_07_fichiers_separes(self):
        ea = plateforme.Registre(TMP).trouver("alpha")
        eb = plateforme.Registre(TMP).trouver("beta")
        self.assertNotEqual(ea["chemin_db_abs"], eb["chemin_db_abs"])
        self.assertNotEqual(ea["prive_abs"], eb["prive_abs"])
        self.assertTrue(os.path.exists(os.path.join(ea["prive_abs"], "signature.png")))
        self.assertFalse(os.path.exists(os.path.join(eb["prive_abs"], "signature.png")))
        with open(os.path.join(TMP, "plateforme.db"), "rb") as f:
            self.assertNotIn(b"400000", f.read())       # le registre ne contient aucune donnée métier

    def test_08_sante_et_sauvegarde(self):
        st, j = Client().req("GET", "/api/sante")
        self.assertEqual((st, j), (200, {"ok": True}))  # supervision, sans connexion ni donnée
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(ICI), "app", "sauvegarde_quotidienne.py")],
                           env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for code in ("alpha", "beta"):
            d = plateforme.Registre(TMP).trouver(code)["sauvegardes_abs"]
            self.assertTrue(os.listdir(d))

    def test_99_entreprise_desactivee(self):
        reg = plateforme.Registre(TMP)
        reg.activer("beta", False)
        try:
            st, j = self.b.req("GET", "/api/moi")
            self.assertEqual(st, 401)
            st, j = Client().connexion("beta", "dir-b", NOUVEAU_B)
            self.assertEqual(st, 401)
        finally:
            reg.activer("beta", True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
