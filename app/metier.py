"""Règles de calcul d'ANO Services (reprises de l'outil Excel V4).

Toutes les fonctions sont pures (aucun accès à la base) pour être testées
facilement. Les montants sont des entiers en XAF. Les taux sont stockés en
« pour dix mille » (18,5 % -> 1850) pour éviter les erreurs d'arrondi des
nombres à virgule.
"""
import calendar
import datetime as dt
import re
import unicodedata
from fractions import Fraction

STATUTS = ["Brouillon", "Envoyé", "Validé", "BC reçu", "En cours", "Terminé", "Annulé"]
# Statuts où le contrat est réellement en place (pour « personnes en contrat »)
STATUTS_EN_CONTRAT = {"Validé", "BC reçu", "En cours", "Terminé"}

MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

TYPE_MAD = "MAD"
TYPE_VISITE = "VISITE"
TYPE_BIS = "BIS"


# ---------------------------------------------------------------------------
# Arrondis et dates
# ---------------------------------------------------------------------------
def arrondi(x):
    """Arrondi à l'entier le plus proche, 0,5 vers le haut (comme ROUND d'Excel
    pour les montants positifs). Accepte int, Fraction."""
    x = Fraction(x)
    if x >= 0:
        return int((x + Fraction(1, 2)) // 1)
    return -int((-x + Fraction(1, 2)) // 1)


def jours_du_mois(d):
    return calendar.monthrange(d.year, d.month)[1]


def debut_mois(d):
    return dt.date(d.year, d.month, 1)


def fin_mois(d):
    return dt.date(d.year, d.month, jours_du_mois(d))


def ajouter_mois(d, n):
    """EDATE d'Excel : même jour n mois plus tard (borné à la fin du mois)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def mois_complets(d1, d2):
    """DATEDIF(d1; d2; "m") : nombre de mois entiers entre deux dates."""
    n = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        n -= 1
    return n


def libelle_mois(d):
    return "%s %d" % (MOIS_FR[d.month - 1], d.year)


def sans_accents(t):
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def cle_nom(nom):
    """Clé d'identification d'un intérimaire : sans accents, majuscules,
    espaces et tirets normalisés (« Dupont  Élise » = « DUPONT ELISE »)."""
    t = sans_accents(str(nom or "")).upper().replace("-", " ")
    return " ".join(t.split())


def matricule(n):
    return "INT-%04d" % n


# ---------------------------------------------------------------------------
# Coûts
# ---------------------------------------------------------------------------
def coefficient_pdm(charges):
    """1 + somme des taux, en pour dix mille (1,91 -> 19100)."""
    return 10000 + sum(int(c["taux_pdm"]) for c in charges)


def cout_mensuel(salaire_base, charges):
    """Coût mensuel HT d'un agent = salaire de base × coefficient, arrondi."""
    return arrondi(Fraction(int(salaire_base) * coefficient_pdm(charges), 10000))


def mois_couverts(debut, fin):
    """Liste des mois touchés par la période : (1er du mois, jours couverts,
    jours du mois). Jours calendaires, bornes incluses."""
    res = []
    m = debut_mois(debut)
    while m <= fin:
        d1 = max(debut, m)
        d2 = min(fin, fin_mois(m))
        jours = (d2 - d1).days + 1
        if jours > 0:
            res.append((m, jours, jours_du_mois(m)))
        m = ajouter_mois(m, 1)
    return res


def dates_visites(debut, fin, derniere_connue, mode, validite_mois=12):
    """Dates des visites médicales à facturer pendant le contrat (formules
    AO/AP du Suivi V4) : 1re visite au début si la dernière visite connue a
    plus d'un an (ou n'existe pas), puis une à chaque anniversaire."""
    if mode == "Non":
        return []
    z = derniere_connue
    if z is None:
        v1 = debut
    elif z >= debut:
        v1 = z
    elif ajouter_mois(z, validite_mois) <= debut:
        v1 = debut
    else:
        v1 = ajouter_mois(z, validite_mois)
    if v1 > fin:
        return []
    n = mois_complets(v1, fin) // validite_mois + 1
    return [ajouter_mois(v1, validite_mois * k) for k in range(n)]


def montant_mois(cout, jours, jours_mois):
    """Montant HT d'une facture mensuelle (prorata arrondi au franc)."""
    return arrondi(Fraction(int(cout) * jours, jours_mois))


def tva(ht, taux_tva_pdm):
    return arrondi(Fraction(int(ht) * int(taux_tva_pdm), 10000))


def echeance(date_facture, delai_jours):
    """« 30 JFDM » : date de facture + délai, puis fin de mois."""
    return fin_mois(date_facture + dt.timedelta(days=int(delai_jours)))


# ---------------------------------------------------------------------------
# Proforma
# ---------------------------------------------------------------------------
def nom_pour_numero(texte):
    t = sans_accents(texte or "").upper()
    t = re.sub(r"[^A-Z0-9 \-]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def premier_mot(texte):
    t = (texte or "").strip()
    return t.split(" ")[0] if t else ""


def numero_proforma(seq, date_proforma, nom, code="ANO"):
    """348-11-ANO-NOM/2026 ; « ANO » = code de l'entreprise (Paramètres)."""
    code = nom_pour_numero(code) or "ANO"
    return "%d-%02d-%s-%s/%d" % (seq, date_proforma.month, code, nom_pour_numero(nom), date_proforma.year)


def calcul_proforma(dossier, agents, charges, params):
    """Calcule toute la proforma d'un dossier (DA).

    dossier : dict avec date_debut, date_fin (date), visite_mode
    agents  : liste de dict (nom, poste, salaire_base, derniere_visite)
    charges : liste de dict (libelle, taux_pdm), dans l'ordre
    params  : dict (visite_ht, tva_pdm, validite_visite_mois)
    """
    debut, fin = dossier["date_debut"], dossier["date_fin"]
    visite_ht = int(params["visite_ht"])
    validite = int(params.get("validite_visite_mois", 12))
    lignes_agents = []
    total_base = 0
    total_cout = 0
    nb_visites = 0
    for a in agents:
        cout = cout_mensuel(a["salaire_base"], charges)
        vis = dates_visites(debut, fin, a.get("derniere_visite"), dossier.get("visite_mode", "Auto"), validite)
        nb_visites += len(vis)
        total_base += int(a["salaire_base"])
        total_cout += cout
        lignes_agents.append({
            "nom": a["nom"], "poste": a["poste"], "salaire_base": int(a["salaire_base"]),
            "cout_mensuel": cout, "visites": [v.isoformat() for v in vis],
        })
    nb = len(agents)
    detail = [{"libelle": "Salaire de base", "taux_pdm": None, "nb": nb,
               "pu": arrondi(Fraction(total_base, nb)) if nb else 0, "total": total_base}]
    for c in charges:
        tot = arrondi(Fraction(total_base * int(c["taux_pdm"]), 10000))
        detail.append({"libelle": c["libelle"], "taux_pdm": int(c["taux_pdm"]), "nb": nb,
                       "pu": arrondi(Fraction(tot, nb)) if nb else 0, "total": tot})
    mois = []
    somme_prorata = Fraction(0)
    for m, j, jm in mois_couverts(debut, fin):
        p = Fraction(j, jm)
        somme_prorata += p
        mois.append({"mois": m.isoformat(), "libelle": libelle_mois(m), "jours": j, "jours_mois": jm,
                     "prorata": float(p), "complet": j == jm,
                     "montant": float(total_cout * p)})
    visites_ht = nb_visites * visite_ht
    # Cumul : prorata non arrondi mois par mois, arrondi une seule fois
    cumul_ht = visites_ht + arrondi(total_cout * somme_prorata)
    t = tva(cumul_ht, params["tva_pdm"])
    return {
        "agents": lignes_agents, "nb_agents": nb, "coefficient_pdm": coefficient_pdm(charges),
        "detail_charges": detail, "total_base": total_base, "cout_mensuel_total": total_cout,
        "mois": mois, "nb_visites": nb_visites, "visite_ht": visite_ht, "visites_ht": visites_ht,
        "cumul_ht": cumul_ht, "tva": t, "cumul_ttc": cumul_ht + t,
    }


# ---------------------------------------------------------------------------
# Factures
# ---------------------------------------------------------------------------
def lignes_factures_agent(dossier, agent, charges, params):
    """Factures prévues pour un agent : visites (au mois de chaque visite)
    puis une facture par mois couvert, montant au prorata."""
    debut, fin = dossier["date_debut"], dossier["date_fin"]
    cout = cout_mensuel(agent["salaire_base"], charges)
    res = []
    for v in dates_visites(debut, fin, agent.get("derniere_visite"), dossier.get("visite_mode", "Auto"),
                           int(params.get("validite_visite_mois", 12))):
        res.append({"type": TYPE_VISITE, "mois": debut_mois(v), "jours": None, "jours_mois": None,
                    "montant_ht": int(params["visite_ht"])})
    for m, j, jm in mois_couverts(debut, fin):
        res.append({"type": TYPE_MAD, "mois": m, "jours": j, "jours_mois": jm,
                    "montant_ht": montant_mois(cout, j, jm)})
    return res


def numero_facture(n, type_facture, mois, prefixe="FA", code_mad="MAD", code_visite="Visite Médicale"):
    """FA 161/11-MAD/2026 ; préfixe et codes réglables par entreprise (Paramètres)."""
    libelle = code_visite if type_facture == TYPE_VISITE else code_mad
    return ("%s %d/%02d-%s/%d" % (prefixe, n, mois.month, libelle, mois.year)).strip()


def numero_bis(numero):
    """FA 152/08-MAD/2026 -> FA 152 bis/08-MAD/2026"""
    if "/" in numero:
        i = numero.index("/")
        return numero[:i] + " bis" + numero[i:]
    return numero + " bis"


def statut_facture(f, aujourd_hui):
    if f.get("remplacee_par_id"):
        return "Remplacée"
    if f.get("paye_le"):
        return "Payée"
    if not f.get("numero"):
        return "À émettre"
    if not f.get("envoyee_le"):
        return "À envoyer"
    if f.get("echeance") and aujourd_hui > dt.date.fromisoformat(f["echeance"]):
        return "En retard"
    return "Envoyée"
