"""Jeu de données FICTIVES pour le site de test (et les essais en local).

Aucun vrai nom, aucun vrai salaire : noms inventés suivis de « Fictif/Fictive »,
salaires ronds ou inventés. Couvre les cas réels rencontrés chez ANO :
  1. agent seul sur 6 mois, visite médicale, factures émises et envoyées ;
  2. groupe de 9 infirmiers, une seule facture par mois, payée / trop-perçu / impayée ;
  3. prolongation du groupe (visite pas refacturée, < 1 an), proforma seule ;
  4. départ en milieu de mois (prorata), facture « bis » après PV, facture corrigée à la main ;
  5. deux agents sur 15 mois : visite refacturée à l'anniversaire ;
  6. une DA annulée.
Tout passe par l'API (mêmes contrôles que l'écran).

  python3 outils/donnees_fictives.py https://dev.exemple.com <entreprise> <identifiant>
  (mot de passe lu sur l'entrée standard)
"""
import base64
import calendar
import http.client
import json
import sys
import urllib.parse

AUJ = "2026-11-25"


class Client:
    """Petit client HTTP(S) : cookie de session et jeton CSRF gérés à la main
    (le cookie « Secure » doit aussi passer vers 127.0.0.1 en HTTP)."""

    def __init__(self, url, hote=None):
        u = urllib.parse.urlsplit(url)
        self.https = u.scheme == "https"
        self.adresse = u.netloc
        self.hote = hote or u.netloc
        self.origine = "%s://%s" % (u.scheme, self.hote)
        self.cookie = None
        self.csrf = None

    def req(self, methode, chemin, corps=None):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        c = cls(self.adresse, timeout=60)
        h = {"Host": self.hote, "Origin": self.origine}
        if self.cookie:
            h["Cookie"] = self.cookie
        if self.csrf and methode != "GET":
            h["X-CSRF-Token"] = self.csrf
        data = None
        if corps is not None:
            data = json.dumps(corps).encode()
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=data, headers=h)
        r = c.getresponse()
        txt = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            v = sc.split(";")[0]
            self.cookie = v if v.split("=", 1)[1] else None
        c.close()
        try:
            return r.status, json.loads(txt)
        except ValueError:
            return r.status, txt

    def ok(self, methode, chemin, corps=None):
        st, j = self.req(methode, chemin, corps)
        if st != 200:
            raise RuntimeError("%s %s -> %s %s" % (methode, chemin, st, j))
        return j

    def connexion(self, entreprise, identifiant, mdp):
        j = self.ok("POST", "/api/connexion", {"entreprise": entreprise, "identifiant": identifiant, "mot_de_passe": mdp})
        self.csrf = j["csrf"]
        return j


def _pdf_fictif(titre):
    """PDF d'une page, généré ici (pièce jointe d'exemple)."""
    t = titre.replace("(", "").replace(")", "")
    flux = ("BT /F1 18 Tf 72 720 Td (%s) Tj ET" % t).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(flux) + flux + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, pos = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % p for p in pos)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return out


INFIRMIERS = ["NDONG", "MBOUMBA", "OBAME", "MOUSSAVOU", "NZIENGUI", "BOUSSOUGOU", "KOUMBA", "MAKAYA", "IVANGA"]


def remplir(c):
    """Remplit l'entreprise connectée. Renvoie un résumé (ids utiles aux tests)."""
    if c.ok("GET", "/api/dossiers")["dossiers"]:
        return {"deja_rempli": True}
    c.ok("PUT", "/api/parametres", {"parametres": {
        "raison_sociale": "ESSAI INTÉRIM (fictif)", "adresse": "BP 0000", "ville": "Moanda", "telephone": "+241 00 00 00 00",
        "email": "contact@exemple.invalid", "rccm": "RCCM-FICTIF-0001", "nif": "000000 X", "cnss": "CNSS-FICTIF",
        "banque": "Banque Fictive du Gabon", "compte": "00000 00000 00000000000 00",
        "mention_designation": "ANO SERVICE", "dernier_num_proforma": 100, "dernier_num_facture": 50}})
    c.ok("POST", "/api/clients", {"nom": "MINES DU SUD SA (fictif)", "adresse": "BP 1", "ville": "Moanda", "contact": "Service Achats"})
    c.ok("POST", "/api/clients", {"nom": "PORT OCÉAN SA (fictif)", "adresse": "BP 2", "ville": "Libreville", "contact": "DRH"})
    cl = {x["nom"]: x["id"] for x in c.ok("GET", "/api/clients")["clients"]}
    mines, port = cl["MINES DU SUD SA (fictif)"], cl["PORT OCÉAN SA (fictif)"]
    r = {}

    def dossier(corps, bc=None):
        did = c.ok("POST", "/api/dossiers", corps)["id"]
        if bc:
            cumul = c.ok("GET", "/api/dossiers/%d" % did)["proforma"]["cumul_ht"]
            c.ok("POST", "/api/dossiers/%d/bc" % did, {"bc_numero": bc[0], "bc_montant": cumul, "bc_date": bc[1]})
            c.ok("POST", "/api/dossiers/%d/generer-factures" % did, {"forcer": True})
        return did

    def factures(did):
        return c.ok("GET", "/api/factures?dossier=%d" % did)["factures"]

    def emettre(ids, date):
        return c.ok("POST", "/api/factures/emettre", {"ids": ids, "date_facture": date})

    # 1. agent seul, 6 mois, visite médicale
    d1 = dossier({"client_id": mines, "service": "DAF", "imputation": "IMP-FICTIVE-01", "lieu": "Moanda",
                  "date_debut": "2026-09-01", "date_fin": "2027-02-28", "visite_mode": "Auto", "date_proforma": "2026-08-20",
                  "nom_numero": "MOUELE", "agents": [{"nom": "MOUELE Aline Fictive", "poste": "Comptable fournisseurs",
                                                      "salaire_base": 600000}]}, bc=("900001", "2026-08-28"))
    fs = factures(d1)
    vis = [f["id"] for f in fs if f["type"] == "VISITE"]
    mad = [f["id"] for f in fs if f["type"] == "MAD"]
    emettre(vis + mad[:1], "2026-09-30")
    emettre(mad[1:2], "2026-10-31")
    c.ok("POST", "/api/factures/envoyees", {"ids": vis + mad[:2], "date": "2026-11-03"})
    c.ok("POST", "/api/factures/paiement", {"ids": vis, "date": "2026-11-15", "reference": "VIR-FICTIF-001"})
    c.ok("POST", "/api/dossiers/%d/pieces" % d1, {"categorie": "DA", "nom": "DA fictive MOUELE.pdf",
                                                    "contenu": base64.b64encode(_pdf_fictif("DA fictive - MOUELE")).decode()})
    r["agent_seul"] = d1
    r["heures_sup"] = ajouter_heures_sup(c, d1)

    # 2. groupe de 9 infirmiers, une facture par mois pour tout le groupe
    agents9 = [{"nom": "%s %s Fictif" % (n, p), "poste": "IDE", "salaire_base": 650000}
               for n, p in zip(INFIRMIERS, ["Paul", "Marie", "Jean", "Rose", "Luc", "Anne", "Marc", "Lise", "Yves"])]
    d2 = dossier({"client_id": mines, "service": "Direction médicale", "lieu": "Moanda (6) / Mounana (3)",
                  "date_debut": "2026-08-01", "date_fin": "2026-10-31", "visite_mode": "Auto", "date_proforma": "2026-07-20",
                  "nom_numero": "(9) Infirmiers_IDE", "facture_groupee": True, "agents": agents9},
                 bc=("900002", "2026-07-29"))
    fs = factures(d2)
    mad = sorted([f for f in fs if f["type"] == "MAD"], key=lambda f: f["mois"])
    vis = [f["id"] for f in fs if f["type"] == "VISITE"]
    emettre(vis + [mad[0]["id"]], "2026-08-31")
    emettre([mad[1]["id"]], "2026-09-30")
    emettre([mad[2]["id"]], "2026-10-31")
    c.ok("POST", "/api/factures/envoyees", {"ids": vis + [f["id"] for f in mad], "date": "2026-11-02"})
    ttc = {f["id"]: f["ttc"] for f in factures(d2)}
    c.ok("POST", "/api/factures/paiement", {"ids": vis + [mad[0]["id"]], "date": "2026-10-20", "reference": "VIR-FICTIF-002"})
    # paiement supérieur à la facture (accepté, signalé « À vérifier » au tableau de bord)
    c.ok("POST", "/api/factures/paiement", {"ids": [mad[1]["id"]], "date": "2026-11-20", "reference": "VIR-FICTIF-003",
                                             "montant": ttc[mad[1]["id"]] + 150000})
    r["groupe_9"] = d2

    # 3. prolongation du même groupe : dernière visite il y a moins d'un an -> pas refacturée
    d3 = dossier({"client_id": mines, "service": "Direction médicale", "lieu": "Moanda (6) / Mounana (3)",
                  "date_debut": "2026-11-01", "date_fin": "2027-01-31", "visite_mode": "Auto", "date_proforma": "2026-10-25",
                  "nom_numero": "(9) Infirmiers_IDE", "facture_groupee": True,
                  "notes": "Prolongation de la DA d'août (exemple fictif).",
                  "agents": [dict(a, derniere_visite="2026-08-01") for a in agents9]})
    r["prolongation"] = d3

    # 4. départ en milieu de mois (prorata), client de Libreville, PV différent -> « bis », facture corrigée
    d4 = dossier({"client_id": port, "service": "Exploitation", "lieu": "Libreville", "date_debut": "2026-06-15",
                  "date_fin": "2026-12-14", "visite_mode": "Auto", "date_proforma": "2026-06-05", "nom_numero": "NGUEMA",
                  "agents": [{"nom": "NGUEMA Serge Fictif", "poste": "Chef de quai", "salaire_base": 450000}]},
                 bc=("900003", "2026-06-12"))
    fs = factures(d4)
    mad = sorted([f for f in fs if f["type"] == "MAD"], key=lambda f: f["mois"])
    vis = [f["id"] for f in fs if f["type"] == "VISITE"]
    emettre(vis + [mad[0]["id"]], "2026-06-30")
    for f, dte in zip(mad[1:5], ["2026-07-31", "2026-08-31", "2026-09-30", "2026-10-31"]):
        emettre([f["id"]], dte)
    c.ok("POST", "/api/factures/envoyees", {"ids": vis + [f["id"] for f in mad[:5]], "date": "2026-11-04"})
    c.ok("POST", "/api/factures/paiement", {"ids": vis + [f["id"] for f in mad[:3]], "date": "2026-11-10",
                                             "reference": "VIR-FICTIF-004"})
    # PV de septembre : 2 jours d'absence -> facture « bis » au montant du PV
    c.ok("POST", "/api/factures/%d/bis" % mad[3]["id"], {"montant_ht": mad[3]["montant_ht"] - 57000, "date_pv": "2026-10-15",
                                                         "remarque": "PV fictif : 2 jours d'absence"})
    # facture d'octobre corrigée à la main (unité, remarque)
    c.ok("PUT", "/api/factures/%d" % mad[4]["id"], {"montant_ht": mad[4]["montant_ht"], "jours": mad[4]["jours"],
                                                    "unite": "Jours ouvrés", "remarque": "Corrigée : unité demandée par le client"})
    r["prorata_bis"] = d4

    # 5. deux agents sur 15 mois : visite à l'embauche puis à l'anniversaire
    d5 = dossier({"client_id": port, "service": "Maintenance", "lieu": "Port-Gentil", "date_debut": "2025-10-01",
                  "date_fin": "2026-12-31", "visite_mode": "Auto", "date_proforma": "2025-09-20", "nom_numero": "(2) Techniciens",
                  "agents": [{"nom": "ONDO Rémi Fictif", "poste": "Technicien", "salaire_base": 380000},
                             {"nom": "ESSONO Carine Fictive", "poste": "Technicienne", "salaire_base": 380000}]},
                 bc=("900004", "2025-09-28"))
    fs = factures(d5)
    mois = sorted({f["mois"] for f in fs if f["mois"] < "2026-11-01"})
    for m in mois:                                   # une émission par mois, en fin de mois
        a, mm = int(m[:4]), int(m[5:7])
        emettre([f["id"] for f in fs if f["mois"] == m], "%04d-%02d-%02d" % (a, mm, calendar.monthrange(a, mm)[1]))
    payees = [f["id"] for f in fs if f["mois"] < "2026-09-01"]
    c.ok("POST", "/api/factures/paiement", {"ids": payees, "date": "2026-10-30", "reference": "VIR-FICTIF-005"})
    r["anniversaire"] = d5

    # 6. DA reçue puis annulée
    d6 = dossier({"client_id": mines, "service": "Logistique", "lieu": "Moanda", "date_debut": "2026-12-01",
                  "date_fin": "2027-03-31", "visite_mode": "Auto", "nom_numero": "BIYOGO",
                  "agents": [{"nom": "BIYOGO Paulin Fictif", "poste": "Magasinier", "salaire_base": 300000}]})
    c.ok("POST", "/api/dossiers/%d/statut" % d6, {"statut": "Annulé"})
    r["annule"] = d6
    return r



def ajouter_heures_sup(c, did):
    """Heures supplémentaires fictives sur un dossier : un relevé facturé et payé, un relevé au stade du devis."""
    p = c.ok("GET", "/api/parametres")["parametres"]
    maj = {k: v for k, v in (("dernier_num_proforma_h", 20), ("dernier_num_facture_h", 10)) if p.get(k) is None}
    if maj:
        c.ok("PUT", "/api/parametres", {"parametres": maj})
    ag = c.ok("GET", "/api/dossiers/%d" % did)["agents"][0]["id"]
    fiche = {"direction": "DIRECTION FICTIVE", "service": "Laboratoire (fictif)", "section": "0000", "matricule_client": "MAD",
             "categorie": "C00A", "heures": None}
    l1 = [{"date": "2026-10-05", "debut": "16:00", "fin": "20:00", "justification": "Clôture mensuelle (fictif)"},
          {"date": "2026-10-06", "debut": "16:00", "fin": "21:00", "justification": "Inventaire (fictif)"},
          {"date": "2026-10-11", "debut": "08:00", "fin": "14:00", "justification": "Permanence (fictif)"},
          {"date": "2026-10-14", "debut": "20:00", "fin": "23:00", "justification": "Urgence (fictif)"}]
    h1 = c.ok("POST", "/api/dossiers/%d/heures-sup" % did, {"agent_id": ag})["id"]
    c.ok("POST", "/api/heures-sup/%d/releve" % h1, {"nom": "Releve heures fictif.pdf",
                                                    "contenu": base64.b64encode(_pdf_fictif("Releve d'heures fictif")).decode()})
    c.ok("PUT", "/api/heures-sup/%d" % h1, dict(fiche, lignes=l1))
    c.ok("POST", "/api/heures-sup/%d/devis" % h1, {"date": "2026-10-20"})
    c.ok("POST", "/api/heures-sup/%d/facture" % h1, {"date_facture": "2026-11-05", "bc_numero": "900011"})
    c.ok("POST", "/api/heures-sup/%d/suivi" % h1, {"envoyee_le": "2026-11-06"})
    for etape, jour in (("avant", "2026-10-02"), ("apres", "2026-10-15")):
        c.ok("POST", "/api/heures-sup/%d/etape" % h1, {"etape": etape, "date": jour})
    c.ok("POST", "/api/heures-sup/%d/suivi" % h1, {"fiche_envoyee_le": "2026-10-16"})
    h2 = c.ok("POST", "/api/dossiers/%d/heures-sup" % did, {"agent_id": ag})["id"]
    c.ok("PUT", "/api/heures-sup/%d" % h2, dict(fiche, lignes=[
        # saisie en grille (heures par jour), à cheval sur deux mois, avec un dimanche férié (Toussaint)
        {"date": "2026-10-29", "heures": 4, "justification": "Audit (fictif)"},
        {"date": "2026-10-31", "heures": 6, "justification": "Clôture (fictif)"},
        {"date": "2026-11-01", "heures": 5, "justification": "Permanence (fictif)"},
        {"date": "2026-11-02", "heures": 3}]))
    c.ok("POST", "/api/heures-sup/%d/devis" % h2, {"date": "2026-11-20"})
    return [h1, h2]


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    cl = Client(sys.argv[1])
    cl.connexion(sys.argv[2], sys.argv[3], sys.stdin.readline().strip())
    print(json.dumps(remplir(cl)))
