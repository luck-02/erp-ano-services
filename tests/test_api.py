"""Tests de bout en bout de l'API : un vrai serveur est lancé sur un port
libre avec une base vide dans un dossier temporaire. Données fictives
uniquement (le cas de référence reprend les chiffres du dossier de référence
avec un nom inventé).

Lancer : python3 tests/test_api.py
"""
import http.client
import json
import re
import urllib.parse
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ano_test_")
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
os.environ["ANO_DONNEES"] = TMP
os.environ["ANO_PORT"] = str(PORT)
# copies PDF des factures : désactivées ici (test séparé), pour des tests rapides
os.environ["ANO_SOFFICE"] = os.path.join(TMP, "pas-de-libreoffice")
# cachet fictif dans un dossier temporaire : jamais le vrai cachet de app/prive
os.environ["ANO_PRIVE"] = os.path.join(TMP, "prive")
os.makedirs(os.environ["ANO_PRIVE"])


def png_test(l=40, h=20):
    import struct
    import zlib

    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    brut = b"".join(b"\x00" + b"\x10\x40\xa0" * l for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", l, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(brut)) + ch(b"IEND", b""))


with open(os.path.join(os.environ["ANO_PRIVE"], "signature.png"), "wb") as _f:
    _f.write(png_test())
sys.path.insert(0, os.path.join(os.path.dirname(ICI), "app"))

import serveur  # noqa: E402

MDP_ADMIN = "Moanda-Bureau-2026!"


class Client:
    def __init__(self, hote="127.0.0.1:%d" % PORT):
        self.cookie = None
        self.csrf = None
        self.hote = hote

    def req(self, methode, chemin, corps=None, entetes=None, brut=None):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
        h = {"Host": self.hote}
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf and methode != "GET":
            h["X-CSRF-Token"] = self.csrf
        data = None
        if corps is not None or brut is not None:
            data = brut if brut is not None else json.dumps(corps).encode()
            h["Content-Type"] = "application/json"
        h.update(entetes or {})
        c.request(methode, chemin, body=data, headers=h)
        r = c.getresponse()
        txt = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            v = sc.split(";")[0]
            self.cookie = v if v.split("=", 1)[1] else None
        try:
            j = json.loads(txt)
        except ValueError:
            j = txt
        self.derniere = r
        c.close()
        return r.status, j

    def connexion(self, ident, mdp):
        st, j = self.req("POST", "/api/connexion", {"identifiant": ident, "mot_de_passe": mdp})
        if st == 200:
            self.csrf = j["csrf"]
        return st, j


def da_reference(client_id=1, nom="TESTEUR REFERENCE Alpha"):
    return {"client_id": client_id, "num_da": "DA-TEST-1", "service": "DAF", "imputation": "IMP-01", "lieu": "Moanda",
            "date_debut": "2026-11-02", "date_fin": "2027-05-01", "visite_mode": "Auto",
            "date_proforma": "2026-10-30", "nom_numero": "TESTEUR REFERENCE",
            "agents": [{"nom": nom, "poste": "Comptable fournisseurs", "salaire_base": 576300}]}


class TestsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t = threading.Thread(target=serveur.demarrer, kwargs={"ouvrir_navigateur": False}, daemon=True)
        t.start()
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.admin = Client()
        st, j = cls.admin.req("GET", "/api/etat")
        assert j["installation_requise"] is True
        st, j = cls.admin.req("POST", "/api/installation",
                              {"identifiant": "direction", "nom": "Direction", "mot_de_passe": MDP_ADMIN})
        assert st == 200, j
        st, j = cls.admin.connexion("direction", MDP_ADMIN)
        assert st == 200, j

    # ------------------------------------------------------------------ métier
    def test_01_cas_de_reference(self):
        a = self.admin
        st, ap = a.req("POST", "/api/dossiers/apercu", da_reference())
        self.assertEqual(st, 200, ap)
        self.assertEqual(ap["cumul_ht"], 6648214)
        self.assertEqual(ap["numero_propose"], "349-10-ANO-TESTEUR REFERENCE/2026")   # dernier devis réel : 348
        st, j = a.req("POST", "/api/dossiers", da_reference())
        self.assertEqual(st, 200, j)
        did = j["id"]
        self.assertEqual(j["numero_proforma"], "349-10-ANO-TESTEUR REFERENCE/2026")
        st, d = a.req("GET", "/api/dossiers/%d" % did)
        pro = d["proforma"]
        self.assertEqual(pro["cout_mensuel_total"], 1100733)
        self.assertEqual(pro["cumul_ht"], 6648214)
        self.assertEqual(pro["tva"], 1196679)
        self.assertEqual([m["jours"] for m in pro["mois"]], [29, 31, 31, 28, 31, 30, 1])
        self.assertEqual(len(pro["detail_charges"]), 10)
        self.assertEqual(pro["detail_charges"][1]["total"], 106616)   # CNSS 18,5 %
        # Générer sans BC : refus
        st, j = a.req("POST", "/api/dossiers/%d/generer-factures" % did, {})
        self.assertEqual(st, 409)
        self.assertEqual(j["code"], "SANS_BC")
        # BC 493930 au montant exact
        st, j = a.req("POST", "/api/dossiers/%d/bc" % did, {"bc_numero": "493930", "bc_montant": 6648214})
        self.assertEqual((st, j["ecart"]), (200, 0))
        st, j = a.req("POST", "/api/dossiers/%d/generer-factures" % did, {})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["ajoutees"], 8)
        # Relancer ne duplique rien
        st, j = a.req("POST", "/api/dossiers/%d/generer-factures" % did, {})
        self.assertEqual((j["ajoutees"], j["total"]), (0, 8))
        st, f = a.req("GET", "/api/factures?dossier=%d" % did)
        fs = f["factures"]
        self.assertEqual([x["type"] for x in fs], ["VISITE"] + ["MAD"] * 7)
        self.assertEqual([x["montant_ht"] for x in fs],
                         [45000, 1064042, 1100733, 1100733, 1100733, 1100733, 1100733, 35508])
        self.assertEqual(fs[1]["tva"], 191528)
        # visite médicale : pas de TVA
        self.assertEqual((fs[0]["tva"], fs[0]["ttc"]), (0, 45000))
        self.assertEqual(fs[1]["ttc"], 1064042 + 191528)
        type(self).did = did

    def test_02_emission_rattrapage_bis_paiement(self):
        a = self.admin
        # dernière facture réelle : FA 161 (la suivante sera FA 162) ; le test repart de 152
        st, pa = a.req("GET", "/api/parametres")
        self.assertEqual(pa["parametres"]["dernier_num_facture"], 161)
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"dernier_num_facture": 152}})
        self.assertEqual(st, 200, j)
        # décembre + rattrapage de novembre (visite + novembre) = 3 factures
        st, j = a.req("POST", "/api/factures/emettre",
                      {"mois": "2026-12", "rattrapage": True, "date_facture": "2026-12-05"})
        self.assertEqual((st, j["emises"]), (200, 3), j)
        st, f = a.req("GET", "/api/factures?ids=" + ",".join(map(str, j["ids"])))
        nums = [x["numero"] for x in f["factures"]]
        # visite + facture de novembre émises ensemble -> même n° 153 ; 12 = mois d'émission
        self.assertEqual(nums, ["FA 153/Visite médicale/2026", "FA 153/12/2026", "FA 154/12/2026"])
        self.assertEqual(f["factures"][0]["echeance"], "2027-01-31")   # 05/12 + 30 j -> fin janvier
        # relancer : rien de plus
        st, j2 = a.req("POST", "/api/factures/emettre", {"mois": "2026-12", "rattrapage": True})
        self.assertEqual(j2["emises"], 0)
        nov = f["factures"][1]
        # envoyée
        st, j = a.req("POST", "/api/factures/envoyees", {"ids": [x["id"] for x in f["factures"]], "date": "2026-12-06"})
        self.assertEqual(j["modifiees"], 3)
        # facture bis selon PV
        st, j = a.req("POST", "/api/factures/%d/bis" % nov["id"], {"montant_ht": 1060000, "date_pv": "2026-12-20"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["numero"], "FA 153 bis/12/2026")
        st, j3 = a.req("POST", "/api/factures/%d/bis" % nov["id"], {"montant_ht": 1, "date_pv": "2026-12-20"})
        self.assertEqual(st, 409)
        # paiement de la bis
        st, fb = a.req("GET", "/api/factures?ids=%d,%d" % (nov["id"], j["id"]))
        st_par_num = {x["numero"]: x for x in fb["factures"]}
        self.assertEqual(st_par_num["FA 153/12/2026"]["statut"], "Remplacée")
        bis = st_par_num["FA 153 bis/12/2026"]
        self.assertEqual(bis["ttc"], 1060000 + 190800)
        st, j = a.req("POST", "/api/factures/paiement", {"ids": [bis["id"]], "date": "2027-03-15", "reference": "VIR-0001"})
        self.assertEqual(j["modifiees"], 1)
        # export Word : une facture seule -> .docx ; plusieurs -> .zip d'un .docx par facture
        import io
        import zipfile
        vis = f["factures"][0]
        st, doc = a.req("GET", "/api/factures/word?ids=%d" % vis["id"])
        self.assertEqual(st, 200)
        self.assertIn("wordprocessingml", a.derniere.getheader("Content-Type"))
        self.assertIn("attachment", a.derniere.getheader("Content-Disposition"))
        self.assertIn("COMILOG SA - Facture Novembre 2026 - ", urllib.parse.unquote(a.derniere.getheader("Content-Disposition")))
        z = zipfile.ZipFile(io.BytesIO(doc))
        xml = z.read("word/document.xml").decode()
        self.assertIn("N° FA 153/Visite médicale/2026", xml)
        self.assertIn("TVA (18 %)</w:t></w:r></w:p></w:tc><w:tc><w:tcPr><w:tcW w:w=\"1600\" w:type=\"dxa\"/><w:vAlign w:val=\"top\"/></w:tcPr><w:p><w:pPr><w:spacing w:before=\"60\" w:after=\"60\"/></w:pPr><w:r><w:rPr><w:sz w:val=\"22\"/><w:szCs w:val=\"22\"/></w:rPr><w:t xml:space=\"preserve\">0<", xml)   # visite : TVA (18 %) = 0
        self.assertNotIn("Modalité", xml)
        for interne in ("Imputation", "IMP-01", "CLI001", vis["numero_proforma"], "DA-"):
            self.assertNotIn(interne, xml)          # infos internes : jamais sur la facture
        self.assertIn("45.000", xml)
        self.assertIn("RCCM", z.read("word/footer1.xml").decode())
        st, doc = a.req("GET", "/api/factures/word?ids=%d,%d" % (bis["id"], f["factures"][2]["id"]))
        self.assertEqual(st, 200)
        z = zipfile.ZipFile(io.BytesIO(doc))
        self.assertEqual(len(z.namelist()), 2)
        xml = z.read([n for n in z.namelist() if "153 bis" in n][0])
        xml = zipfile.ZipFile(io.BytesIO(xml)).read("word/document.xml").decode()
        self.assertIn("Ajustement selon PV", xml)
        self.assertIn("Facture Novembre 2026", xml)
        self.assertNotIn("PV du", xml)              # pas de dates dans la désignation
        self.assertIn("TVA (18 %)", xml)
        self.assertIn("1.250.800", xml)
        st, j = a.req("GET", "/api/factures/word?ids=abc")
        self.assertEqual(st, 400)
        # paiement d'une facture remplacée : ignoré
        st, j = a.req("POST", "/api/factures/paiement", {"ids": [nov["id"]], "date": "2027-03-15", "reference": "X"})
        self.assertEqual(j["modifiees"], 0)
        # export Excel (CSV) : en-têtes, accents, pas de salaire, formules neutralisées
        st, csv = a.req("GET", "/api/factures/export.csv")
        self.assertEqual(st, 200)
        self.assertIn("text/csv", a.derniere.getheader("Content-Type"))
        txt = csv.decode("utf-8-sig")
        self.assertTrue(txt.startswith("N° facture;Mois;Type"))
        self.assertIn("FA 153 bis/12/2026", txt)
        self.assertNotIn("576300", txt)                 # jamais le salaire de base
        self.assertEqual(serveur.api._cellule_csv("=SOMME(A1)"), "'=SOMME(A1)")
        self.assertEqual(serveur.api._cellule_csv('a;"b"'), '"a;""b"""')
        # tableau de bord : liste « À faire »
        st, t = a.req("GET", "/api/tableau-de-bord")
        self.assertIn("a_faire", t)
        self.assertEqual(set(t["a_faire"]), {"a_emettre", "a_envoyer", "en_retard", "brouillons", "sans_bc"})
        self.assertEqual(t["a_faire"]["a_emettre"], 0)       # novembre et décembre déjà émis, rien d'échu
        # tableau de bord de novembre
        st, t = a.req("GET", "/api/tableau-de-bord?mois=2026-11")
        self.assertEqual(st, 200, t)
        self.assertEqual(t["personnes_en_contrat"], 1)
        self.assertEqual(t["a_facturer_total_ht"], 1064042 + 45000)
        self.assertEqual(t["factures_emises"], 2)              # visite + bis (l'originale ne compte plus)
        self.assertEqual(t["facture_ht"], 45000 + 1060000)
        self.assertEqual(t["paye"], 1060000 + 190800)
        st, t = a.req("GET", "/api/tableau-de-bord?mois=2027-05")
        self.assertEqual(t["a_facturer_total_ht"], 35508)

    def test_03_verrouillage_apres_emission(self):
        a = self.admin
        st, d = a.req("GET", "/api/dossiers/%d" % self.did)
        self.assertTrue(d["verrouille"])
        st, f0 = a.req("GET", "/api/factures?dossier=%d" % self.did)
        emises0 = {x["id"]: (x["numero"], x["montant_ht"]) for x in f0["factures"] if x["numero"]}
        # v3.5.0 : la proforma reste modifiable après émission ; les factures émises ne bougent pas
        corps = da_reference()
        corps["agents"][0]["salaire_base"] = 600000
        corps["imputation"] = "IMP-02"
        st, j = a.req("PUT", "/api/dossiers/%d" % self.did, corps)
        self.assertEqual(st, 200, j)
        self.assertEqual(j["emises_gardees"], len(emises0))
        st, f1 = a.req("GET", "/api/factures?dossier=%d" % self.did)
        apres = {x["id"]: x for x in f1["factures"]}
        for fid, (num, ht) in emises0.items():
            self.assertEqual((apres[fid]["numero"], apres[fid]["montant_ht"]), (num, ht))   # inchangées
        prevues = [x for x in f1["factures"] if not x["numero"] and x["type"] == "MAD" and x["jours"] == x["jours_mois"]]
        self.assertTrue(prevues and all(x["montant_ht"] == 1146000 for x in prevues))      # 600 000 × 1,91
        # ajouter puis retirer un agent (sans facture émise) : permis
        corps2 = da_reference()
        corps2["imputation"] = "IMP-02"
        corps2["agents"].append({"nom": "AUTRE Fictif", "poste": "p", "salaire_base": 100000})
        st, j = a.req("PUT", "/api/dossiers/%d" % self.did, corps2)
        self.assertEqual(st, 200, j)
        corps3 = da_reference()
        corps3["imputation"] = "IMP-02"
        st, j = a.req("PUT", "/api/dossiers/%d" % self.did, corps3)
        self.assertEqual(st, 200, j)
        st, f3 = a.req("GET", "/api/factures?dossier=%d" % self.did)
        self.assertEqual(sorted(x["id"] for x in f3["factures"] if x["numero"]), sorted(emises0))
        st, j = a.req("POST", "/api/dossiers/%d/statut" % self.did, {"statut": "Annulé"})
        self.assertEqual(st, 409)

    def test_04_plusieurs_agents_visites_et_renouvellement(self):
        a = self.admin
        # 2 agents, 15 mois -> 2 visites chacun
        corps = {"client_id": 2, "service": "DRH", "lieu": "Libreville", "date_debut": "2027-01-01",
                 "date_fin": "2028-03-31", "agents": [
                     {"nom": "AGENT FICTIF Un", "poste": "Chauffeur", "salaire_base": 300000},
                     {"nom": "AGENT FICTIF Deux", "poste": "Magasinier", "salaire_base": 350000}]}
        st, j = a.req("POST", "/api/dossiers", corps)
        self.assertEqual(st, 200, j)
        self.assertTrue(j["numero_proforma"].startswith("350-"))
        # pas de n° de DA saisi -> n° automatique DA-AAAA-001, puis 002
        annee = serveur.api.aujourdhui().year
        self.assertEqual(j["num_da"], "DA-%d-001" % annee)
        st, ap = a.req("POST", "/api/dossiers/apercu", corps)
        self.assertEqual(ap["num_da_propose"], "DA-%d-002" % annee)
        # un n° de DA déjà utilisé est refusé
        st, k = a.req("POST", "/api/dossiers", dict(corps, num_da="DA-TEST-1"))
        self.assertEqual(st, 409, k)
        st, d = a.req("GET", "/api/dossiers/%d" % j["id"])
        # modifier sans n° de DA garde le n° automatique
        st, k = a.req("PUT", "/api/dossiers/%d" % j["id"], dict(corps, num_da=""))
        self.assertEqual(st, 200, k)
        st, d2 = a.req("GET", "/api/dossiers/%d" % j["id"])
        self.assertEqual(d2["dossier"]["num_da"], "DA-%d-001" % annee)
        self.assertEqual(d["proforma"]["nb_visites"], 4)
        self.assertEqual(d["proforma"]["visites_ht"], 180000)
        # Renouvellement du 1er agent de référence : visite faite le 02/11/2026,
        # nouveau contrat du 02/05/2027 au 01/11/2027 -> aucune visite
        ren = da_reference()
        ren.update(date_debut="2027-05-02", date_fin="2027-11-01", nom_numero="")
        st, ap = a.req("POST", "/api/dossiers/apercu", ren)
        self.assertEqual(ap["dernieres_visites"], ["2026-11-02"])
        self.assertEqual(ap["nb_visites"], 0)
        # Visite désactivée
        ren["visite_mode"] = "Non"
        ren["date_fin"] = "2028-12-31"
        st, ap = a.req("POST", "/api/dossiers/apercu", ren)
        self.assertEqual(ap["nb_visites"], 0)

    def test_06_matricule_fixe(self):
        a = self.admin
        base = {"client_id": 1, "service": "DAF", "lieu": "Moanda", "date_debut": "2028-01-01", "date_fin": "2028-02-29"}
        st, j1 = a.req("POST", "/api/dossiers", dict(base, agents=[
            {"nom": "INTERIM FICTIF Élodie", "poste": "Secrétaire", "salaire_base": 250000}]))
        self.assertEqual(st, 200, j1)
        st, d1 = a.req("GET", "/api/dossiers/%d" % j1["id"])
        m1 = d1["agents"][0]["matricule"]
        self.assertRegex(m1, r"^INT-\d{4}$")
        # nouvelle DA : même personne écrite autrement -> même matricule ; nouvelle personne -> nouveau
        corps2 = dict(base, date_debut="2028-03-01", date_fin="2028-04-30", agents=[
            {"nom": "interim  fictif elodie", "poste": "Secrétaire", "salaire_base": 260000},
            {"nom": "INTERIM FICTIF Autre", "poste": "Chauffeur", "salaire_base": 200000}])
        st, ap = a.req("POST", "/api/dossiers/apercu", corps2)
        self.assertEqual(ap["matricules"], [m1, None])
        st, j2 = a.req("POST", "/api/dossiers", corps2)
        self.assertEqual(st, 200, j2)
        st, d2 = a.req("GET", "/api/dossiers/%d" % j2["id"])
        m2 = [x["matricule"] for x in d2["agents"]]
        self.assertEqual(m2[0], m1)
        self.assertNotEqual(m2[1], m1)
        # la modification d'une DA garde les matricules
        st, k = a.req("PUT", "/api/dossiers/%d" % j2["id"], corps2)
        self.assertEqual(st, 200, k)
        st, d3 = a.req("GET", "/api/dossiers/%d" % j2["id"])
        self.assertEqual([x["matricule"] for x in d3["agents"]], m2)
        st, li = a.req("GET", "/api/interimaires")
        self.assertEqual(st, 200)
        e = [x for x in li["interimaires"] if x["matricule"] == m1][0]
        self.assertEqual(e["nb_contrats"], 2)
        self.assertNotIn("salaire_base", json.dumps(li))
        st, ld = a.req("GET", "/api/dossiers?q=" + m1.lower())
        self.assertEqual(len(ld["dossiers"]), 2)

    def test_08_ancien_interimaire(self):
        a = self.admin
        fiche = {"nom": "ANCIEN FICTIF Paul", "poste": "Magasinier", "lieu": "Moanda",
                 "hist_debut": "2025-03-01", "hist_fin": "2026-02-28", "derniere_visite": "2026-01-15"}
        st, j = a.req("POST", "/api/interimaires", fiche)
        self.assertEqual(st, 200, j)
        mat = j["matricule"]
        st, k = a.req("POST", "/api/interimaires", dict(fiche, nom="ancien fictif paul"))
        self.assertEqual(st, 409)                       # doublon refusé
        st, k = a.req("POST", "/api/interimaires", dict(fiche, hist_fin="2024-01-01"))
        self.assertEqual(st, 400)                       # fin avant début
        st, li = a.req("GET", "/api/interimaires")
        e = [x for x in li["interimaires"] if x["matricule"] == mat][0]
        self.assertEqual((e["nb_contrats"], e["poste"], e["premier_debut"], e["ancien"]), (1, "Magasinier", "2025-03-01", True))
        st, f = a.req("GET", "/api/factures")
        self.assertFalse([x for x in f["factures"] if x["agent"] == fiche["nom"]])   # aucune facture
        # nouvelle DA : même matricule, visite de janvier 2026 reprise -> pas de visite avant janvier 2027
        corps = {"client_id": 1, "service": "DAF", "lieu": "Moanda", "date_debut": "2026-12-01", "date_fin": "2027-01-10",
                 "agents": [{"nom": "Ancien Fictif PAUL", "poste": "Magasinier", "salaire_base": 300000}]}
        st, ap = a.req("POST", "/api/dossiers/apercu", corps)
        self.assertEqual((ap["matricules"], ap["dernieres_visites"], ap["nb_visites"]), ([mat], ["2026-01-15"], 0))
        # modification de la fiche
        st, k = a.req("PUT", "/api/interimaires/%d" % j["id"], dict(fiche, poste="Chef magasinier"))
        self.assertEqual(st, 200, k)

    def test_07_migration_base_existante(self):
        import sqlite3
        chemin = os.path.join(TMP, "ancienne.db")
        con = sqlite3.connect(chemin)
        con.executescript("CREATE TABLE agents (id INTEGER PRIMARY KEY, dossier_id INTEGER, rang INTEGER, nom TEXT, "
                          "poste TEXT, salaire_base INTEGER, derniere_visite TEXT);"
                          "INSERT INTO agents(dossier_id, rang, nom, poste, salaire_base) VALUES "
                          "(1,1,'ANCIEN Agent','X',1),(2,1,'Ancien  agent','X',1),(2,2,'AUTRE Agent','Y',1);")
        con.commit()
        con.close()
        serveur.db.initialiser(chemin)
        serveur.db.initialiser(chemin)      # deux lancements : rien ne doit changer
        # paramètre ajouté par une version récente : ajouté sans écraser les autres
        con = sqlite3.connect(chemin)
        con.execute("DELETE FROM parametres WHERE cle = 'code_entreprise'")
        con.execute("UPDATE parametres SET valeur = '\"BANQUE TEST\"' WHERE cle = 'banque'")
        con.commit()
        con.close()
        serveur.db.initialiser(chemin)
        con = sqlite3.connect(chemin)
        self.assertEqual(dict(con.execute("SELECT cle, valeur FROM parametres WHERE cle IN ('code_entreprise', 'banque')")),
                         {"code_entreprise": '"ANO"', "banque": '"BANQUE TEST"'})
        con.close()
        con = sqlite3.connect(chemin)
        r = con.execute("SELECT a.id, i.matricule FROM agents a JOIN interimaires i ON i.id = a.interimaire_id "
                        "ORDER BY a.id").fetchall()
        con.close()
        self.assertEqual([m for _, m in r], ["INT-0001", "INT-0001", "INT-0002"])

    def test_05_validation_entrees(self):
        a = self.admin
        mauvais = [
            dict(da_reference(), date_fin="2026-10-01"),
            dict(da_reference(), date_debut="02/11/2026"),
            dict(da_reference(), agents=[]),
            dict(da_reference(), agents=[{"nom": "X", "poste": "Y", "salaire_base": -5}]),
            dict(da_reference(), agents=[{"nom": "X", "poste": "Y", "salaire_base": "12a"}]),
            dict(da_reference(), agents=[{"nom": "X", "poste": "Y", "salaire_base": 1.5}]),
            dict(da_reference(), client_id=999),
            dict(da_reference(), service="x" * 500),
            dict(da_reference(), visite_mode="Peut-être"),
        ]
        for c in mauvais:
            st, j = a.req("POST", "/api/dossiers/apercu", c)
            self.assertEqual(st, 400, (c, j))
        st, j = a.req("POST", "/api/dossiers/apercu", brut=b"{pas du json")
        self.assertEqual(st, 400)
        st, j = a.req("POST", "/api/dossiers/apercu", brut=b"[1,2]")
        self.assertEqual(st, 400)
        st, j = a.req("POST", "/api/dossiers/%d/bc" % self.did, {"bc_numero": "49A930", "bc_montant": 1})
        self.assertEqual(st, 400)

    # ---------------------------------------------------------------- sécurité
    def test_10_sans_session(self):
        c = Client()
        for m, p in [("GET", "/api/dossiers"), ("GET", "/api/factures"), ("GET", "/api/tableau-de-bord"),
                     ("GET", "/api/utilisateurs"), ("GET", "/api/parametres")]:
            st, j = c.req(m, p)
            self.assertEqual(st, 401, p)
        st, j = c.req("POST", "/api/installation", {"identifiant": "pirate", "nom": "x", "mot_de_passe": "Unmotdepasse-long-9"})
        self.assertEqual(st, 409)

    def test_11_csrf_origine_type(self):
        a = self.admin
        sauve = a.csrf
        a.csrf = None
        st, j = a.req("POST", "/api/dossiers/apercu", da_reference())
        self.assertEqual(st, 403)
        a.csrf = "faux" * 10
        st, j = a.req("POST", "/api/dossiers/apercu", da_reference())
        self.assertEqual(st, 403)
        a.csrf = sauve
        st, j = a.req("POST", "/api/dossiers/apercu", da_reference(), entetes={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        st, j = a.req("POST", "/api/dossiers/apercu", brut=json.dumps(da_reference()).encode(),
                      entetes={"Content-Type": "text/plain"})
        self.assertEqual(st, 415)
        # Hôte étranger (DNS rebinding)
        st, j = Client(hote="evil.example:%d" % PORT).req("GET", "/api/etat")
        self.assertEqual(st, 400)

    def test_12_entetes_securite(self):
        a = self.admin
        st, _ = a.req("GET", "/")
        r = a.derniere
        self.assertEqual(st, 200)
        self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        st, _ = a.req("GET", "/static/../app/db.py")
        self.assertEqual(st, 404)
        st, _ = a.req("GET", "/donnees/ano.db")
        self.assertEqual(st, 404)

    def test_13_roles(self):
        a = self.admin
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "lola", "nom": "Lola", "role": "gestion",
                                                     "mot_de_passe": "Temporaire-Compta-1"})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "boss", "nom": "Lecteur", "role": "lecture",
                                                     "mot_de_passe": "Temporaire-Lecture-1"})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "faible", "nom": "x", "role": "gestion",
                                                     "mot_de_passe": "court"})
        self.assertEqual(st, 400)
        g = Client()
        st, j = g.connexion("lola", "Temporaire-Compta-1")
        self.assertEqual(st, 200)
        self.assertTrue(j["utilisateur"]["doit_changer_mdp"])
        st, j = g.req("GET", "/api/dossiers")
        self.assertEqual((st, j.get("code")), (403, "CHANGER_MDP"))
        st, j = g.req("POST", "/api/moi/mot-de-passe", {"actuel": "Temporaire-Compta-1", "nouveau": "Factures-du-mois-42"})
        self.assertEqual(st, 200, j)
        st, j = g.req("GET", "/api/dossiers")
        self.assertEqual(st, 200)
        st, j = g.req("GET", "/api/utilisateurs")
        self.assertEqual(st, 403)
        st, j = g.req("PUT", "/api/parametres", {"parametres": {"tva_pdm": 0}})
        self.assertEqual(st, 403)
        lec = Client()
        lec.connexion("boss", "Temporaire-Lecture-1")
        lec.req("POST", "/api/moi/mot-de-passe", {"actuel": "Temporaire-Lecture-1", "nouveau": "Tableau-de-bord-77"})
        st, j = lec.req("GET", "/api/tableau-de-bord")
        self.assertEqual(st, 200)
        st, j = lec.req("GET", "/api/dossiers")
        self.assertEqual(st, 403)       # les salaires restent invisibles
        st, j = lec.req("GET", "/api/interimaires")
        self.assertEqual(st, 403)
        st, j = lec.req("GET", "/api/factures/word?ids=1")
        self.assertEqual(st, 403)       # le cachet n'est pas remis au compte Lecture
        st, j = lec.req("POST", "/api/factures/paiement", {"ids": [1], "date": "2027-01-01"})
        self.assertEqual(st, 403)

    def test_14_blocage_apres_5_erreurs(self):
        c = Client()
        for _ in range(5):
            st, j = c.connexion("lola", "mauvais-mot-de-passe")
            self.assertEqual(st, 401)
        st, j = c.connexion("lola", "Factures-du-mois-42")
        self.assertEqual(st, 423)
        st, j = c.connexion("inconnu", "nimporte-quoi-123")
        self.assertEqual(st, 401)
        self.assertEqual(j["erreur"], "Identifiant ou mot de passe incorrect.")

    def test_15_deconnexion_et_journal(self):
        c = Client()
        st, j = c.connexion("direction", MDP_ADMIN)
        self.assertEqual(st, 200)
        st, j = c.req("POST", "/api/deconnexion", {})
        self.assertEqual(st, 200)
        st, j = c.req("GET", "/api/moi")
        self.assertEqual(st, 401)
        st, j = self.admin.req("GET", "/api/journal")
        actions = {x["action"] for x in j["journal"]}
        for a in ("installation", "connexion", "connexion_echec", "dossier_cree", "bc_saisi", "factures_emises",
                  "facture_bis", "paiement", "utilisateur_cree"):
            self.assertIn(a, actions)
        # aucun mot de passe en clair dans le journal
        self.assertNotIn("Factures-du-mois-42", json.dumps(j))

    def test_16_sauvegarde(self):
        st, j = self.admin.req("POST", "/api/sauvegarde", {})
        self.assertEqual(st, 200, j)
        self.assertTrue(os.path.exists(j["fichier"]))

    def test_17_signature_protegee(self):
        st, corps = Client().req("GET", "/api/signature")
        self.assertEqual(st, 401)
        st, corps = self.admin.req("GET", "/api/signature")
        self.assertEqual(st, 200)
        self.assertEqual(self.admin.derniere.getheader("Content-Type"), "image/png")
        lec = Client()
        lec.connexion("boss", "Tableau-de-bord-77")
        st, corps = lec.req("GET", "/api/signature")
        self.assertEqual(st, 200)       # cachet sur tous les documents, pour tout compte connecté

    def test_18_documents(self):
        import base64
        import io
        import zipfile
        a = self.admin
        did = self.did
        # copies figées des factures émises au test 02 (Word ; PDF désactivé dans ces tests)
        st, j = a.req("GET", "/api/dossiers/%d/documents" % did)
        self.assertEqual(st, 200, j)
        self.assertFalse(j["conversion_pdf"])
        fact = [d for d in j["documents"] if d["categorie"] == "Facture"]
        self.assertEqual(len(fact), 4)                  # visite, novembre, décembre, bis
        self.assertIn("FA 153 bis/12/2026", [d["facture_numero"] for d in fact])
        for d in j["documents"]:
            self.assertNotIn("fichier", d)              # le nom sur le disque reste interne
            self.assertNotIn("sha256", d)
        st, doc = a.req("GET", "/api/documents/%d" % fact[0]["id"])
        self.assertEqual(st, 200)
        self.assertIn("attachment", a.derniere.getheader("Content-Disposition"))
        self.assertIn("word/document.xml", zipfile.ZipFile(io.BytesIO(doc)).namelist())
        # fichiers rangés hors du programme, droits 600, noms aléatoires
        racine = os.path.join(TMP, "documents")
        fichiers = [os.path.join(r, f) for r, _, fs in os.walk(racine) for f in fs]
        self.assertGreaterEqual(len(fichiers), 4)
        for f in fichiers:
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)
            self.assertNotIn("FA", os.path.basename(f))
        # pièce du client : PDF accepté
        pdf = b"%PDF-1.4\n% piece fictive\n%%EOF\n"
        corps = {"categorie": "BC", "nom": "BC fictif.pdf", "contenu": "data:application/pdf;base64," + base64.b64encode(pdf).decode()}
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, corps)
        self.assertEqual(st, 200, j)
        pid = j["id"]
        st, doc = a.req("GET", "/api/documents/%d" % pid)
        self.assertEqual((st, doc), (200, pdf))
        self.assertEqual(a.derniere.getheader("Content-Type"), "application/pdf")
        # refus : format, catégorie, taille, nom avec chemin, dossier inconnu
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, dict(corps, contenu=base64.b64encode(b"<html>x</html>").decode()))
        self.assertEqual(st, 400)
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, dict(corps, categorie="Facture"))
        self.assertEqual(st, 400)                       # une pièce ne se fait pas passer pour une facture émise
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, dict(corps, contenu="pas du base64 !"))
        self.assertEqual(st, 400)
        gros = base64.b64encode(b"%PDF-" + b"0" * (8 * 1024 * 1024)).decode()
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, dict(corps, contenu=gros))
        self.assertEqual(st, 413)
        st, j = a.req("POST", "/api/dossiers/%d/pieces" % did, dict(corps, nom="../../app/serveur.py"))
        self.assertEqual(st, 200, j)
        st, l = a.req("GET", "/api/dossiers/%d/documents" % did)
        self.assertIn(".._.._app_serveur.py", [d["nom"] for d in l["documents"]])
        st, j = a.req("POST", "/api/dossiers/99999/pieces", corps)
        self.assertEqual(st, 404)
        # rôles : Gestion ajoute et télécharge mais ne retire pas ; Lecture ne voit rien
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "agent2", "nom": "Gestion pièces", "role": "gestion",
                                                     "mot_de_passe": "Temporaire-Pieces-1"})
        self.assertEqual(st, 200, j)
        g = Client()
        g.connexion("agent2", "Temporaire-Pieces-1")
        st, j = g.req("POST", "/api/moi/mot-de-passe", {"actuel": "Temporaire-Pieces-1", "nouveau": "Pieces-du-client-58"})
        self.assertEqual(st, 200, j)
        st, j = g.req("GET", "/api/documents/%d" % pid)
        self.assertEqual(st, 200)
        st, j = g.req("POST", "/api/documents/%d/retirer" % pid, {})
        self.assertEqual(st, 403)
        lec = Client()
        lec.connexion("boss", "Tableau-de-bord-77")
        for m, ch in (("GET", "/api/dossiers/%d/documents" % did), ("GET", "/api/documents/%d" % pid)):
            st, j = lec.req(m, ch)
            self.assertEqual(st, 403)
        st, j = lec.req("POST", "/api/dossiers/%d/pieces" % did, corps)
        self.assertEqual(st, 403)
        st, j = Client().req("GET", "/api/documents/%d" % pid)
        self.assertEqual(st, 401)
        # retrait par la Direction : masqué, fichier gardé ; copie de facture : jamais
        st, j = a.req("POST", "/api/documents/%d/retirer" % fact[0]["id"], {})
        self.assertEqual(st, 409)
        st, j = a.req("POST", "/api/documents/%d/retirer" % pid, {})
        self.assertEqual(st, 200, j)
        st, j = a.req("GET", "/api/documents/%d" % pid)
        self.assertEqual(st, 404)
        self.assertGreaterEqual(len([1 for r, _, fs in os.walk(racine) for f in fs]), len(fichiers) + 2)
        st, jl = a.req("GET", "/api/journal")
        actions = json.dumps(jl)
        self.assertIn("piece_ajoutee", actions)
        self.assertIn("piece_retiree", actions)
        # une ligne de base qui pointerait hors du dossier n'est jamais lue
        with self.assertRaises(FileNotFoundError):
            serveur.api.DOC.lire(os.path.join(TMP, "ano.db"), {"fichier": "../ano.db"})

    def test_19_conversion_pdf(self):
        DOC = serveur.api.DOC
        ancien = os.environ.pop("ANO_SOFFICE")
        try:
            if not DOC.soffice():
                self.skipTest("LibreOffice absent : conversion PDF non testée")
            st, j = self.admin.req("GET", "/api/factures?dossier=%d" % self.did)
            f = [x for x in j["factures"] if x["numero"]][0]
            st, docx = self.admin.req("GET", "/api/factures/word?ids=%d" % f["id"])
            pdf = DOC.en_pdf(docx)
            self.assertIsNotNone(pdf)
            self.assertTrue(pdf.startswith(b"%PDF-"))
        finally:
            os.environ["ANO_SOFFICE"] = ancien

    def test_20_retours_v350(self):
        """v3.5.0 : facture modifiable après émission, paiement plafonné au TTC,
        facture groupée (ex. 9 infirmiers), visite émise seule puis son mois = même n°."""
        import io
        import zipfile
        a = self.admin
        # --- dossier groupé : 3 agents, 2 mois pleins, une seule facture par mois
        corps = {"client_id": 1, "service": "DRH", "lieu": "Moanda (2) / Owendo (1)", "date_debut": "2027-03-01",
                 "date_fin": "2027-04-30", "visite_mode": "Non", "nom_numero": "(3) Infirmiers_IDE",
                 "facture_groupee": True, "agents": [
                     {"nom": "GROUPE Un Fictif", "poste": "IDE", "salaire_base": 674220},
                     {"nom": "GROUPE Deux Fictif", "poste": "IDE", "salaire_base": 674220},
                     {"nom": "GROUPE Trois Fictif", "poste": "IDE", "salaire_base": 674220}]}
        st, j = a.req("POST", "/api/dossiers", corps)
        self.assertEqual(st, 200, j)
        self.assertIn("-ANO-(3) INFIRMIERS_IDE/", j["numero_proforma"])
        gid = j["id"]
        st, d = a.req("GET", "/api/dossiers/%d" % gid)
        self.assertEqual(d["dossier"]["facture_groupee"], 1)
        self.assertEqual(d["proforma"]["cout_mensuel_total"], 3863281)   # 3 × 1 287 760,2 -> arrondi une fois
        st, j = a.req("POST", "/api/dossiers/%d/bc" % gid, {"bc_numero": "700001", "bc_montant": d["proforma"]["cumul_ht"]})
        st, j = a.req("POST", "/api/dossiers/%d/generer-factures" % gid, {})
        self.assertEqual((st, j["total"]), (200, 2), j)
        st, f = a.req("GET", "/api/factures?dossier=%d" % gid)
        fs = f["factures"]
        self.assertEqual([x["montant_ht"] for x in fs], [3863281, 3863281])
        self.assertEqual(fs[0]["agent"], "GROUPE_GROUPE_GROUPE")
        self.assertEqual((fs[0]["groupe"], fs[0]["nb_agents"]), (1, 3))
        # le salaire est visible dans la liste des dossiers (direction / gestion)
        st, l = a.req("GET", "/api/dossiers")
        self.assertEqual([x for x in l["dossiers"] if x["id"] == gid][0]["salaires"], [674220] * 3)
        # --- émission : n° au format réel, 03 = mois d'émission
        st, pa = a.req("GET", "/api/parametres")
        n0 = pa["parametres"]["dernier_num_facture"]
        st, j = a.req("POST", "/api/factures/emettre", {"ids": [fs[0]["id"]], "date_facture": "2027-03-31"})
        self.assertEqual(j["emises"], 1, j)
        st, f = a.req("GET", "/api/factures?ids=%d" % fs[0]["id"])
        fa = f["factures"][0]
        self.assertEqual(fa["numero"], "FA %d/03/2027" % (n0 + 1))
        st, doc = a.req("GET", "/api/factures/word?ids=%d" % fa["id"])
        xml = zipfile.ZipFile(io.BytesIO(doc)).read("word/document.xml").decode()
        self.assertIn("MAD de 3 IDE", xml)
        self.assertIn(">Mois<", xml)
        # --- modifier la facture émise : n° gardé, TVA recalculée, unité changée, copie gardée
        st, docs0 = a.req("GET", "/api/dossiers/%d/documents" % gid)
        st, j = a.req("PUT", "/api/factures/%d" % fa["id"], {"montant_ht": 3800000, "unite": "Forfait", "jours": 31,
                                                              "date_facture": "2027-04-02"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["ttc"], 3800000 + 684000)
        st, f = a.req("GET", "/api/factures?ids=%d" % fa["id"])
        fm = f["factures"][0]
        self.assertEqual((fm["numero"], fm["montant_ht"], fm["tva"], fm["unite"], fm["date_facture"]),
                         (fa["numero"], 3800000, 684000, "Forfait", "2027-04-02"))
        self.assertEqual(fm["echeance"], "2027-05-31")
        st, docs1 = a.req("GET", "/api/dossiers/%d/documents" % gid)
        self.assertEqual(len(docs1["documents"]), len(docs0["documents"]) + 1)
        st, doc = a.req("GET", "/api/factures/word?ids=%d" % fa["id"])
        xml = zipfile.ZipFile(io.BytesIO(doc)).read("word/document.xml").decode()
        self.assertIn(">Forfait<", xml)
        self.assertIn("3.800.000", xml)
        st, jr = a.req("GET", "/api/journal")
        self.assertIn("facture_modifiee", {x["action"] for x in jr["journal"]})
        # une facture prévue corrigée à la main n'est plus écrasée par « Mettre à jour les factures »
        st, j = a.req("PUT", "/api/factures/%d" % fs[1]["id"], {"montant_ht": 123})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/dossiers/%d/generer-factures" % gid, {})
        st, f = a.req("GET", "/api/factures?ids=%d" % fs[1]["id"])
        self.assertEqual(f["factures"][0]["montant_ht"], 123)
        # --- paiement plus grand que le TTC : permis, signalé au tableau de bord, reste jamais négatif
        st, j = a.req("POST", "/api/factures/paiement", {"ids": [fa["id"]], "date": "2027-05-10", "montant": 5000000})
        self.assertEqual(j["modifiees"], 1, j)
        st, j = a.req("PUT", "/api/factures/%d" % fa["id"], {"montant_ht": 1})
        self.assertEqual(st, 409)                       # payée : annuler le paiement d'abord
        st, t = a.req("GET", "/api/tableau-de-bord?mois=2027-03")
        self.assertGreaterEqual(t["reste_a_encaisser"], 0)
        self.assertEqual([x["numero"] for x in t["trop_percus"]], [fa["numero"]])
        mars = [x for x in t["serie"] if x["mois"] == "2027-03-01"][0]
        self.assertEqual((mars["facture_ttc"], mars["paye"]), (3800000 + 684000, 5000000))
        # --- visite médicale seule : n° à elle (FA N/Visite médicale/AAAA)
        corps = {"client_id": 1, "service": "DAF", "lieu": "Moanda", "date_debut": "2027-06-01", "date_fin": "2027-07-31",
                 "visite_mode": "Auto", "agents": [{"nom": "VISITE Seule Fictive", "poste": "p", "salaire_base": 200000}]}
        st, j = a.req("POST", "/api/dossiers", corps)
        vid = j["id"]
        a.req("POST", "/api/dossiers/%d/generer-factures" % vid, {"forcer": True})
        st, f = a.req("GET", "/api/factures?dossier=%d" % vid)
        vis = [x for x in f["factures"] if x["type"] == "VISITE"][0]
        mad = [x for x in f["factures"] if x["type"] == "MAD"][0]
        st, j = a.req("POST", "/api/factures/emettre", {"ids": [vis["id"]], "date_facture": "2027-06-05"})
        st, j = a.req("POST", "/api/factures/emettre", {"ids": [mad["id"]], "date_facture": "2027-06-06"})
        st, f = a.req("GET", "/api/factures?ids=%d,%d" % (vis["id"], mad["id"]))
        nums = sorted(x["numero"] for x in f["factures"])
        # émise après sa visite, la facture du même mois reprend le n° de la visite (lié à l'agent)
        self.assertEqual(nums, sorted(["FA %d/Visite médicale/2027" % (n0 + 2), "FA %d/06/2027" % (n0 + 2)]))

    def test_21_recherche(self):
        """Recherche globale : plusieurs mots, accents, n° avec espaces, filtres, rôles."""
        a = self.admin
        st, j = a.req("GET", "/api/recherche?q=")
        self.assertEqual((st, j["total"]), (200, 0))                 # rien à chercher
        st, j = a.req("GET", "/api/recherche?q=testeur%20r%C3%A9f%C3%A9rence")
        self.assertEqual(st, 200, j)
        types = {r["type"] for r in j["resultats"]}
        self.assertIn("dossier", types)
        self.assertIn("facture", types)
        self.assertIn("interimaire", types)
        self.assertTrue(all("salaire" not in r and "576300" not in str(r) for r in j["resultats"]))
        st, j = a.req("GET", "/api/recherche?q=testeur&type=facture")
        self.assertTrue(j["resultats"] and all(r["type"] == "facture" for r in j["resultats"]))
        num = [r for r in j["resultats"] if r["titre"].startswith("FA ")][0]["titre"]
        st, j = a.req("GET", "/api/recherche?q=" + urllib.parse.quote(num, safe=""))
        self.assertEqual(j["resultats"][0]["titre"], num)            # le n° exact arrive en tête
        st, j = a.req("GET", "/api/recherche?type=facture&statut=Pay%C3%A9e&min=1&max=999999999")
        self.assertTrue(all(r["statut"] == "Payée" for r in j["resultats"]))
        st, j = a.req("GET", "/api/recherche?q=testeur&du=2040-01-01")
        self.assertEqual(j["total"], 0)
        st, j = a.req("GET", "/api/recherche?type=pirate")
        self.assertEqual(st, 400)
        st, j = a.req("GET", "/api/recherche?q=x&min=abc")
        self.assertEqual(st, 400)
        # rôle Lecture : factures seulement
        l = Client()
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "lecteur-rech", "nom": "L", "role": "lecture",
                                                     "mot_de_passe": "Temporaire-Lecture-77"})
        l.connexion("lecteur-rech", "Temporaire-Lecture-77")
        l.req("POST", "/api/moi/mot-de-passe", {"actuel": "Temporaire-Lecture-77", "nouveau": "Lecture-Recherche-2027!"})
        st, j = l.req("GET", "/api/recherche?q=testeur")
        self.assertEqual(st, 200, j)
        self.assertTrue(j["resultats"] and {r["type"] for r in j["resultats"]} == {"facture"})
        st, j = l.req("GET", "/api/recherche?q=testeur&type=document")
        self.assertEqual(j["total"], 0)

    def test_22_numero_lie_a_l_agent(self):
        """Un n° de facture émis reste lié à son agent (Luc, 25/11/2026) : visite émise seule,
        puis le mois suivant, puis le mois de la visite -> il reprend le n° de la visite.
        Modifier la DA (ordre des agents, dates) ne change ni le n° ni l'agent d'une facture émise."""
        a = self.admin
        corps = {"client_id": 1, "service": "DAF", "lieu": "Moanda", "date_debut": "2028-11-01", "date_fin": "2029-01-31",
                 "visite_mode": "Auto", "agents": [
                     {"nom": "PREMIER Agent Fictif", "poste": "p", "salaire_base": 600000},
                     {"nom": "SECOND Agent Fictif", "poste": "p", "salaire_base": 600000}]}
        st, j = a.req("POST", "/api/dossiers", corps)
        self.assertEqual(st, 200, j)
        did = j["id"]
        a.req("POST", "/api/dossiers/%d/generer-factures" % did, {"forcer": True})
        fs = a.req("GET", "/api/factures?dossier=%d" % did)[1]["factures"]
        def f_(agent, type_, mois):
            return [x for x in fs if x["agent"].startswith(agent) and x["type"] == type_ and x["mois"].startswith(mois)][0]
        vis, nov, dec = f_("PREMIER", "VISITE", "2028-11"), f_("PREMIER", "MAD", "2028-11"), f_("PREMIER", "MAD", "2028-12")
        n0 = a.req("GET", "/api/parametres")[1]["parametres"]["dernier_num_facture"]
        a.req("POST", "/api/factures/emettre", {"ids": [vis["id"]], "date_facture": "2028-11-25"})
        a.req("POST", "/api/factures/emettre", {"ids": [dec["id"]], "date_facture": "2028-11-26"})
        a.req("POST", "/api/factures/emettre", {"ids": [nov["id"]], "date_facture": "2028-12-01"})
        par = {x["id"]: x for x in a.req("GET", "/api/factures?dossier=%d" % did)[1]["factures"]}
        self.assertEqual(par[vis["id"]]["numero"], "FA %d/Visite médicale/2028" % (n0 + 1))
        self.assertEqual(par[dec["id"]]["numero"], "FA %d/11/2028" % (n0 + 2))
        self.assertEqual(par[nov["id"]]["numero"], "FA %d/12/2028" % (n0 + 1))     # reprend le n° de la visite
        self.assertEqual(a.req("GET", "/api/parametres")[1]["parametres"]["dernier_num_facture"], n0 + 2)
        # DA modifiée : agents inversés, dates prolongées -> les factures émises gardent n° et agent
        corps2 = dict(corps, date_fin="2029-03-31", agents=list(reversed(corps["agents"])))
        st, j = a.req("PUT", "/api/dossiers/%d" % did, corps2)
        self.assertEqual(st, 200, j)
        a.req("POST", "/api/dossiers/%d/generer-factures" % did, {"forcer": True})
        apres = {x["id"]: x for x in a.req("GET", "/api/factures?dossier=%d" % did)[1]["factures"]}
        for fid in (vis["id"], nov["id"], dec["id"]):
            self.assertEqual((apres[fid]["numero"], apres[fid]["agent"], apres[fid]["montant_ht"]),
                             (par[fid]["numero"], par[fid]["agent"], par[fid]["montant_ht"]))
        self.assertTrue(apres[vis["id"]]["agent"].startswith("PREMIER"))
        # accents / majuscules corrigés : même agent, permis
        corps3 = dict(corps2, agents=[dict(corps["agents"][1]), dict(corps["agents"][0], nom="Premier Agent FICTIF")])
        st, j = a.req("PUT", "/api/dossiers/%d" % did, corps3)
        self.assertEqual(st, 200, j)
        # remplacer l'agent qui a des factures émises par une autre personne : refusé
        corps4 = dict(corps2, agents=[dict(corps["agents"][1]), dict(corps["agents"][0], nom="AUTRE Personne Fictive")])
        st, j = a.req("PUT", "/api/dossiers/%d" % did, corps4)
        self.assertEqual(st, 409, j)
        self.assertIn("FA %d/" % (n0 + 1), j["erreur"])
        # le second agent (sans facture émise) peut être retiré
        corps5 = dict(corps2, agents=[dict(corps["agents"][0])])
        st, j = a.req("PUT", "/api/dossiers/%d" % did, corps5)
        self.assertEqual(st, 200, j)
        fin = {x["id"]: x for x in a.req("GET", "/api/factures?dossier=%d" % did)[1]["factures"]}
        self.assertTrue(all(x["agent"].startswith("PREMIER") or x["agent"].startswith("Premier") for x in fin.values()))
        self.assertEqual(fin[nov["id"]]["numero"], par[nov["id"]]["numero"])

    def test_23_mention_designation(self):
        """« ANO SERVICE » sous la 1re ligne de la désignation (comme les factures d'ANO), réglable."""
        import io
        import zipfile
        a = self.admin
        fa = [x for x in a.req("GET", "/api/factures")[1]["factures"] if x["numero"] and x["type"] == "MAD"][0]
        def texte_word():
            st, doc = a.req("GET", "/api/factures/word?ids=%d" % fa["id"])
            self.assertEqual(st, 200)
            z = zipfile.ZipFile(io.BytesIO(doc))
            nom = [n for n in z.namelist() if n.endswith(".docx")]
            if nom:
                z = zipfile.ZipFile(io.BytesIO(z.read(nom[0])))
            return re.sub(r"<[^>]+>", "|", z.read("word/document.xml").decode())
        p = a.req("GET", "/api/parametres")[1]["parametres"]
        self.assertEqual(p["mention_designation"], "ANO SERVICE")     # rempli d'office pour ANO Services
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"mention_designation": ""}})
        self.assertEqual(st, 200, j)
        self.assertIn("|" + p["raison_sociale"].upper() + "|", texte_word())   # vide : raison sociale en majuscules
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"mention_designation": "ANO SERVICE"}})
        self.assertEqual(st, 200, j)
        t = texte_word()
        self.assertIn("|ANO SERVICE|", t)
        self.assertLess(t.index("MAD d"), t.index("ANO SERVICE|"))
        self.assertLess(t.index("ANO SERVICE|"), t.index(fa["agent"]))

    def test_24_mise_en_conformite_donnees_existantes(self):
        """Base d'avant : « ANO SERVICE » ajouté une fois, aucun n° émis ni montant modifié, relançable."""
        import glob
        import sqlite3
        chemins = [c for c in glob.glob(os.path.join(TMP, "**", "*.db"), recursive=True)
                   if os.path.basename(c) != "plateforme.db" and "ancienne" not in c]
        chemin = max(chemins, key=os.path.getsize)
        def etat():
            con = sqlite3.connect(chemin)
            try:
                return con.execute("SELECT * "
                                   "FROM factures ORDER BY id").fetchall()
            finally:
                con.close()
        avant = etat()
        self.assertTrue([f for f in avant if f[1]])                   # il y a bien des n° émis
        con = sqlite3.connect(chemin)
        con.execute("DELETE FROM parametres WHERE cle IN ('maj_mention_20261125', 'mention_designation')")
        con.commit()
        con.close()
        serveur.db.initialiser(chemin)
        serveur.db.initialiser(chemin)
        self.assertEqual(etat(), avant)
        self.assertEqual(self.admin.req("GET", "/api/parametres")[1]["parametres"]["mention_designation"], "ANO SERVICE")
        # une entreprise qui a vidé ou changé le champ ensuite n'est plus touchée
        self.admin.req("PUT", "/api/parametres", {"parametres": {"mention_designation": ""}})
        serveur.db.initialiser(chemin)
        self.assertEqual(self.admin.req("GET", "/api/parametres")[1]["parametres"]["mention_designation"], "")
        self.admin.req("PUT", "/api/parametres", {"parametres": {"mention_designation": "ANO SERVICE"}})

    def test_25_heures_supplementaires(self):
        """Relevé -> fiche -> classement -> Proforma H -> FA H (circuit de Lola), n° à part, montant du devis par défaut."""
        import base64
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
        import metier as M
        a = self.admin
        dos = [x for x in a.req("GET", "/api/dossiers")[1]["dossiers"] if x["statut"] != "Annulé"][0]
        st, d = a.req("GET", "/api/dossiers/%d" % dos["id"])
        ag = d["agents"][0]
        st, j = a.req("POST", "/api/dossiers/%d/heures-sup" % dos["id"], {"agent_id": 999999})
        self.assertEqual(st, 400)
        st, j = a.req("POST", "/api/dossiers/%d/heures-sup" % dos["id"], {"agent_id": ag["id"], "direction": "DRHST"})
        self.assertEqual(st, 200, j)
        hid = j["id"]
        pdf = b"%PDF-1.4\n% releve fictif\n%%EOF\n"
        st, j = a.req("POST", "/api/heures-sup/%d/releve" % hid, {"nom": "releve.pdf", "contenu": base64.b64encode(pdf).decode()})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/heures-sup/%d/devis" % hid, {})
        self.assertEqual(st, 400)                                     # pas encore d'heures
        lignes = [{"date": "2026-10-12", "debut": "15:00", "fin": "21:00", "justification": "Bilans des urgences"},
                  {"date": "2026-10-13", "debut": "15:00", "fin": "19:00", "heures": "4"},
                  {"date": "2026-10-18", "debut": "08:00", "fin": "12:00", "heures": 4},
                  {"date": "2026-10-19", "debut": "22:00", "fin": "02:00", "heures": "4 H"}]
        corps = {"direction": "DRHST", "service": "Laboratoire", "section": "1256", "matricule_client": "MAD",
                 "categorie": "C08A", "lignes": lignes, "heures": None}
        st, j = a.req("PUT", "/api/heures-sup/%d" % hid, corps)
        self.assertEqual(st, 200, j)
        h = j["heures_sup"]
        self.assertEqual(h["total_heures"], 18)
        self.assertEqual(h["lignes"][0]["heures"], 6)                 # calculée depuis début / fin
        self.assertEqual(h["heures"], {"h1": 12, "h2": 2, "h3": 4})   # proposition : 8 h/semaine, reste, dimanche
        self.assertEqual([(w["du"], w["total"]) for w in h["semaines"]], [("2026-10-12", 14), ("2026-10-19", 4)])
        # jours fériés réglables (avec leur nom) : un férié passe au taux des dimanches
        p0 = a.req("GET", "/api/parametres")[1]["parametres"]["hs_jours_feries"]
        self.assertIn("08-17 Fête de l'indépendance", p0)
        self.assertEqual(a.req("PUT", "/api/parametres", {"parametres": {"hs_jours_feries": ["13-45 Faux"]}})[0], 400)
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"hs_jours_feries": ["2026-10-13  Férié  fictif", "01-01"]}})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["parametres"]["hs_jours_feries"], ["01-01", "2026-10-13 Férié fictif"])
        hf = a.req("GET", "/api/heures-sup/%d" % hid)[1]["heures_sup"]
        self.assertEqual(hf["heures"], {"h1": 10, "h2": 0, "h3": 8})
        self.assertTrue([x for x in hf["semaines"][0]["jours"] if x["date"] == "2026-10-13"][0]["repos"])
        # férié « à confirmer » (Aïd, Tabaski) : pas appliqué, le devis attend la confirmation
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"hs_jours_feries": ["2026-10-13 Aïd fictif (à confirmer)"]}})
        self.assertEqual(st, 200, j)
        hf = a.req("GET", "/api/heures-sup/%d" % hid)[1]["heures_sup"]
        self.assertEqual(hf["feries_a_confirmer"], [{"date": "2026-10-13", "libelle": "Aïd fictif"}])
        self.assertEqual(hf["proposition"], {"h1": 12, "h2": 2, "h3": 4})          # pas encore appliqué
        st, j = a.req("POST", "/api/heures-sup/%d/devis" % hid, {"date": "2026-10-21"})
        self.assertEqual((st, j.get("code")), (409, "FERIE_A_CONFIRMER"))
        st, j = a.req("POST", "/api/feries/confirmer", {"jour": "2026-10-13", "ferie": True})
        self.assertEqual(j["hs_jours_feries"], ["2026-10-13 Aïd fictif"])
        hf = a.req("GET", "/api/heures-sup/%d" % hid)[1]["heures_sup"]
        self.assertEqual((hf["feries_a_confirmer"], hf["proposition"]["h3"]), ([], 8))
        a.req("PUT", "/api/parametres", {"parametres": {"hs_jours_feries": ["2026-10-13 Aïd fictif (à confirmer)"]}})
        st, j = a.req("POST", "/api/feries/confirmer", {"jour": "2026-10-13", "ferie": False})
        self.assertEqual(j["hs_jours_feries"], [])                                 # pas férié : retiré
        a.req("PUT", "/api/parametres", {"parametres": {"hs_jours_feries": p0}})
        self.assertIn("08-30 Journée nationale de la Libération", p0)
        self.assertIn("2027-05-16 Aïd el-Kébir / Tabaski (à confirmer)", p0)
        # signatures de l'agent à chaque étape, scan signé joint ; fiche en Word, archivée, envoyée
        pdf2 = b"%PDF-1.4\n% fiche signee fictive\n%%EOF\n"
        st, j = a.req("POST", "/api/heures-sup/%d/etape" % hid, {"etape": "avant", "date": "2026-10-10", "nom": "avant.pdf",
                                                                 "contenu": base64.b64encode(pdf2).decode()})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["heures_sup"]["etapes"]["avant"]["date"], "2026-10-10")
        self.assertTrue(any(d["nom"].startswith("Fiche signée (avant)") for d in j["heures_sup"]["releves"]))
        self.assertEqual(a.req("POST", "/api/heures-sup/%d/etape" % hid, {"etape": "pendant", "date": "2026-10-10"})[0], 400)
        st, doc = a.req("GET", "/api/heures-sup/%d/fiche.docx" % hid)
        self.assertEqual((st, doc[:2]), (200, b"PK"))
        import io
        import zipfile
        xml = zipfile.ZipFile(io.BytesIO(doc)).read("word/document.xml").decode()
        for mot in ("Fiche d'attachement", "Avant :  signé le 10/10/2026", "Après :", "Payées :", "Récupérées :", "Bilans des urgences"):
            self.assertIn(mot, xml)
        st, j = a.req("POST", "/api/heures-sup/%d/fiche-archiver" % hid, {})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/heures-sup/%d/suivi" % hid, {"fiche_envoyee_le": "2026-10-20"})
        self.assertEqual((st, j["heures_sup"]["fiche_envoyee_le"]), (200, "2026-10-20"))
        self.assertTrue(any(d["nom"].startswith("Fiche d'attachement") for d in j["heures_sup"]["releves"]))
        self.assertEqual(len(h["releves"]), 1)
        cout = h["cout_mensuel"]
        self.assertEqual(cout, d["proforma"]["agents"][0]["cout_mensuel"])
        # classement à la main
        st, j = a.req("PUT", "/api/heures-sup/%d" % hid, dict(corps, heures={"h1": 7, "h2": "7,5", "h3": 3.5}))
        self.assertEqual(st, 200, j)
        h = j["heures_sup"]
        attendu = M.hs_lignes_montants(cout, [7, 7.5, 3.5], [2800, 5600, 7500])["total"]
        self.assertEqual(h["calcul"]["total"], attendu)
        self.assertEqual(h["ecart_heures"], 0)
        # dernier n° pas renseigné : refus clair
        st, j = a.req("POST", "/api/heures-sup/%d/devis" % hid, {"date": "2026-10-21"})
        self.assertEqual((st, j.get("code")), (409, "NUM_DERNIER_NUM_PROFORMA_H"), j)
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"dernier_num_proforma_h": "123", "dernier_num_facture_h": 109}})
        self.assertEqual(st, 200, j)
        st, j = a.req("POST", "/api/heures-sup/%d/devis" % hid, {"date": "2026-10-21"})
        self.assertEqual(st, 200, j)
        self.assertEqual(j["heures_sup"]["devis_numero"], "124-10-ANO-MAD/2026")
        st, j = a.req("POST", "/api/heures-sup/%d/devis" % hid, {"date": "2026-10-22"})
        self.assertEqual(j["heures_sup"]["devis_numero"], "124-10-ANO-MAD/2026")   # n° gardé
        self.assertEqual(a.req("GET", "/api/parametres")[1]["parametres"]["dernier_num_proforma_h"], 124)
        st, j = a.req("POST", "/api/heures-sup/%d/supprimer" % hid, {})
        self.assertEqual(st, 409)
        # facture FA H : montant du devis par défaut, TVA 18 %
        st, j = a.req("POST", "/api/heures-sup/%d/facture" % hid, {"date_facture": "2026-11-07", "bc_numero": "493349"})
        self.assertEqual(st, 200, j)
        f = j["heures_sup"]
        self.assertEqual(f["facture_numero"], "FA H 110/11/2026")
        self.assertEqual((f["montant_ht"], f["tva"], f["ttc"]), (attendu, M.tva(attendu, 1800), attendu + M.tva(attendu, 1800)))
        self.assertEqual(f["statut"], "Facturée")
        st, j = a.req("PUT", "/api/heures-sup/%d" % hid, corps)
        self.assertEqual(st, 409)                                     # figé après émission
        st, j = a.req("POST", "/api/heures-sup/%d/facture" % hid, {})
        self.assertEqual(st, 409)
        st, j = a.req("POST", "/api/heures-sup/%d/suivi" % hid, {"envoyee_le": "2026-11-08", "paye_le": "2026-12-20", "reference": "VIR 1"})
        self.assertEqual((st, j["heures_sup"]["statut"], j["heures_sup"]["montant_paye"]), (200, "Payée", f["ttc"]))
        # 2e relevé : montant saisi (BC différent), n° suivants ; le dossier les liste
        st, j = a.req("POST", "/api/dossiers/%d/heures-sup" % dos["id"], {"agent_id": ag["id"], "lignes": lignes[:1]})
        h2 = j["id"]
        a.req("POST", "/api/heures-sup/%d/devis" % h2, {"date": "2026-11-02"})
        st, j = a.req("POST", "/api/heures-sup/%d/facture" % h2, {"date_facture": "2026-11-30", "montant_ht": 50000})
        self.assertEqual((j["heures_sup"]["facture_numero"], j["heures_sup"]["montant_ht"]), ("FA H 111/11/2026", 50000), j)
        self.assertEqual(j["heures_sup"]["devis_numero"], "125-11-ANO-MAD/2026")
        st, d2 = a.req("GET", "/api/dossiers/%d" % dos["id"])
        self.assertEqual(len(d2["heures_sup"]), 2)
        self.assertNotIn("FA H", "".join(x["numero"] or "" for x in d2["factures"]))   # séries séparées
        # les FA H suivent les autres factures : page Factures, statut (payée / à envoyer), export, recherche
        st, lf = a.req("GET", "/api/factures?mois=2026-11")
        fh = {x["numero"]: x for x in lf["factures_hs"]}
        self.assertEqual(set(fh), {"FA H 110/11/2026", "FA H 111/11/2026"})
        self.assertEqual((fh["FA H 110/11/2026"]["statut"], fh["FA H 111/11/2026"]["statut"]), ("Payée", "À envoyer"))
        st, lf = a.req("GET", "/api/factures?statut=" + urllib.parse.quote("À envoyer"))
        self.assertEqual([x["numero"] for x in lf["factures_hs"]], ["FA H 111/11/2026"])
        self.assertEqual(a.req("GET", "/api/factures?mois=2026-10")[1]["factures_hs"], [])
        st, csv = a.req("GET", "/api/factures/export.csv?mois=2026-11")
        self.assertIn("FA H 111/11/2026;", csv.decode("utf-8"))
        self.assertIn("Heures supplémentaires", csv.decode("utf-8"))
        st, rq = a.req("GET", "/api/recherche?q=" + urllib.parse.quote("FA H 111"))
        self.assertEqual([(x["titre"], x["lien"]) for x in rq["resultats"]], [("FA H 111/11/2026", "#/hs/%d" % h2)])
        # lignes invalides
        for mauvais in ([{"date": "2026-10-12"}], [{"date": "2026-10-12", "heures": "30"}], [{"date": "x", "heures": 2}],
                        [{"date": "2026-10-12", "debut": "25:00", "fin": "26:00"}]):
            st, j = a.req("POST", "/api/dossiers/%d/heures-sup" % dos["id"], {"agent_id": ag["id"], "lignes": mauvais})
            self.assertEqual(st, 400, (mauvais, j))

    def test_99_parametres_entreprise(self):
        """V1 B2B : codes de n°, TVA visite et images réglables ; ANO inchangé par défaut."""
        a = self.admin
        st, p = a.req("GET", "/api/parametres")
        d = p["parametres"]
        self.assertEqual((d["code_entreprise"], d["prefixe_facture"], d["code_mad"], d["tva_visite"], d["bc_chiffres"]),
                         ("ANO", "FA", "", False, 6))
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"code_mad": "A/B"}})
        self.assertEqual(st, 400)                       # « / » interdit dans un code
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"code_entreprise": "  "}})
        self.assertEqual(st, 400)
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"tva_visite": "oui"}})
        self.assertEqual(st, 400)
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"code_entreprise": "xyz", "tva_visite": True}})
        self.assertEqual(st, 200, j)
        st, ap = a.req("POST", "/api/dossiers/apercu", da_reference())
        self.assertIn("-XYZ-", ap["numero_propose"])
        self.assertEqual(ap["cumul_ht"], 6648214)       # calcul inchangé
        self.assertEqual(serveur.api._tva_ligne("VISITE", 45000, {"tva_pdm": 1800, "tva_visite": True}), 8100)
        self.assertEqual(serveur.api._tva_ligne("VISITE", 45000, {"tva_pdm": 1800}), 0)     # anciens dossiers
        st, j = a.req("PUT", "/api/parametres", {"parametres": {"code_entreprise": "ANO", "tva_visite": False}})
        self.assertEqual(st, 200)
        # logo / cachet : direction seulement, PNG seulement, rangé dans un dossier de test
        prive = os.environ["ANO_PRIVE"]
        try:
            import base64
            st, j = a.req("PUT", "/api/images/logo", {"png": base64.b64encode(b"GIF89a....").decode()})
            self.assertEqual(st, 400)
            st, j = a.req("PUT", "/api/images/logo", {"png": "pas du base64 !"})
            self.assertEqual(st, 400)
            png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
            st, j = a.req("PUT", "/api/images/signature", {"png": "data:image/png;base64," + base64.b64encode(png).decode()})
            self.assertEqual(st, 200, j)
            with open(os.path.join(prive, "signature.png"), "rb") as f:
                self.assertEqual(f.read(), png)
            st, j = a.req("PUT", "/api/images/autre", {"png": ""})
            self.assertEqual(st, 404)
        finally:
            with open(os.path.join(prive, "signature.png"), "wb") as f:
                f.write(png_test())
        st, j = Client().req("PUT", "/api/images/logo", {"png": ""})
        self.assertEqual(st, 401)                       # sans connexion
        a.req("POST", "/api/utilisateurs", {"identifiant": "gestion99", "nom": "G", "role": "gestion",
                                             "mot_de_passe": "Temporaire-Gestion-9"})
        g = Client()
        g.connexion("gestion99", "Temporaire-Gestion-9")
        g.req("POST", "/api/moi/mot-de-passe", {"actuel": "Temporaire-Gestion-9", "nouveau": "Gestion-des-images-9"})
        st, j = g.req("PUT", "/api/images/logo", {"png": ""})
        self.assertEqual(st, 403)                       # gestion : refusé


if __name__ == "__main__":
    unittest.main(verbosity=2)
