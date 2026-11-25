"""Vérifications EN LIGNE du site de test (API), sur l'entreprise « verif » remplie avec le
jeu de données fictives (outils/donnees_fictives.py). Lancé par GitHub après chaque mise à jour.

  SITE=https://dev.exemple.com MDP_VERIF=... python3 tests/en_ligne/verifier_dev_api.py

Ne lit et n'écrit que dans « verif » (recréée à chaque mise à jour) ; essaie seulement de
LIRE « essai » pour vérifier qu'on n'y a pas accès.
"""
import io
import os
import re
import secrets
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "outils"))
import donnees_fictives as F  # noqa: E402

SITE = os.environ["SITE"].rstrip("/")
MDP = os.environ["MDP_VERIF"]
reussis, echecs = 0, 0


def verifier(cond, libelle, detail=None):
    global reussis, echecs
    if cond:
        reussis += 1
        print("  ok    " + libelle)
    else:
        echecs += 1
        print("  ÉCHEC " + libelle + ("" if detail is None else " -> %r" % (detail,))[:400])


def nouveau():
    return F.Client(SITE, hote=os.environ.get("HOTE"))


def main():
    a = nouveau()
    a.connexion("verif", "direction", MDP)
    st, moi = a.req("GET", "/api/moi")
    verifier(st == 200 and moi.get("utilisateur", {}).get("role") == "admin", "connexion Direction sur « verif »", moi)

    print("\n1. Jeu de données fictives")
    ds = {d["id"]: d for d in a.ok("GET", "/api/dossiers")["dossiers"]}
    verifier(len(ds) == 6, "6 dossiers fictifs", len(ds))
    verifier(ds.get(6, {}).get("statut") == "Annulé", "DA annulée", ds.get(6, {}).get("statut"))
    verifier(ds.get(3, {}).get("statut") == "Brouillon", "prolongation : proforma seule, sans BC", ds.get(3, {}).get("statut"))
    verifier(not any(re.search(r"\b(KABILA|MANDZEYI)\b", str(d), re.I) for d in ds.values()), "aucun nom réel connu")

    print("\n2. Calculs")
    p = {i: a.ok("GET", "/api/dossiers/%d" % i)["proforma"] for i in (1, 2, 3, 4, 5)}
    verifier(p[1]["cout_mensuel_total"] == 1146000, "agent seul : 600 000 × 1,91 = 1 146 000 par mois", p[1]["cout_mensuel_total"])
    verifier(p[1]["cumul_ht"] == 6 * 1146000 + 45000, "agent seul : 6 mois + visite = 6 921 000", p[1]["cumul_ht"])
    verifier(p[2]["cout_mensuel_total"] == 11173500, "9 infirmiers : 11 173 500 par mois (arrondi une seule fois)", p[2]["cout_mensuel_total"])
    verifier((p[2]["nb_visites"], p[2]["visites_ht"]) == (9, 405000), "9 visites médicales", (p[2]["nb_visites"], p[2]["visites_ht"]))
    verifier(p[3]["nb_visites"] == 0, "prolongation < 1 an : visite pas refacturée", p[3]["nb_visites"])
    verifier(p[5]["nb_visites"] == 4, "2 agents sur 15 mois : visite à l'embauche + à l'anniversaire (4)", p[5]["nb_visites"])
    f4 = a.ok("GET", "/api/factures?dossier=4")["factures"]
    juin = [f for f in f4 if f["type"] == "MAD" and f["mois"].startswith("2026-06")]
    verifier(juin and juin[0]["montant_ht"] == 458400 and juin[0]["jours"] == 16, "prorata : 15 → 30 juin = 16/30 de 859 500 = 458 400",
             juin and (juin[0]["montant_ht"], juin[0]["jours"]))
    dec = [f for f in f4 if f["mois"].startswith("2026-12")]
    verifier(dec and dec[0]["montant_ht"] == 388161, "prorata : 1 → 14 décembre = 14/31", dec and dec[0]["montant_ht"])

    print("\n3. Factures")
    tout = a.ok("GET", "/api/factures")["factures"]
    nums = [f["numero"] for f in tout if f["numero"]]
    verifier(len(nums) == len(set(nums)), "aucun n° de facture en double", len(nums))
    verifier(all(re.fullmatch(r"FA \d+( bis)?/(\d\d|Visite médicale)/20\d\d", n) for n in nums),
             "n° au format FA 159/11/2026 ou FA 159/Visite médicale/2026", [n for n in nums if not re.fullmatch(r"FA \d+( bis)?/(\d\d|Visite médicale)/20\d\d", n)][:3])
    vis = [f for f in tout if f["type"] == "VISITE" and f["numero"]]
    verifier(vis and all(f["tva"] == 0 for f in vis), "visite médicale sans TVA", [f["tva"] for f in vis][:5])
    mad = [f for f in tout if f["type"] == "MAD" and f["numero"]]
    verifier(all(f["tva"] == round(f["montant_ht"] * 0.18) or abs(f["tva"] - f["montant_ht"] * 0.18) <= 1 for f in mad), "TVA 18 % sur les factures mensuelles")
    g = [f for f in tout if f.get("groupe")]
    verifier(g and all(f["nb_agents"] == 9 and f["agent"].startswith("NDONG_MBOUMBA") for f in g if f["dossier_id"] == 2),
             "groupe : une facture par mois pour les 9 (NDONG_MBOUMBA_…)", g[:1] and (g[0]["nb_agents"], g[0]["agent"]))
    bis = [f for f in tout if f["type"] == "BIS"]
    verifier(len(bis) == 1 and bis[0]["montant_ht"] == 802500 and " bis/" in bis[0]["numero"], "facture « bis » au montant du PV",
             bis and (bis[0]["numero"], bis[0]["montant_ht"]))
    verifier(any(f["statut"] == "Remplacée" for f in f4), "facture d'origine marquée « Remplacée »")
    mod = [f for f in f4 if f.get("unite") == "Jours ouvrés"]
    verifier(len(mod) == 1 and mod[0].get("modifiee_le"), "facture corrigée à la main (unité « Jours ouvrés »)", mod and mod[0].get("unite"))
    gm = [f for f in g if f["type"] == "MAD"]
    st, doc = a.req("GET", "/api/factures/word?ids=%d" % gm[0]["id"])
    xml = zipfile.ZipFile(io.BytesIO(doc)).read("word/document.xml").decode() if st == 200 else ""
    verifier("MAD de 9 IDE" in xml, "Word de la facture groupée : « MAD de 9 IDE »", st)
    verifier("650000" not in xml and "650.000" not in xml, "aucun salaire de base dans le Word")
    st, csv = a.req("GET", "/api/factures/export.csv")
    verifier(st == 200 and "650000" not in str(csv), "export CSV sans salaire", st)

    print("\n4. Tableau de bord")
    t = a.ok("GET", "/api/tableau-de-bord?mois=2026-11")
    verifier(len(t["trop_percus"]) == 1 and t["trop_percus"][0]["paye"] - t["trop_percus"][0]["ttc"] == 150000,
             "paiement supérieur à la facture accepté et signalé (150 000 de trop)", t["trop_percus"])
    verifier(t["reste_a_encaisser"] >= 0, "reste à encaisser jamais négatif", t["reste_a_encaisser"])
    verifier(t["personnes_en_contrat"] == 4 and t["personnes_en_attente"] == 9, "novembre : 4 en contrat, 9 en attente de BC",
             (t["personnes_en_contrat"], t["personnes_en_attente"]))
    verifier(any(x["agent"].startswith("NGUEMA") for x in t["alertes_fin"]), "alerte de fin de contrat (14 décembre)")

    print("\n5. Pièces jointes")
    docs = a.ok("GET", "/api/dossiers/1/documents")["documents"]
    da = [d for d in docs if d["categorie"] == "DA"]
    st, contenu = a.req("GET", "/api/documents/%d" % da[0]["id"]) if da else (0, b"")
    verifier(st == 200 and bytes(contenu).startswith(b"%PDF-"), "DA en PDF jointe et téléchargeable", st)
    fac = [d for d in docs if d["categorie"] == "Facture"]
    verifier(len(fac) >= 3, "copie gardée de chaque facture émise", len(fac))

    print("\n6. Rôles")
    comptes = {}
    for role in ("gestion", "lecture"):
        prov, fin = "Prov-%s-%s" % (role, secrets.token_urlsafe(8)), "Fin-%s-%s!" % (role, secrets.token_urlsafe(10))
        st, j = a.req("POST", "/api/utilisateurs", {"identifiant": "essai-" + role, "nom": "Compte %s fictif" % role,
                                                    "role": role, "mot_de_passe": prov})
        c = nouveau()
        c.connexion("verif", "essai-" + role, prov)
        st2, j2 = c.req("GET", "/api/dossiers")
        verifier(st2 == 403, "%s : mot de passe provisoire à changer avant tout" % role, st2)
        st3, _ = c.req("POST", "/api/moi/mot-de-passe", {"actuel": prov, "nouveau": fin})
        verifier(st3 == 200, "%s : changement de mot de passe" % role, st3)
        comptes[role] = c
    g_, l_ = comptes["gestion"], comptes["lecture"]
    verifier(g_.req("GET", "/api/dossiers")[0] == 200, "Gestion voit les dossiers")
    verifier(g_.req("GET", "/api/utilisateurs")[0] == 403, "Gestion ne gère pas les comptes")
    verifier(g_.req("PUT", "/api/parametres", {"parametres": {"ville": "x"}})[0] == 403, "Gestion ne change pas les paramètres")
    verifier(l_.req("GET", "/api/tableau-de-bord")[0] == 200, "Lecture voit le tableau de bord")
    verifier(l_.req("GET", "/api/dossiers")[0] == 403, "Lecture ne voit pas les dossiers (salaires)")
    verifier(l_.req("POST", "/api/factures/paiement", {"ids": [1], "date": "2026-11-25"})[0] == 403, "Lecture n'enregistre pas de paiement")
    verifier(l_.req("GET", "/api/factures/word?ids=1")[0] == 403, "Lecture n'exporte pas en Word")

    print("\n7. Isolation des entreprises et sécurité")
    jeton = a.cookie.split("=", 1)[1].split(".", 1)[1]
    autre = nouveau()
    autre.cookie = a.cookie.split("=", 1)[0] + "=essai." + jeton
    autre.csrf = a.csrf
    verifier(autre.req("GET", "/api/dossiers")[0] == 401, "session de « verif » refusée chez « essai »")
    st, j = nouveau().req("POST", "/api/connexion", {"entreprise": "essai", "identifiant": "direction", "mot_de_passe": MDP})
    verifier(st == 401, "mot de passe de « verif » refusé chez « essai »", st)
    sans = nouveau()
    sans.cookie = a.cookie
    verifier(sans.req("POST", "/api/clients", {"nom": "Client sans jeton CSRF"})[0] == 403, "écriture refusée sans jeton CSRF")
    pirate = nouveau()
    pirate.origine = "https://site-pirate.example"
    st, _ = pirate.req("POST", "/api/connexion", {"entreprise": "verif", "identifiant": "direction", "mot_de_passe": MDP})
    verifier(st == 403, "connexion refusée depuis un autre site (Origin)", st)
    st, j = nouveau().req("POST", "/api/connexion", {"entreprise": "verif", "identifiant": "direction", "mot_de_passe": "Mauvais-mdp-123"})
    verifier(st == 401 and "incorrect" in str(j), "mauvais mot de passe : message neutre", st)
    a.ok("POST", "/api/deconnexion", {})
    verifier(a.req("GET", "/api/dossiers")[0] == 401, "déconnexion : session fermée")

    print("\n%d contrôle(s) réussi(s), %d échec(s)." % (reussis, echecs))
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
