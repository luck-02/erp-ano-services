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
    t = re.sub(r"[^A-Z0-9 ()_\-]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def noms_groupe(noms):
    """Ligne des noms comme sur les documents d'ANO : 1 agent = nom complet ;
    plusieurs = 1er mot de chaque nom, séparés par « _ » (DUPONT_MBINA_…)."""
    noms = [str(n).strip() for n in noms if str(n).strip()]
    if len(noms) == 1:
        return noms[0]
    return "_".join(premier_mot(n).upper() for n in noms)


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
    nb_visites = 0
    for a in agents:
        cout = cout_mensuel(a["salaire_base"], charges)
        vis = dates_visites(debut, fin, a.get("derniere_visite"), dossier.get("visite_mode", "Auto"), validite)
        nb_visites += len(vis)
        total_base += int(a["salaire_base"])
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
    # Coût mensuel du groupe calculé sans arrondi par agent, arrondi une seule fois,
    # comme la proforma Excel (9 × 674 220 × 1,91 = 11 589 841,8 -> 11 589 842)
    cout_exact = Fraction(total_base * coefficient_pdm(charges), 10000)
    total_cout = arrondi(cout_exact)
    mois = []
    somme_prorata = Fraction(0)
    for m, j, jm in mois_couverts(debut, fin):
        p = Fraction(j, jm)
        somme_prorata += p
        mois.append({"mois": m.isoformat(), "libelle": libelle_mois(m), "jours": j, "jours_mois": jm,
                     "prorata": float(p), "complet": j == jm,
                     "montant": float(cout_exact * p)})
    visites_ht = nb_visites * visite_ht
    # Cumul : prorata non arrondi mois par mois, arrondi une seule fois
    cumul_ht = visites_ht + arrondi(cout_exact * somme_prorata)
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
def lignes_factures_groupe(dossier, agents, charges, params):
    """Facture groupée (ex. 9 infirmiers : une seule facture par mois pour tout le
    groupe, quantité 1 mois). Montant = coût du groupe au prorata, arrondi une fois.
    Visites : une facture par mois où il y en a, quantité = nombre de visites."""
    debut, fin = dossier["date_debut"], dossier["date_fin"]
    total_base = sum(int(a["salaire_base"]) for a in agents)
    cout_exact = Fraction(total_base * coefficient_pdm(charges), 10000)
    visites = {}
    for a in agents:
        for v in dates_visites(debut, fin, a.get("derniere_visite"), dossier.get("visite_mode", "Auto"),
                               int(params.get("validite_visite_mois", 12))):
            visites[debut_mois(v)] = visites.get(debut_mois(v), 0) + 1
    res = [{"type": TYPE_VISITE, "mois": m, "jours": n, "jours_mois": None,
            "montant_ht": n * int(params["visite_ht"])} for m, n in sorted(visites.items())]
    for m, j, jm in mois_couverts(debut, fin):
        res.append({"type": TYPE_MAD, "mois": m, "jours": j, "jours_mois": jm,
                    "montant_ht": arrondi(cout_exact * Fraction(j, jm))})
    return res


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


def numero_facture(n, type_facture, date_emission, prefixe="FA", code_mad="", code_visite="Visite médicale"):
    """Règle des factures réelles d'ANO (Luc, 25/11/2026) :
    - facture du mois : FA 159/11/2026 (11 = mois d'émission ; avec un code : FA 159/11-MAD/2026)
    - visite médicale : FA 159/Visite médicale/2026 (même n° que la facture du mois
      émise avec elle ; n° à elle si elle est émise seule)
    Préfixe et codes réglables par entreprise (Paramètres)."""
    if type_facture == TYPE_VISITE:
        return ("%s %d/%s/%d" % (prefixe, n, code_visite or "Visite médicale", date_emission.year)).strip()
    suite = "-" + code_mad if code_mad else ""
    return ("%s %d/%02d%s/%d" % (prefixe, n, date_emission.month, suite, date_emission.year)).strip()


def numero_bis(numero):
    """FA 152/08/2026 -> FA 152 bis/08/2026"""
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


# ---------------------------------------------------------------------------
# Heures supplémentaires (circuit de Lola, 25/11/2026) :
# relevé COMILOG -> fiche d'attachement -> classement 28/56/75 % -> Proforma H -> facture FA H
# ---------------------------------------------------------------------------
HS_CATEGORIES = ("h1", "h2", "h3")


def hs_taux_horaire(cout, diviseur_centiemes=17333):
    """Taux horaire exact (fraction) = coût mensuel ÷ 173,33 heures."""
    return Fraction(int(cout) * 100, int(diviseur_centiemes))


def hs_heures(v):
    """Heures saisies (8, 7,5, « 3 H ») -> Fraction au quart d'heure près."""
    if isinstance(v, (int, float)):
        f = Fraction(v).limit_denominator(100)
    else:
        t = str(v or "").upper().replace("H", "").replace(",", ".").strip()
        if not re.fullmatch(r"\d{1,3}(\.\d{1,2})?", t):
            raise ValueError("heures")
        f = Fraction(t)
    return f


def hs_lignes_montants(cout, heures, taux_pdm, diviseur_centiemes=17333):
    """Une ligne par catégorie : taux horaire majoré (arrondi, affiché) et total,
    calculé sur le taux exact puis arrondi une seule fois par ligne (comme le devis de Lola).
    heures et taux_pdm : listes de même longueur (ex. [27, 28, 15] et [2800, 5600, 7500])."""
    th = hs_taux_horaire(cout, diviseur_centiemes)
    res = []
    for h, t in zip(heures, taux_pdm):
        maj = th * (10000 + int(t)) / 10000
        res.append({"heures": float(Fraction(h)), "taux_pdm": int(t), "taux_horaire": arrondi(maj),
                    "total": arrondi(maj * Fraction(h))})
    return {"taux_horaire": arrondi(th), "lignes": res, "total": sum(x["total"] for x in res)}


def _minutes(hhmm):
    if not hhmm:
        return None
    m = re.fullmatch(r"(\d{1,2})[:hH](\d{2})?", str(hhmm).strip())
    if not m or int(m.group(1)) > 24 or int(m.group(2) or 0) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def hs_part_nuit(debut, fin, nuit_debut=21, nuit_fin=5):
    """Fraction de la plage [debut, fin) (HH:MM, peut passer minuit) tombée la nuit."""
    d, f = _minutes(debut), _minutes(fin)
    if d is None or f is None or d == f:
        return None
    if f <= d:
        f += 24 * 60
    nd, nf = nuit_debut * 60, nuit_fin * 60
    nuit = 0
    for jour in (-1, 0, 1):          # nuits de la veille, du jour et du lendemain
        a = nd + jour * 1440
        b = (nf + (jour + 1) * 1440) if nf <= nd else nf + jour * 1440
        nuit += max(0, min(f, b) - max(d, a))
    return Fraction(nuit, f - d)


def hs_classer(lignes, seuil_semaine=8, nuit_debut=21, nuit_fin=5, jours_repos=(6,)):
    """Classement PROPOSÉ (modifiable) des heures réalisées :
    - heures de nuit -> h3 (75 %)
    - jour de repos (dimanche par défaut) -> h2 (56 %)
    - jours ouvrables : les `seuil_semaine` premières heures de la semaine -> h1 (28 %), au-delà -> h2.
    lignes : [{"date": date, "debut": "20:00", "fin": "23:00", "heures": Fraction}]"""
    tot = {"h1": Fraction(0), "h2": Fraction(0), "h3": Fraction(0)}
    deja = {}
    for l in sorted(lignes, key=lambda x: (x["date"], _minutes(x.get("debut")) or 0)):
        h = Fraction(l["heures"])
        pn = hs_part_nuit(l.get("debut"), l.get("fin"), nuit_debut, nuit_fin) or Fraction(0)
        nuit = h * pn
        jour = h - nuit
        tot["h3"] += nuit
        if l["date"].weekday() in jours_repos:
            tot["h2"] += jour
            continue
        sem = l["date"].isocalendar()[:2]
        reste = max(Fraction(0), Fraction(seuil_semaine) - deja.get(sem, 0))
        a28 = min(jour, reste)
        deja[sem] = deja.get(sem, 0) + a28
        tot["h1"] += a28
        tot["h2"] += jour - a28
    # au quart d'heure, sans perdre d'heure au total
    res = {k: Fraction(round(v * 4), 4) for k, v in tot.items()}
    ecart = sum((Fraction(l["heures"]) for l in lignes), Fraction(0)) - sum(res.values())
    if ecart:
        k = max(res, key=lambda x: res[x])
        res[k] += ecart
    return res


def numero_proforma_h(n, date_devis, code="ANO", suite="MAD"):
    """124-10-ANO-MAD/2026 (série à part des proformas de mise à disposition)."""
    return "%d-%02d-%s-%s/%d" % (n, date_devis.month, code, suite or "MAD", date_devis.year)


def numero_facture_h(n, date_emission, prefixe="FA", code="H"):
    """FA H 110/11/2026 (11 = mois d'émission, comme les autres factures)."""
    return ("%s %s %d/%02d/%d" % (prefixe, code or "H", n, date_emission.month, date_emission.year)).strip()
