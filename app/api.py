"""Points d'entrée de l'API (logique applicative). Chaque fonction reçoit
le contexte de la requête (ctx), les groupes de l'URL et le corps JSON, et
renvoie un objet JSON. Les erreurs passent par ErreurAPI."""
import datetime as dt
import json
import os
import re

import db
import docx_facture
import metier as M
import securite as S


class Fichier:
    """Réponse binaire (image, document) au lieu de JSON. Avec un nom, le
    navigateur le télécharge (Content-Disposition: attachment)."""
    def __init__(self, contenu, type_, nom=None):
        self.contenu, self.type_, self.nom = contenu, type_, nom


class ErreurAPI(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


# ---------------------------------------------------------------------------
# Validation des entrées
# ---------------------------------------------------------------------------
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def texte(d, cle, maxi=200, requis=False, defaut="", multiligne=False):
    v = d.get(cle, defaut)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ErreurAPI(400, "Champ « %s » : texte attendu." % cle)
    v = v.strip()
    if not multiligne:
        v = v.replace("\n", " ").replace("\r", " ")
    v = _CTRL.sub("", v)
    if requis and not v:
        raise ErreurAPI(400, "Champ « %s » obligatoire." % cle)
    if len(v) > maxi:
        raise ErreurAPI(400, "Champ « %s » trop long (%d caractères maximum)." % (cle, maxi))
    return v


def entier(d, cle, mini=None, maxi=None, requis=True, defaut=None):
    v = d.get(cle, defaut)
    if v is None or v == "":
        if requis:
            raise ErreurAPI(400, "Champ « %s » obligatoire." % cle)
        return None
    if isinstance(v, bool):
        raise ErreurAPI(400, "Champ « %s » : nombre entier attendu." % cle)
    if isinstance(v, str):
        s = v.replace(" ", "").replace(" ", "").replace(" ", "")
        if not re.fullmatch(r"-?\d{1,15}", s):
            raise ErreurAPI(400, "Champ « %s » : nombre entier attendu." % cle)
        v = int(s)
    if isinstance(v, float):
        if not v.is_integer():
            raise ErreurAPI(400, "Champ « %s » : nombre entier attendu." % cle)
        v = int(v)
    if not isinstance(v, int):
        raise ErreurAPI(400, "Champ « %s » : nombre entier attendu." % cle)
    if mini is not None and v < mini:
        raise ErreurAPI(400, "Champ « %s » : minimum %d." % (cle, mini))
    if maxi is not None and v > maxi:
        raise ErreurAPI(400, "Champ « %s » : maximum %d." % (cle, maxi))
    return v


def date_(d, cle, requis=True):
    v = d.get(cle)
    if v in (None, ""):
        if requis:
            raise ErreurAPI(400, "Date « %s » obligatoire." % cle)
        return None
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ErreurAPI(400, "Date « %s » invalide (format AAAA-MM-JJ)." % cle)
    try:
        x = dt.date.fromisoformat(v)
    except ValueError:
        raise ErreurAPI(400, "Date « %s » invalide." % cle)
    if not (2000 <= x.year <= 2100):
        raise ErreurAPI(400, "Date « %s » hors limites." % cle)
    return x


def mois_(v, cle="mois"):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}", v):
        raise ErreurAPI(400, "Mois invalide (format AAAA-MM).")
    y, m = int(v[:4]), int(v[5:])
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        raise ErreurAPI(400, "Mois invalide.")
    return dt.date(y, m, 1)


def booleen(d, cle):
    v = d.get(cle, False)
    if not isinstance(v, bool):
        raise ErreurAPI(400, "Champ « %s » : vrai/faux attendu." % cle)
    return v


def liste_ids(d, cle="ids", maxi=1000):
    v = d.get(cle)
    if not isinstance(v, list) or not v or len(v) > maxi:
        raise ErreurAPI(400, "Sélectionnez au moins une ligne.")
    res = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            raise ErreurAPI(400, "Identifiant invalide.")
        res.append(x)
    return sorted(set(res))


def aujourdhui():
    return dt.date.today()


# ---------------------------------------------------------------------------
# Outils base de données
# ---------------------------------------------------------------------------
def journaliser(ctx, action, objet="", details=""):
    u = ctx.get("user") or {}
    ctx["con"].execute(
        "INSERT INTO journal(quand, user_id, identifiant, action, objet, details) VALUES (?,?,?,?,?,?)",
        (db.maintenant(), u.get("id"), u.get("identifiant", ctx.get("identifiant_tente", "")),
         action, str(objet)[:200], str(details)[:1000]))


def parametres(con):
    return {r["cle"]: json.loads(r["valeur"]) for r in con.execute("SELECT cle, valeur FROM parametres")}


def charges(con):
    return [dict(r) for r in con.execute("SELECT libelle, taux_pdm FROM charges ORDER BY ordre")]


class Transaction:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, typ, val, tb):
        self.con.execute("COMMIT" if typ is None else "ROLLBACK")
        return False


def _dossier_row(con, did):
    r = con.execute("SELECT * FROM dossiers WHERE id = ?", (did,)).fetchone()
    if not r:
        raise ErreurAPI(404, "Dossier introuvable.")
    return r


def _agents(con, did):
    return [dict(r) for r in con.execute(
        "SELECT a.*, i.matricule FROM agents a LEFT JOIN interimaires i ON i.id = a.interimaire_id "
        "WHERE a.dossier_id = ? ORDER BY a.rang", (did,))]


def _pour_calcul(drow, agents):
    d = {"date_debut": dt.date.fromisoformat(drow["date_debut"]),
         "date_fin": dt.date.fromisoformat(drow["date_fin"]),
         "visite_mode": drow["visite_mode"]}
    ags = [{"nom": a["nom"], "poste": a["poste"], "salaire_base": a["salaire_base"],
            "derniere_visite": dt.date.fromisoformat(a["derniere_visite"]) if a.get("derniere_visite") else None}
           for a in agents]
    return d, ags


def _bareme(drow):
    return json.loads(drow["bareme_json"])


def _proforma(drow, agents):
    b = _bareme(drow)
    d, ags = _pour_calcul(drow, agents)
    return M.calcul_proforma(d, ags, b["charges"], b)


def _derniere_visite_connue(con, nom, sauf_dossier=None):
    """Dernière visite médicale facturée (ou prévue) à cet agent dans un
    autre contrat non annulé : reprise automatique lors d'un renouvellement."""
    meilleur = None
    rows = con.execute(
        "SELECT a.*, d.date_debut, d.date_fin, d.visite_mode, d.id AS did FROM agents a "
        "JOIN dossiers d ON d.id = a.dossier_id JOIN interimaires i ON i.id = a.interimaire_id "
        "WHERE d.statut <> 'Annulé' AND i.cle = ?", (M.cle_nom(nom),)).fetchall()
    for r in rows:
        if sauf_dossier and r["did"] == sauf_dossier:
            continue
        b_val = con.execute("SELECT bareme_json FROM dossiers WHERE id = ?", (r["did"],)).fetchone()[0]
        val = json.loads(b_val).get("validite_visite_mois", 12)
        dern = dt.date.fromisoformat(r["derniere_visite"]) if r["derniere_visite"] else None
        vis = M.dates_visites(dt.date.fromisoformat(r["date_debut"]), dt.date.fromisoformat(r["date_fin"]),
                              dern, r["visite_mode"], val)
        cand = vis[-1] if vis else dern
        if cand and (meilleur is None or cand > meilleur):
            meilleur = cand
    # ancien intérimaire saisi à la main : dernière visite connue
    r = con.execute("SELECT derniere_visite FROM interimaires WHERE cle = ?", (M.cle_nom(nom),)).fetchone()
    if r and r[0]:
        cand = dt.date.fromisoformat(r[0])
        if meilleur is None or cand > meilleur:
            meilleur = cand
    return meilleur


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------
def etat(ctx, g, body):
    n = ctx["con"].execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0]
    return {"installation_requise": n == 0}


def installation(ctx, g, body):
    """Création du premier compte administrateur (seulement si aucun compte)."""
    con = ctx["con"]
    identifiant = texte(body, "identifiant", 40, True)
    nom = texte(body, "nom", 80, True)
    mdp = body.get("mot_de_passe")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", identifiant):
        raise ErreurAPI(400, "Identifiant : 3 à 40 caractères (lettres, chiffres, . _ -).")
    p = S.probleme_mdp(mdp, identifiant)
    if p:
        raise ErreurAPI(400, p)
    with Transaction(con):
        if con.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0] > 0:
            raise ErreurAPI(409, "L'installation est déjà faite.")
        con.execute("INSERT INTO utilisateurs(identifiant, nom, role, mdp_hash, cree_le) VALUES (?,?,?,?,?)",
                    (identifiant, nom, "admin", S.hacher_mdp(mdp), db.maintenant()))
        ctx["identifiant_tente"] = identifiant
        journaliser(ctx, "installation", identifiant, "Compte administrateur créé")
    return {"ok": True}


def connexion(ctx, g, body):
    con, ip = ctx["con"], ctx["ip"]
    identifiant = texte(body, "identifiant", 40, True)
    mdp = body.get("mot_de_passe")
    if not isinstance(mdp, str) or not mdp or len(mdp) > S.MDP_MAX:
        raise ErreurAPI(400, "Identifiant ou mot de passe incorrect.")
    ctx["identifiant_tente"] = identifiant
    if ctx["limiteur"].bloque(ip):
        raise ErreurAPI(429, "Trop de tentatives. Réessayez dans 15 minutes.")
    u = con.execute("SELECT * FROM utilisateurs WHERE identifiant = ?", (identifiant,)).fetchone()
    now = dt.datetime.now()
    if u is None:
        S.verifier_factice(mdp)
        ctx["limiteur"].echec(ip)
        with Transaction(con):
            journaliser(ctx, "connexion_echec", identifiant, "identifiant inconnu")
        raise ErreurAPI(401, "Identifiant ou mot de passe incorrect.")
    if u["bloque_jusqu"] and dt.datetime.fromisoformat(u["bloque_jusqu"]) > now:
        S.verifier_factice(mdp)
        raise ErreurAPI(423, "Compte bloqué temporairement après plusieurs erreurs. Réessayez dans 15 minutes.")
    ok = S.verifier_mdp(mdp, u["mdp_hash"])
    if not ok or not u["actif"]:
        ctx["limiteur"].echec(ip)
        with Transaction(con):
            echecs = u["echecs"] + 1
            bloque = None
            if echecs >= S.ECHECS_AVANT_BLOCAGE:
                bloque = (now + S.DUREE_BLOCAGE).replace(microsecond=0).isoformat(sep=" ")
                echecs = 0
            con.execute("UPDATE utilisateurs SET echecs = ?, bloque_jusqu = ? WHERE id = ?", (echecs, bloque, u["id"]))
            journaliser(ctx, "connexion_echec", identifiant, "compte désactivé" if ok else "mot de passe incorrect")
        raise ErreurAPI(401, "Identifiant ou mot de passe incorrect.")
    ctx["limiteur"].reussite(ip)
    jeton, csrf = S.nouveau_jeton(), S.nouveau_jeton()
    with Transaction(con):
        con.execute("UPDATE utilisateurs SET echecs = 0, bloque_jusqu = NULL, dernier_login = ? WHERE id = ?",
                    (db.maintenant(), u["id"]))
        con.execute("INSERT INTO sessions(token_hash, user_id, csrf, cree_le, vu_le) VALUES (?,?,?,?,?)",
                    (S.empreinte(jeton), u["id"], csrf, db.maintenant(), db.maintenant()))
        ctx["user"] = dict(u)
        journaliser(ctx, "connexion", identifiant)
    ctx["nouveau_cookie"] = jeton
    return {"utilisateur": _vue_user(u), "csrf": csrf}


def deconnexion(ctx, g, body):
    with Transaction(ctx["con"]):
        ctx["con"].execute("DELETE FROM sessions WHERE token_hash = ?", (ctx["session_hash"],))
        journaliser(ctx, "deconnexion")
    ctx["effacer_cookie"] = True
    return {"ok": True}


def _vue_user(u):
    return {"id": u["id"], "identifiant": u["identifiant"], "nom": u["nom"], "role": u["role"],
            "doit_changer_mdp": bool(u["doit_changer_mdp"])}


def moi(ctx, g, body):
    return {"utilisateur": _vue_user(ctx["user"]), "csrf": ctx["csrf"]}


def changer_mdp(ctx, g, body):
    con, u = ctx["con"], ctx["user"]
    actuel = body.get("actuel")
    nouveau = body.get("nouveau")
    if not isinstance(actuel, str) or not S.verifier_mdp(actuel, u["mdp_hash"]):
        raise ErreurAPI(400, "Mot de passe actuel incorrect.")
    p = S.probleme_mdp(nouveau, u["identifiant"])
    if p:
        raise ErreurAPI(400, p)
    if nouveau == actuel:
        raise ErreurAPI(400, "Choisissez un mot de passe différent de l'actuel.")
    with Transaction(con):
        con.execute("UPDATE utilisateurs SET mdp_hash = ?, doit_changer_mdp = 0 WHERE id = ?",
                    (S.hacher_mdp(nouveau), u["id"]))
        con.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (u["id"], ctx["session_hash"]))
        journaliser(ctx, "mot_de_passe_change", u["identifiant"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Utilisateurs (admin)
# ---------------------------------------------------------------------------
ROLES = ("admin", "gestion", "lecture")


def utilisateurs(ctx, g, body):
    rows = ctx["con"].execute("SELECT id, identifiant, nom, role, actif, dernier_login, bloque_jusqu, doit_changer_mdp "
                              "FROM utilisateurs ORDER BY identifiant").fetchall()
    return {"utilisateurs": [dict(r) for r in rows]}


def creer_utilisateur(ctx, g, body):
    con = ctx["con"]
    identifiant = texte(body, "identifiant", 40, True)
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", identifiant):
        raise ErreurAPI(400, "Identifiant : 3 à 40 caractères (lettres, chiffres, . _ -).")
    nom = texte(body, "nom", 80, True)
    role = body.get("role")
    if role not in ROLES:
        raise ErreurAPI(400, "Rôle invalide.")
    mdp = body.get("mot_de_passe")
    p = S.probleme_mdp(mdp, identifiant)
    if p:
        raise ErreurAPI(400, p)
    with Transaction(con):
        if con.execute("SELECT 1 FROM utilisateurs WHERE identifiant = ?", (identifiant,)).fetchone():
            raise ErreurAPI(409, "Cet identifiant existe déjà.")
        con.execute("INSERT INTO utilisateurs(identifiant, nom, role, mdp_hash, doit_changer_mdp, cree_le) "
                    "VALUES (?,?,?,?,1,?)", (identifiant, nom, role, S.hacher_mdp(mdp), db.maintenant()))
        journaliser(ctx, "utilisateur_cree", identifiant, role)
    return {"ok": True}


def modifier_utilisateur(ctx, g, body):
    con = ctx["con"]
    uid = int(g[0])
    u = con.execute("SELECT * FROM utilisateurs WHERE id = ?", (uid,)).fetchone()
    if not u:
        raise ErreurAPI(404, "Utilisateur introuvable.")
    nom = texte(body, "nom", 80, True, u["nom"])
    role = body.get("role", u["role"])
    if role not in ROLES:
        raise ErreurAPI(400, "Rôle invalide.")
    actif = body.get("actif", bool(u["actif"]))
    if not isinstance(actif, bool):
        raise ErreurAPI(400, "Champ « actif » invalide.")
    mdp = body.get("mot_de_passe")
    with Transaction(con):
        if (u["role"] == "admin") and (role != "admin" or not actif):
            n = con.execute("SELECT COUNT(*) FROM utilisateurs WHERE role = 'admin' AND actif = 1 AND id <> ?",
                            (uid,)).fetchone()[0]
            if n == 0:
                raise ErreurAPI(409, "Il doit rester au moins un administrateur actif.")
        con.execute("UPDATE utilisateurs SET nom = ?, role = ?, actif = ? WHERE id = ?", (nom, role, int(actif), uid))
        if mdp:
            p = S.probleme_mdp(mdp, u["identifiant"])
            if p:
                raise ErreurAPI(400, p)
            con.execute("UPDATE utilisateurs SET mdp_hash = ?, doit_changer_mdp = 1, echecs = 0, bloque_jusqu = NULL "
                        "WHERE id = ?", (S.hacher_mdp(mdp), uid))
        if mdp or not actif or role != u["role"]:
            con.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        journaliser(ctx, "utilisateur_modifie", u["identifiant"],
                    "rôle=%s actif=%s%s" % (role, actif, " mdp réinitialisé" if mdp else ""))
    return {"ok": True}


CHEMIN_SIGNATURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prive", "signature.png")


def signature(ctx, g, body):
    """Cachet + signature de la direction : servi seulement aux comptes
    connectés (direction, gestion), jamais comme fichier public."""
    try:
        with open(CHEMIN_SIGNATURE, "rb") as f:
            return Fichier(f.read(), "image/png")
    except OSError:
        raise ErreurAPI(404, "Aucune signature enregistrée.")


def journal(ctx, g, body):
    rows = ctx["con"].execute("SELECT quand, identifiant, action, objet, details FROM journal "
                              "ORDER BY id DESC LIMIT 500").fetchall()
    return {"journal": [dict(r) for r in rows]}


def sauvegarde(ctx, g, body):
    chemin = db.sauvegarder(ctx["chemin_db"], ctx["dossier_sauvegardes"])
    with Transaction(ctx["con"]):
        journaliser(ctx, "sauvegarde", chemin or "")
    return {"ok": True, "fichier": chemin}


# ---------------------------------------------------------------------------
# Paramètres et clients
# ---------------------------------------------------------------------------
CHAMPS_TEXTE_PARAM = {
    "raison_sociale": 80, "adresse": 120, "ville": 80, "telephone": 80, "email": 120, "rccm": 80,
    "nif": 40, "cnss": 40, "banque": 80, "compte": 60, "devise": 6, "modalite_reglement": 40, "heures": 120,
}
CHAMPS_ENTIER_PARAM = {
    "tva_pdm": (0, 5000), "validite_devis_jours": (1, 365), "delai_paiement_jours": (0, 365),
    "visite_ht": (0, 10_000_000), "validite_visite_mois": (1, 60), "dernier_num_proforma": (0, 10_000_000),
    "alerte_fin_jours": (1, 365), "alerte_visite_jours": (1, 365),
}


def lire_parametres(ctx, g, body):
    p = parametres(ctx["con"])
    return {"parametres": p, "charges": charges(ctx["con"]),
            "coefficient_pdm": M.coefficient_pdm(charges(ctx["con"])), "statuts": M.STATUTS}


def modifier_parametres(ctx, g, body):
    con = ctx["con"]
    p_in = body.get("parametres")
    if not isinstance(p_in, dict):
        raise ErreurAPI(400, "Paramètres manquants.")
    nouv = {}
    for k, mx in CHAMPS_TEXTE_PARAM.items():
        if k in p_in:
            nouv[k] = texte(p_in, k, mx, k in ("raison_sociale",))
    for k, (a, b) in CHAMPS_ENTIER_PARAM.items():
        if k in p_in:
            nouv[k] = entier(p_in, k, a, b)
    if "dernier_num_facture" in p_in:
        nouv["dernier_num_facture"] = entier(p_in, "dernier_num_facture", 0, 10_000_000, requis=False)
    for k in ("lieux", "services"):
        if k in p_in:
            v = p_in[k]
            if not isinstance(v, list) or len(v) > 50:
                raise ErreurAPI(400, "Liste « %s » invalide." % k)
            nouv[k] = [texte({"x": x}, "x", 60, True) for x in v if isinstance(x, str) and x.strip()]
    ch = body.get("charges")
    ch_ok = None
    if ch is not None:
        if not isinstance(ch, list) or not (1 <= len(ch) <= 20):
            raise ErreurAPI(400, "Liste des charges invalide.")
        ch_ok = [(texte(c, "libelle", 80, True), entier(c, "taux_pdm", 0, 100000)) for c in ch if isinstance(c, dict)]
        if len(ch_ok) != len(ch):
            raise ErreurAPI(400, "Liste des charges invalide.")
    with Transaction(con):
        avant = parametres(con)
        for k, v in nouv.items():
            con.execute("INSERT OR REPLACE INTO parametres(cle, valeur) VALUES (?, ?)", (k, json.dumps(v)))
        if ch_ok is not None:
            con.execute("DELETE FROM charges")
            for i, (lib, t) in enumerate(ch_ok):
                con.execute("INSERT INTO charges(ordre, libelle, taux_pdm) VALUES (?,?,?)", (i + 1, lib, t))
        diff = ["%s: %s → %s" % (k, avant.get(k), v) for k, v in nouv.items() if avant.get(k) != v]
        if ch_ok is not None:
            diff.append("charges: " + ", ".join("%s %s" % c for c in ch_ok))
        journaliser(ctx, "parametres_modifies", "", "; ".join(diff))
    return lire_parametres(ctx, g, body)


def clients(ctx, g, body):
    return {"clients": [dict(r) for r in ctx["con"].execute("SELECT * FROM clients ORDER BY code")]}


def _valider_client(body):
    return {
        "nom": texte(body, "nom", 120, True), "adresse": texte(body, "adresse", 120),
        "ville": texte(body, "ville", 80), "telephone": texte(body, "telephone", 60),
        "email": texte(body, "email", 120), "contact": texte(body, "contact", 120),
    }


def creer_client(ctx, g, body):
    con = ctx["con"]
    c = _valider_client(body)
    with Transaction(con):
        n = con.execute("SELECT COUNT(*) FROM clients").fetchone()[0] + 1
        code = "CLI%03d" % n
        while con.execute("SELECT 1 FROM clients WHERE code = ?", (code,)).fetchone():
            n += 1
            code = "CLI%03d" % n
        con.execute("INSERT INTO clients(code, nom, adresse, ville, telephone, email, contact) VALUES (?,?,?,?,?,?,?)",
                    (code, c["nom"], c["adresse"], c["ville"], c["telephone"], c["email"], c["contact"]))
        journaliser(ctx, "client_cree", code, c["nom"])
    return {"ok": True, "code": code}


def modifier_client(ctx, g, body):
    con = ctx["con"]
    cid = int(g[0])
    c = _valider_client(body)
    actif = body.get("actif", True)
    if not isinstance(actif, bool):
        raise ErreurAPI(400, "Champ « actif » invalide.")
    with Transaction(con):
        r = con.execute("SELECT code FROM clients WHERE id = ?", (cid,)).fetchone()
        if not r:
            raise ErreurAPI(404, "Client introuvable.")
        con.execute("UPDATE clients SET nom=?, adresse=?, ville=?, telephone=?, email=?, contact=?, actif=? WHERE id=?",
                    (c["nom"], c["adresse"], c["ville"], c["telephone"], c["email"], c["contact"], int(actif), cid))
        journaliser(ctx, "client_modifie", r["code"], c["nom"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Dossiers (DA -> proforma -> BC)
# ---------------------------------------------------------------------------
def _valider_dossier(con, body):
    d = {
        "client_id": entier(body, "client_id", 1),
        "num_da": texte(body, "num_da", 60),
        "service": texte(body, "service", 80, True),
        "imputation": texte(body, "imputation", 80),
        "lieu": texte(body, "lieu", 80, True),
        "date_debut": date_(body, "date_debut"),
        "date_fin": date_(body, "date_fin"),
        "visite_mode": body.get("visite_mode", "Auto"),
        "date_proforma": date_(body, "date_proforma", requis=False) or aujourdhui(),
        "notes": texte(body, "notes", 2000, multiligne=True),
    }
    if d["visite_mode"] not in ("Auto", "Non"):
        raise ErreurAPI(400, "Visite médicale : « Auto » ou « Non ».")
    if d["date_fin"] < d["date_debut"]:
        raise ErreurAPI(400, "La date de fin doit être après la date de début.")
    if (d["date_fin"] - d["date_debut"]).days > 366 * 5:
        raise ErreurAPI(400, "Période trop longue (5 ans maximum).")
    cl = con.execute("SELECT actif FROM clients WHERE id = ?", (d["client_id"],)).fetchone()
    if not cl:
        raise ErreurAPI(400, "Client inconnu.")
    ags = body.get("agents")
    if not isinstance(ags, list) or not ags:
        raise ErreurAPI(400, "Ajoutez au moins un agent.")
    if len(ags) > 20:
        raise ErreurAPI(400, "20 agents maximum par DA.")
    agents, noms = [], set()
    for i, a in enumerate(ags):
        if not isinstance(a, dict):
            raise ErreurAPI(400, "Agent %d invalide." % (i + 1))
        try:
            x = {"nom": texte(a, "nom", 120, True), "poste": texte(a, "poste", 120, True),
                 "salaire_base": entier(a, "salaire_base", 1, 100_000_000),
                 "derniere_visite": date_(a, "derniere_visite", requis=False)}
        except ErreurAPI as e:
            raise ErreurAPI(400, "Agent %d : %s" % (i + 1, e.message))
        cle = x["nom"].lower()
        if cle in noms:
            raise ErreurAPI(400, "L'agent « %s » est saisi deux fois." % x["nom"])
        noms.add(cle)
        agents.append(x)
    nom_num = texte(body, "nom_numero", 40) or M.premier_mot(agents[0]["nom"])
    nom_num = M.nom_pour_numero(nom_num)
    if not nom_num:
        raise ErreurAPI(400, "Nom dans le n° de proforma invalide.")
    d["nom_numero"] = nom_num
    return d, agents


def _bareme_actuel(con):
    p = parametres(con)
    return {"charges": charges(con), "visite_ht": p["visite_ht"], "tva_pdm": p["tva_pdm"],
            "validite_visite_mois": p["validite_visite_mois"]}


def prochain_num_da(con, annee):
    """N° de DA automatique quand la DA de COMILOG n'en a pas : DA-AAAA-001,
    DA-AAAA-002… (repart à 001 chaque année)."""
    mx = 0
    for (v,) in con.execute("SELECT num_da FROM dossiers WHERE num_da LIKE ?", ("DA-%d-%%" % annee,)):
        m = re.fullmatch(r"DA-%d-(\d+)" % annee, v or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return "DA-%d-%03d" % (annee, mx + 1)


def _verifier_num_da_libre(con, num_da, sauf=None):
    if not num_da:
        return
    r = con.execute("SELECT numero_proforma FROM dossiers WHERE lower(num_da) = lower(?) AND id <> ?",
                    (num_da, sauf or 0)).fetchone()
    if r:
        raise ErreurAPI(409, "Le n° de DA %s est déjà utilisé sur la proforma %s." % (num_da, r[0]))


def apercu_dossier(ctx, g, body):
    """Calcule la proforma sans rien enregistrer (aperçu en direct)."""
    con = ctx["con"]
    d, agents = _valider_dossier(con, body)
    b = _bareme_actuel(con)
    for a in agents:
        if a["derniere_visite"] is None:
            a["derniere_visite"] = _derniere_visite_connue(con, a["nom"])
    p = parametres(con)
    seq = int(p.get("dernier_num_proforma") or 0) + 1
    pro = M.calcul_proforma(d, agents, b["charges"], b)
    pro["numero_propose"] = M.numero_proforma(seq, d["date_proforma"], d["nom_numero"])
    pro["num_da_propose"] = d["num_da"] or prochain_num_da(con, d["date_proforma"].year)
    pro["dernieres_visites"] = [a["derniere_visite"].isoformat() if a["derniere_visite"] else None for a in agents]
    mats = []
    for a in agents:
        r = con.execute("SELECT matricule FROM interimaires WHERE cle = ?", (M.cle_nom(a["nom"]),)).fetchone()
        mats.append(r[0] if r else None)
    pro["matricules"] = mats
    return pro


def creer_dossier(ctx, g, body):
    con = ctx["con"]
    d, agents = _valider_dossier(con, body)
    with Transaction(con):
        p = parametres(con)
        mx = con.execute("SELECT COALESCE(MAX(num_seq), 0) FROM dossiers").fetchone()[0]
        seq = max(int(p.get("dernier_num_proforma") or 0), mx) + 1
        numero = M.numero_proforma(seq, d["date_proforma"], d["nom_numero"])
        if con.execute("SELECT 1 FROM dossiers WHERE numero_proforma = ?", (numero,)).fetchone():
            raise ErreurAPI(409, "Le n° de proforma %s existe déjà." % numero)
        if d["num_da"]:
            _verifier_num_da_libre(con, d["num_da"])
        else:
            d["num_da"] = prochain_num_da(con, d["date_proforma"].year)
        now = db.maintenant()
        cur = con.execute(
            "INSERT INTO dossiers(num_seq, numero_proforma, nom_numero, date_proforma, client_id, num_da, service, "
            "imputation, lieu, date_debut, date_fin, visite_mode, statut, notes, bareme_json, cree_par, cree_le, maj_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (seq, numero, d["nom_numero"], d["date_proforma"].isoformat(), d["client_id"], d["num_da"], d["service"],
             d["imputation"], d["lieu"], d["date_debut"].isoformat(), d["date_fin"].isoformat(), d["visite_mode"],
             "Brouillon", d["notes"], json.dumps(_bareme_actuel(con)), ctx["user"]["id"], now, now))
        did = cur.lastrowid
        for i, a in enumerate(agents):
            dv = a["derniere_visite"] or _derniere_visite_connue(con, a["nom"], did)
            con.execute("INSERT INTO agents(dossier_id, rang, nom, poste, salaire_base, derniere_visite, interimaire_id) "
                        "VALUES (?,?,?,?,?,?,?)", (did, i + 1, a["nom"], a["poste"], a["salaire_base"],
                                                  dv.isoformat() if dv else None, db.interimaire_id(con, a["nom"])))
        con.execute("INSERT OR REPLACE INTO parametres(cle, valeur) VALUES ('dernier_num_proforma', ?)", (json.dumps(seq),))
        journaliser(ctx, "dossier_cree", numero, "%d agent(s)" % len(agents))
    return {"id": did, "numero_proforma": numero, "num_da": d["num_da"]}


def _vue_dossier_resume(con, r):
    agents = _agents(con, r["id"])
    pro = _proforma(r, agents)
    cl = con.execute("SELECT code, nom FROM clients WHERE id = ?", (r["client_id"],)).fetchone()
    st = con.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN numero IS NOT NULL AND remplacee_par_id IS NULL THEN 1 ELSE 0 END) AS emises "
                     "FROM factures f JOIN agents a ON a.id = f.agent_id WHERE a.dossier_id = ?", (r["id"],)).fetchone()
    return {
        "id": r["id"], "numero_proforma": r["numero_proforma"], "date_proforma": r["date_proforma"],
        "client": cl["nom"] if cl else "", "service": r["service"], "lieu": r["lieu"], "num_da": r["num_da"],
        "date_debut": r["date_debut"], "date_fin": r["date_fin"], "statut": r["statut"],
        "agents": [a["nom"] for a in agents], "postes": [a["poste"] for a in agents],
        "matricules": [a["matricule"] for a in agents],
        "cumul_ht": pro["cumul_ht"], "bc_numero": r["bc_numero"], "bc_montant": r["bc_montant"],
        "ecart_bc": (r["bc_montant"] - pro["cumul_ht"]) if r["bc_montant"] is not None else None,
        "nb_factures": st["n"] or 0, "nb_emises": st["emises"] or 0,
    }


def liste_dossiers(ctx, g, body):
    con = ctx["con"]
    q = ctx["query"]
    sql = "SELECT * FROM dossiers"
    args = []
    cond = []
    statut = q.get("statut", "")
    if statut:
        if statut not in M.STATUTS:
            raise ErreurAPI(400, "Statut inconnu.")
        cond.append("statut = ?")
        args.append(statut)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY num_seq DESC LIMIT 2000"
    res = [_vue_dossier_resume(con, r) for r in con.execute(sql, args).fetchall()]
    rech = q.get("q", "").strip().lower()[:80]
    if rech:
        res = [x for x in res if rech in (" ".join([x["numero_proforma"], x["service"], x["lieu"], x["num_da"],
                                                     x["bc_numero"] or ""] + x["agents"] + x["postes"]
                                                    + [m or "" for m in x["matricules"]])).lower()]
    return {"dossiers": res}


def _factures_de(con, did):
    rows = con.execute(
        "SELECT f.*, a.nom AS agent, a.poste FROM factures f JOIN agents a ON a.id = f.agent_id "
        "WHERE a.dossier_id = ? ORDER BY f.mois, a.rang, CASE f.type WHEN 'VISITE' THEN 0 WHEN 'MAD' THEN 1 ELSE 2 END, f.id",
        (did,)).fetchall()
    auj = aujourdhui()
    res = []
    for r in rows:
        x = dict(r)
        x["statut"] = M.statut_facture(x, auj)
        res.append(x)
    return res


def detail_dossier(ctx, g, body):
    con = ctx["con"]
    r = _dossier_row(con, int(g[0]))
    agents = _agents(con, r["id"])
    pro = _proforma(r, agents)
    cl = dict(con.execute("SELECT * FROM clients WHERE id = ?", (r["client_id"],)).fetchone())
    d = dict(r)
    d["bareme"] = json.loads(d.pop("bareme_json"))
    factures = _factures_de(con, r["id"])
    return {"dossier": d, "agents": agents, "client": cl, "proforma": pro, "factures": factures,
            "ecart_bc": (r["bc_montant"] - pro["cumul_ht"]) if r["bc_montant"] is not None else None,
            "verrouille": any(f["numero"] for f in factures)}


def modifier_dossier(ctx, g, body):
    con = ctx["con"]
    did = int(g[0])
    d, agents = _valider_dossier(con, body)
    with Transaction(con):
        r = _dossier_row(con, did)
        if r["statut"] == "Annulé":
            raise ErreurAPI(409, "Ce dossier est annulé.")
        if d["num_da"]:
            _verifier_num_da_libre(con, d["num_da"], did)
        else:
            d["num_da"] = r["num_da"] or prochain_num_da(con, d["date_proforma"].year)
        emises = con.execute("SELECT COUNT(*) FROM factures f JOIN agents a ON a.id = f.agent_id "
                             "WHERE a.dossier_id = ? AND f.numero IS NOT NULL", (did,)).fetchone()[0]
        anciens = _agents(con, did)
        if emises:
            # Des factures sont émises : seuls les champs administratifs changent.
            meme = (len(anciens) == len(agents) and d["date_debut"].isoformat() == r["date_debut"]
                    and d["date_fin"].isoformat() == r["date_fin"] and d["visite_mode"] == r["visite_mode"]
                    and all(a["nom"] == b["nom"] and a["poste"] == b["poste"] and a["salaire_base"] == b["salaire_base"]
                            for a, b in zip(anciens, agents)))
            if not meme:
                raise ErreurAPI(409, "Des factures sont déjà émises : agents, salaires et dates ne peuvent plus "
                                     "changer. Pour un avenant, créez une nouvelle DA.")
            con.execute("UPDATE dossiers SET num_da=?, service=?, imputation=?, lieu=?, notes=?, client_id=?, maj_le=? "
                        "WHERE id=?", (d["num_da"], d["service"], d["imputation"], d["lieu"], d["notes"],
                                       d["client_id"], db.maintenant(), did))
        else:
            numero = M.numero_proforma(r["num_seq"], d["date_proforma"], d["nom_numero"])
            if con.execute("SELECT 1 FROM dossiers WHERE numero_proforma = ? AND id <> ?", (numero, did)).fetchone():
                raise ErreurAPI(409, "Le n° de proforma %s existe déjà." % numero)
            avait_factures = con.execute("SELECT COUNT(*) FROM factures f JOIN agents a ON a.id = f.agent_id "
                                         "WHERE a.dossier_id = ?", (did,)).fetchone()[0] > 0
            con.execute(
                "UPDATE dossiers SET numero_proforma=?, nom_numero=?, date_proforma=?, client_id=?, num_da=?, service=?, "
                "imputation=?, lieu=?, date_debut=?, date_fin=?, visite_mode=?, notes=?, maj_le=? WHERE id=?",
                (numero, d["nom_numero"], d["date_proforma"].isoformat(), d["client_id"], d["num_da"], d["service"],
                 d["imputation"], d["lieu"], d["date_debut"].isoformat(), d["date_fin"].isoformat(), d["visite_mode"],
                 d["notes"], db.maintenant(), did))
            con.execute("DELETE FROM agents WHERE dossier_id = ?", (did,))
            for i, a in enumerate(agents):
                dv = a["derniere_visite"] or _derniere_visite_connue(con, a["nom"], did)
                con.execute("INSERT INTO agents(dossier_id, rang, nom, poste, salaire_base, derniere_visite, interimaire_id) "
                            "VALUES (?,?,?,?,?,?,?)", (did, i + 1, a["nom"], a["poste"], a["salaire_base"],
                                                      dv.isoformat() if dv else None, db.interimaire_id(con, a["nom"])))
            if avait_factures:
                _generer(con, did)
        journaliser(ctx, "dossier_modifie", r["numero_proforma"])
    return {"ok": True}


def statut_dossier(ctx, g, body):
    con = ctx["con"]
    did = int(g[0])
    st = body.get("statut")
    if st not in M.STATUTS:
        raise ErreurAPI(400, "Statut inconnu.")
    with Transaction(con):
        r = _dossier_row(con, did)
        if st == "Annulé":
            emises = con.execute("SELECT COUNT(*) FROM factures f JOIN agents a ON a.id = f.agent_id "
                                 "WHERE a.dossier_id = ? AND f.numero IS NOT NULL", (did,)).fetchone()[0]
            if emises:
                raise ErreurAPI(409, "Des factures sont émises pour ce dossier : il ne peut pas être annulé.")
            con.execute("DELETE FROM factures WHERE numero IS NULL AND agent_id IN "
                        "(SELECT id FROM agents WHERE dossier_id = ?)", (did,))
        val = r["date_validation"]
        if st == "Validé" and not val:
            val = aujourdhui().isoformat()
        con.execute("UPDATE dossiers SET statut = ?, date_validation = ?, maj_le = ? WHERE id = ?",
                    (st, val, db.maintenant(), did))
        journaliser(ctx, "dossier_statut", r["numero_proforma"], "%s → %s" % (r["statut"], st))
    return {"ok": True}


def bc_dossier(ctx, g, body):
    con = ctx["con"]
    did = int(g[0])
    num = texte(body, "bc_numero", 20, True)
    if not re.fullmatch(r"\d{1,20}", num):
        raise ErreurAPI(400, "N° de BC : chiffres uniquement.")
    montant = entier(body, "bc_montant", 0, 10_000_000_000)
    dbc = date_(body, "bc_date", requis=False) or aujourdhui()
    with Transaction(con):
        r = _dossier_row(con, did)
        if r["statut"] == "Annulé":
            raise ErreurAPI(409, "Ce dossier est annulé.")
        autre = con.execute("SELECT numero_proforma FROM dossiers WHERE bc_numero = ? AND id <> ?", (num, did)).fetchone()
        if autre:
            raise ErreurAPI(409, "Ce n° de BC est déjà saisi sur la proforma %s." % autre[0])
        st = r["statut"]
        if st in ("Brouillon", "Envoyé", "Validé"):
            st = "BC reçu"
        con.execute("UPDATE dossiers SET bc_numero=?, bc_montant=?, bc_date=?, statut=?, maj_le=? WHERE id=?",
                    (num, montant, dbc.isoformat(), st, db.maintenant(), did))
        pro = _proforma(r, _agents(con, did))
        journaliser(ctx, "bc_saisi", r["numero_proforma"], "BC %s, %d XAF (écart %d)" % (num, montant, montant - pro["cumul_ht"]))
    return {"ok": True, "ecart": montant - pro["cumul_ht"]}


def _generer(con, did):
    """Crée ou met à jour les factures prévues (non émises) d'un dossier.
    Ne touche jamais une facture déjà numérotée. Renvoie le nb de lignes ajoutées."""
    r = _dossier_row(con, did)
    b = _bareme(r)
    d, _ = _pour_calcul(r, [])
    ajout = 0
    now = db.maintenant()
    for a in _agents(con, did):
        _, ags = _pour_calcul(r, [a])
        prevues = M.lignes_factures_agent(d, ags[0], b["charges"], b)
        cles = set()
        for l in prevues:
            mois = l["mois"].isoformat()
            cles.add((l["type"], mois))
            # visite médicale : pas de TVA (règle de Luc, 24/11/2026)
            t = 0 if l["type"] == M.TYPE_VISITE else M.tva(l["montant_ht"], b["tva_pdm"])
            ex = con.execute("SELECT id, numero FROM factures WHERE agent_id = ? AND type = ? AND mois = ?",
                             (a["id"], l["type"], mois)).fetchone()
            if ex is None:
                con.execute("INSERT INTO factures(agent_id, type, mois, jours, jours_mois, montant_ht, tva, ttc, cree_le) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", (a["id"], l["type"], mois, l["jours"], l["jours_mois"],
                                                           l["montant_ht"], t, l["montant_ht"] + t, now))
                ajout += 1
            elif ex["numero"] is None:
                con.execute("UPDATE factures SET jours=?, jours_mois=?, montant_ht=?, tva=?, ttc=? WHERE id=?",
                            (l["jours"], l["jours_mois"], l["montant_ht"], t, l["montant_ht"] + t, ex["id"]))
        for f in con.execute("SELECT id, type, mois FROM factures WHERE agent_id = ? AND numero IS NULL AND type <> 'BIS'",
                             (a["id"],)).fetchall():
            if (f["type"], f["mois"]) not in cles:
                con.execute("DELETE FROM factures WHERE id = ?", (f["id"],))
    return ajout


def generer_factures(ctx, g, body):
    con = ctx["con"]
    did = int(g[0])
    forcer = booleen(body, "forcer")
    with Transaction(con):
        r = _dossier_row(con, did)
        if r["statut"] == "Annulé":
            raise ErreurAPI(409, "Ce dossier est annulé.")
        if not forcer:
            if not r["bc_numero"]:
                raise ErreurAPI(409, "Aucun BC saisi : normalement on attend le BC avant de facturer.", "SANS_BC")
            pro = _proforma(r, _agents(con, did))
            ecart = r["bc_montant"] - pro["cumul_ht"]
            if abs(ecart) > 1:
                raise ErreurAPI(409, "Le montant du BC diffère du cumul de la proforma de %s XAF." % format(ecart, ",").replace(",", " "),
                                "ECART_BC")
        n = _generer(con, did)
        if r["statut"] in ("BC reçu", "Validé", "Envoyé", "Brouillon"):
            con.execute("UPDATE dossiers SET statut = 'En cours', maj_le = ? WHERE id = ?", (db.maintenant(), did))
        total = con.execute("SELECT COUNT(*) FROM factures f JOIN agents a ON a.id = f.agent_id WHERE a.dossier_id = ?",
                            (did,)).fetchone()[0]
        journaliser(ctx, "factures_generees", r["numero_proforma"], "%d ajoutée(s), %d au total" % (n, total))
    return {"ajoutees": n, "total": total}


# ---------------------------------------------------------------------------
# Factures
# ---------------------------------------------------------------------------
SQL_FACTURES = (
    "SELECT f.*, a.nom AS agent, i.matricule, a.poste, a.dossier_id, d.numero_proforma, d.bc_numero, d.imputation, d.service, "
    "d.lieu, d.date_debut, d.date_fin, d.statut AS statut_dossier, d.num_seq, a.rang, "
    "c.code AS client_code, c.nom AS client_nom, c.adresse AS client_adresse, c.ville AS client_ville, "
    "c.telephone AS client_telephone, c.email AS client_email "
    "FROM factures f JOIN agents a ON a.id = f.agent_id JOIN dossiers d ON d.id = a.dossier_id "
    "JOIN clients c ON c.id = d.client_id LEFT JOIN interimaires i ON i.id = a.interimaire_id ")
ORDRE_FACTURES = " ORDER BY f.mois, d.num_seq, a.rang, CASE f.type WHEN 'VISITE' THEN 0 WHEN 'MAD' THEN 1 ELSE 2 END, f.id"


def _vue_factures(rows):
    auj = aujourdhui()
    res = []
    for r in rows:
        x = dict(r)
        x["statut"] = M.statut_facture(x, auj)
        x["retard_jours"] = None
        if x["echeance"] and x["numero"] and not x["remplacee_par_id"]:
            fin = dt.date.fromisoformat(x["paye_le"]) if x["paye_le"] else auj
            x["retard_jours"] = max(0, (fin - dt.date.fromisoformat(x["echeance"])).days)
        res.append(x)
    return res


def liste_factures(ctx, g, body):
    con, q = ctx["con"], ctx["query"]
    cond, args = [], []
    if q.get("mois"):
        cond.append("f.mois = ?")
        args.append(mois_(q["mois"]).isoformat())
    if q.get("dossier"):
        if not q["dossier"].isdigit():
            raise ErreurAPI(400, "Dossier invalide.")
        cond.append("a.dossier_id = ?")
        args.append(int(q["dossier"]))
    if q.get("ids"):
        ids = [int(x) for x in q["ids"].split(",") if x.isdigit()][:1000]
        if not ids:
            raise ErreurAPI(400, "Sélection invalide.")
        cond.append("f.id IN (%s)" % ",".join("?" * len(ids)))
        args += ids
    sql = SQL_FACTURES + (" WHERE " + " AND ".join(cond) if cond else "") + ORDRE_FACTURES
    res = _vue_factures(con.execute(sql, args).fetchall())
    st = q.get("statut", "")
    if st:
        res = [x for x in res if x["statut"] == st]
    return {"factures": res}


def _dernier_num_facture(con):
    v = parametres(con).get("dernier_num_facture")
    if v is None:
        raise ErreurAPI(409, "Renseignez d'abord le dernier n° de facture réellement utilisé (Paramètres).",
                        "NUM_FACTURE_MANQUANT")
    mx = con.execute("SELECT COALESCE(MAX(num_seq), 0) FROM factures").fetchone()[0]
    return max(int(v), mx)


def emettre(ctx, g, body):
    """Attribue un n° et une date aux factures choisies : celles d'un mois (avec
    rattrapage des mois précédents non émis) ou une sélection."""
    con = ctx["con"]
    dfac = date_(body, "date_facture", requis=False) or aujourdhui()
    with Transaction(con):
        n = _dernier_num_facture(con)
        base = SQL_FACTURES + " WHERE f.numero IS NULL AND f.type <> 'BIS' AND d.statut <> 'Annulé'"
        if body.get("ids") is not None:
            ids = liste_ids(body)
            rows = con.execute(base + " AND f.id IN (%s)" % ",".join("?" * len(ids)) + ORDRE_FACTURES, ids).fetchall()
        else:
            m = mois_(body.get("mois"))
            if booleen(body, "rattrapage"):
                rows = con.execute(base + " AND f.mois <= ?" + ORDRE_FACTURES, (m.isoformat(),)).fetchall()
            else:
                rows = con.execute(base + " AND f.mois = ?" + ORDRE_FACTURES, (m.isoformat(),)).fetchall()
        p = parametres(con)
        ids_emis = []
        for r in rows:
            n += 1
            numero = M.numero_facture(n, r["type"], dt.date.fromisoformat(r["mois"]))
            if con.execute("SELECT 1 FROM factures WHERE numero = ?", (numero,)).fetchone():
                raise ErreurAPI(409, "Le n° %s existe déjà : vérifiez le dernier n° de facture." % numero)
            ech = M.echeance(dfac, p.get("delai_paiement_jours", 30))
            con.execute("UPDATE factures SET numero=?, num_seq=?, date_facture=?, echeance=? WHERE id=?",
                        (numero, n, dfac.isoformat(), ech.isoformat(), r["id"]))
            ids_emis.append(r["id"])
        if ids_emis:
            con.execute("INSERT OR REPLACE INTO parametres(cle, valeur) VALUES ('dernier_num_facture', ?)", (json.dumps(n),))
            journaliser(ctx, "factures_emises", "", "%d facture(s), jusqu'au n° %d" % (len(ids_emis), n))
    return {"emises": len(ids_emis), "ids": ids_emis}


def marquer_envoyees(ctx, g, body):
    con = ctx["con"]
    ids = liste_ids(body)
    d = date_(body, "date", requis=False) or aujourdhui()
    with Transaction(con):
        cur = con.execute("UPDATE factures SET envoyee_le = ? WHERE numero IS NOT NULL AND envoyee_le IS NULL "
                          "AND remplacee_par_id IS NULL AND id IN (%s)" % ",".join("?" * len(ids)), [d.isoformat()] + ids)
        journaliser(ctx, "factures_envoyees", "", "%d facture(s) le %s" % (cur.rowcount, d))
    return {"modifiees": cur.rowcount}


def paiement(ctx, g, body):
    con = ctx["con"]
    ids = liste_ids(body)
    d = date_(body, "date")
    ref = texte(body, "reference", 80)
    montant = entier(body, "montant", 0, 10_000_000_000, requis=False)
    if montant is not None and len(ids) != 1:
        raise ErreurAPI(400, "Un montant particulier ne peut être saisi que pour une seule facture.")
    with Transaction(con):
        n = 0
        for fid in ids:
            f = con.execute("SELECT * FROM factures WHERE id = ?", (fid,)).fetchone()
            if not f or not f["numero"] or f["remplacee_par_id"]:
                continue
            con.execute("UPDATE factures SET paye_le=?, montant_paye=?, ref_paiement=? WHERE id=?",
                        (d.isoformat(), montant if montant is not None else f["ttc"], ref, fid))
            n += 1
        journaliser(ctx, "paiement", ref, "%d facture(s) payée(s) le %s" % (n, d))
    return {"modifiees": n}


def annuler_paiement(ctx, g, body):
    con = ctx["con"]
    fid = int(g[0])
    with Transaction(con):
        f = con.execute("SELECT numero FROM factures WHERE id = ?", (fid,)).fetchone()
        if not f:
            raise ErreurAPI(404, "Facture introuvable.")
        con.execute("UPDATE factures SET paye_le=NULL, montant_paye=NULL, ref_paiement='' WHERE id=?", (fid,))
        journaliser(ctx, "paiement_annule", f["numero"] or fid)
    return {"ok": True}


def facture_bis(ctx, g, body):
    """Facture ajustée selon le PV de COMILOG : même n° + « bis », montant et
    date du PV. L'ancienne facture n'est plus comptée."""
    con = ctx["con"]
    fid = int(g[0])
    montant = entier(body, "montant_ht", 0, 10_000_000_000)
    dpv = date_(body, "date_pv")
    with Transaction(con):
        f = con.execute("SELECT * FROM factures WHERE id = ?", (fid,)).fetchone()
        if not f:
            raise ErreurAPI(404, "Facture introuvable.")
        if not f["numero"]:
            raise ErreurAPI(409, "Cette facture n'a pas encore de n° : régénérez simplement les factures.")
        if f["remplacee_par_id"]:
            raise ErreurAPI(409, "Cette facture est déjà remplacée.")
        if f["type"] == "BIS":
            raise ErreurAPI(409, "C'est déjà une facture bis.")
        if f["paye_le"]:
            raise ErreurAPI(409, "Cette facture est déjà payée.")
        r = con.execute("SELECT d.bareme_json FROM dossiers d JOIN agents a ON a.dossier_id = d.id WHERE a.id = ?",
                        (f["agent_id"],)).fetchone()
        tva_pdm = json.loads(r[0])["tva_pdm"]
        t = 0 if f["type"] == M.TYPE_VISITE else M.tva(montant, tva_pdm)
        num = M.numero_bis(f["numero"])
        if con.execute("SELECT 1 FROM factures WHERE numero = ?", (num,)).fetchone():
            raise ErreurAPI(409, "Le n° %s existe déjà." % num)
        p = parametres(con)
        cur = con.execute(
            "INSERT INTO factures(agent_id, type, mois, jours, jours_mois, montant_ht, tva, ttc, numero, num_seq, "
            "date_facture, echeance, pv_montant, pv_date, remplace_id, remarque, cree_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["agent_id"], "BIS", f["mois"], f["jours"], f["jours_mois"], montant, t, montant + t, num, None,
             dpv.isoformat(), M.echeance(dpv, p.get("delai_paiement_jours", 30)).isoformat(), montant,
             dpv.isoformat(), fid, "Remplace %s (PV du %s)" % (f["numero"], dpv.strftime("%d/%m/%Y")), db.maintenant()))
        con.execute("UPDATE factures SET remplacee_par_id = ?, pv_montant = ?, pv_date = ?, remarque = ? WHERE id = ?",
                    (cur.lastrowid, montant, dpv.isoformat(), "Remplacée par %s" % num, fid))
        journaliser(ctx, "facture_bis", num, "PV %d XAF HT (avant %d)" % (montant, f["montant_ht"]))
    return {"id": cur.lastrowid, "numero": num}


def remarque_facture(ctx, g, body):
    con = ctx["con"]
    fid = int(g[0])
    rq = texte(body, "remarque", 300)
    with Transaction(con):
        cur = con.execute("UPDATE factures SET remarque = ? WHERE id = ?", (rq, fid))
        if cur.rowcount == 0:
            raise ErreurAPI(404, "Facture introuvable.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------
def tableau_de_bord(ctx, g, body):
    con, q = ctx["con"], ctx["query"]
    auj = aujourdhui()
    m = mois_(q["mois"]) if q.get("mois") else M.debut_mois(auj)
    fm = M.fin_mois(m)
    p = parametres(con)
    dossiers = con.execute("SELECT * FROM dossiers WHERE statut <> 'Annulé'").fetchall()

    def prevu_mois(mm):
        """Montant HT prévu au prorata + visites dues sur le mois mm."""
        tot, vis, pers, attente = 0, 0, 0, 0
        fmm = M.fin_mois(mm)
        for r in dossiers:
            d1, d2 = dt.date.fromisoformat(r["date_debut"]), dt.date.fromisoformat(r["date_fin"])
            if d1 > fmm or d2 < mm:
                continue
            ags = _agents(con, r["id"])
            if r["statut"] not in M.STATUTS_EN_CONTRAT:
                attente += len(ags)
                continue
            b = _bareme(r)
            d, ags_c = _pour_calcul(r, ags)
            pers += len(ags)
            j = (min(d2, fmm) - max(d1, mm)).days + 1
            for a in ags_c:
                tot += M.montant_mois(M.cout_mensuel(a["salaire_base"], b["charges"]), j, M.jours_du_mois(mm))
                for v in M.dates_visites(d1, d2, a["derniere_visite"], r["visite_mode"], b["validite_visite_mois"]):
                    if M.debut_mois(v) == mm:
                        vis += b["visite_ht"]
        return tot, vis, pers, attente

    a_fact, visites, personnes, attente = prevu_mois(m)
    nouveaux = fins = 0
    alertes_fin, alertes_visite = [], []
    for r in dossiers:
        if r["statut"] not in M.STATUTS_EN_CONTRAT:
            continue
        d1, d2 = dt.date.fromisoformat(r["date_debut"]), dt.date.fromisoformat(r["date_fin"])
        ags = _agents(con, r["id"])
        if m <= d1 <= fm:
            nouveaux += len(ags)
        if m <= d2 <= fm:
            fins += len(ags)
        if auj <= d2 <= auj + dt.timedelta(days=int(p["alerte_fin_jours"])):
            for a in ags:
                alertes_fin.append({"dossier_id": r["id"], "agent": a["nom"], "fin": r["date_fin"],
                                    "jours": (d2 - auj).days})
        b = _bareme(r)
        _, ags_c = _pour_calcul(r, ags)
        for a, ac in zip(ags, ags_c):
            vis = M.dates_visites(d1, d2, ac["derniere_visite"], r["visite_mode"], b["validite_visite_mois"])
            suivantes = [v for v in vis if v >= auj]
            if suivantes and suivantes[0] <= auj + dt.timedelta(days=int(p["alerte_visite_jours"])):
                alertes_visite.append({"dossier_id": r["id"], "agent": a["nom"], "date": suivantes[0].isoformat(),
                                       "fin": r["date_fin"]})
    alertes_fin.sort(key=lambda x: x["fin"])
    fact = _vue_factures(con.execute(SQL_FACTURES + ORDRE_FACTURES).fetchall())
    valides = [f for f in fact if f["numero"] and not f["remplacee_par_id"]]
    du_mois = [f for f in valides if f["mois"] == m.isoformat()]
    a_emettre_passe = [f for f in fact if not f["numero"] and f["mois"] < m.isoformat() and f["type"] != "BIS"]
    a_emettre_mois = [f for f in fact if not f["numero"] and f["mois"] == m.isoformat() and f["type"] != "BIS"]
    ecarts_bc = []
    for r in dossiers:
        if r["bc_montant"] is not None:
            e = r["bc_montant"] - _proforma(r, _agents(con, r["id"]))["cumul_ht"]
            if abs(e) > 1:
                ecarts_bc.append({"dossier_id": r["id"], "numero": r["numero_proforma"], "ecart": e})
    serie = []
    for k in range(11, -1, -1):
        mm = M.ajouter_mois(m, -k)
        t, v, _, _ = prevu_mois(mm)
        serie.append({
            "mois": mm.isoformat(), "libelle": M.libelle_mois(mm), "a_facturer_ht": t + v,
            "facture_ht": sum(f["montant_ht"] for f in valides if f["mois"] == mm.isoformat()),
            "paye": sum(f["montant_paye"] or 0 for f in valides if f["mois"] == mm.isoformat()),
        })
    tot_fact = sum(f["ttc"] for f in valides)
    tot_paye = sum(f["montant_paye"] or 0 for f in valides)
    return {
        "mois": m.isoformat(), "libelle": M.libelle_mois(m),
        "personnes_en_contrat": personnes, "personnes_en_attente": attente,
        "nouveaux": nouveaux, "fins": fins,
        "a_facturer_ht": a_fact, "visites_ht": visites, "a_facturer_total_ht": a_fact + visites,
        "a_facturer_ttc": a_fact + visites + M.tva(a_fact, p["tva_pdm"]),
        "factures_emises": len(du_mois), "factures_envoyees": sum(1 for f in du_mois if f["envoyee_le"]),
        "factures_payees": sum(1 for f in du_mois if f["paye_le"]),
        "facture_ht": sum(f["montant_ht"] for f in du_mois), "facture_ttc": sum(f["ttc"] for f in du_mois),
        "paye": sum(f["montant_paye"] or 0 for f in du_mois),
        "impaye_mois": sum(f["ttc"] for f in du_mois) - sum(f["montant_paye"] or 0 for f in du_mois),
        "a_emettre_mois": len(a_emettre_mois), "a_emettre_rattrapage": len(a_emettre_passe),
        "total_facture_ttc": tot_fact, "total_paye": tot_paye, "reste_a_encaisser": tot_fact - tot_paye,
        "factures_en_retard": sum(1 for f in valides if f["statut"] == "En retard"),
        "montant_en_retard": sum(f["ttc"] for f in valides if f["statut"] == "En retard"),
        "alertes_fin": alertes_fin[:20], "alertes_visite": alertes_visite[:20], "ecarts_bc": ecarts_bc,
        "serie": serie, "num_facture_manquant": p.get("dernier_num_facture") is None,
        # « À faire » : ce qui attend une action de l'équipe, tous mois confondus
        "a_faire": {
            "a_emettre": sum(1 for f in fact if not f["numero"] and f["type"] != "BIS" and f["mois"] <= M.debut_mois(auj).isoformat()),
            "a_envoyer": sum(1 for f in valides if f["statut"] == "À envoyer"),
            "en_retard": sum(1 for f in valides if f["statut"] == "En retard"),
            "brouillons": sum(1 for r in dossiers if r["statut"] == "Brouillon"),
            "sans_bc": sum(1 for r in dossiers if r["statut"] in ("Envoyé", "Validé") and not r["bc_numero"]),
        },
    }


# ---------------------------------------------------------------------------
# Intérimaires (matricule fixe, interne : jamais imprimé sur les documents)
# ---------------------------------------------------------------------------
def liste_interimaires(ctx, g, body):
    con = ctx["con"]
    auj = aujourdhui().isoformat()
    res = []
    for i in con.execute("SELECT * FROM interimaires ORDER BY id"):
        rows = con.execute(
            "SELECT a.poste, d.id AS did, d.numero_proforma, d.date_debut, d.date_fin, d.statut, d.lieu "
            "FROM agents a JOIN dossiers d ON d.id = a.dossier_id WHERE a.interimaire_id = ? "
            "ORDER BY d.date_debut", (i["id"],)).fetchall()
        actifs = [r for r in rows if r["statut"] != "Annulé"]
        dern = actifs[-1] if actifs else (rows[-1] if rows else None)
        en_contrat = any(r["statut"] in M.STATUTS_EN_CONTRAT and r["date_debut"] <= auj <= r["date_fin"] for r in actifs)
        debuts = [x for x in [i["hist_debut"]] + [r["date_debut"] for r in actifs] if x]
        fins = [x for x in [i["hist_fin"]] + [r["date_fin"] for r in actifs] if x]
        res.append({"id": i["id"], "matricule": i["matricule"], "nom": i["nom"],
                    "nb_contrats": len(actifs) + (1 if i["hist_debut"] or i["hist_fin"] else 0),
                    "poste": dern["poste"] if dern else (i["poste"] or ""), "lieu": dern["lieu"] if dern else (i["lieu"] or ""),
                    "premier_debut": min(debuts) if debuts else None,
                    "derniere_fin": max(fins) if fins else None, "en_contrat": en_contrat,
                    "ancien": bool(i["hist_debut"] or i["hist_fin"] or i["poste"] or i["derniere_visite"]),
                    "fiche": {"poste": i["poste"] or "", "lieu": i["lieu"] or "", "hist_debut": i["hist_debut"],
                              "hist_fin": i["hist_fin"], "derniere_visite": i["derniere_visite"], "notes": i["notes"] or ""},
                    "dossiers": [{"id": r["did"], "numero_proforma": r["numero_proforma"], "statut": r["statut"]} for r in rows]})
    return {"interimaires": res}


def factures_word(ctx, g, body):
    """Factures émises en Word (.docx) modifiable : un .docx pour une
    facture, un .zip d'un .docx par facture pour une sélection."""
    con, q = ctx["con"], ctx["query"]
    ids = [int(x) for x in str(q.get("ids", "")).split(",") if x.isdigit()][:200]
    if not ids:
        raise ErreurAPI(400, "Aucune facture sélectionnée.")
    rows = con.execute(SQL_FACTURES + " WHERE f.id IN (%s)" % ",".join("?" * len(ids)) + ORDRE_FACTURES, ids).fetchall()
    fs = [dict(r) for r in rows if r["numero"]]
    if not fs:
        raise ErreurAPI(409, "Ces factures n'ont pas encore de n° : émettez-les d'abord.")
    p = parametres(con)
    fichiers, vus = [], set()
    for f in fs:
        nom = docx_facture.nom_fichier(f)
        while nom in vus:
            nom = nom[:-5] + "_" + str(f["id"]) + ".docx"
        vus.add(nom)
        fichiers.append((nom, docx_facture.facture_docx(p, f)))
    journaliser(ctx, "factures_word", ", ".join(f["numero"] for f in fs)[:300], "%d facture(s)" % len(fs))
    if len(fichiers) == 1:
        return Fichier(fichiers[0][1], docx_facture.MIME_DOCX, fichiers[0][0])
    mois = sorted({f["mois"][:7] for f in fs})
    clients = " + ".join(sorted({f["client_nom"] for f in fs}))
    return Fichier(docx_facture.lot_zip(fichiers), "application/zip", docx_facture.propre(
        "%s - Factures %s (%d).zip" % (clients, ", ".join(docx_facture.mois_fr(m + "-01") for m in mois), len(fichiers))))


def _valider_interimaire(body):
    nom = " ".join(texte(body, "nom", 120, requis=True).split())
    d = {"nom": nom, "poste": texte(body, "poste", 120), "lieu": texte(body, "lieu", 80),
         "hist_debut": date_(body, "hist_debut", requis=False), "hist_fin": date_(body, "hist_fin", requis=False),
         "derniere_visite": date_(body, "derniere_visite", requis=False), "notes": texte(body, "notes", 500, multiligne=True)}
    if d["hist_debut"] and d["hist_fin"] and d["hist_fin"] < d["hist_debut"]:
        raise ErreurAPI(400, "La date de fin est avant la date de début.")
    for k in ("hist_debut", "hist_fin", "derniere_visite"):
        d[k] = d[k].isoformat() if d[k] else None
    return d


def creer_interimaire(ctx, g, body):
    """Ajout d'un ancien intérimaire (historique) : reçoit un matricule, ne
    crée ni proforma ni facture. Sa dernière visite médicale est reprise à
    sa prochaine DA."""
    con = ctx["con"]
    d = _valider_interimaire(body)
    with Transaction(con):
        ex = con.execute("SELECT matricule FROM interimaires WHERE cle = ?", (M.cle_nom(d["nom"]),)).fetchone()
        if ex:
            raise ErreurAPI(409, "%s existe déjà (matricule %s) : modifiez sa fiche." % (d["nom"], ex[0]))
        iid = db.interimaire_id(con, d["nom"])
        con.execute("UPDATE interimaires SET poste=?, lieu=?, hist_debut=?, hist_fin=?, derniere_visite=?, notes=? WHERE id=?",
                    (d["poste"], d["lieu"], d["hist_debut"], d["hist_fin"], d["derniere_visite"], d["notes"], iid))
        mat = con.execute("SELECT matricule FROM interimaires WHERE id = ?", (iid,)).fetchone()[0]
        journaliser(ctx, "interimaire_ajoute", mat)
    return {"id": iid, "matricule": mat}


def modifier_interimaire(ctx, g, body):
    con = ctx["con"]
    iid = int(g[0])
    d = _valider_interimaire(body)
    with Transaction(con):
        r = con.execute("SELECT * FROM interimaires WHERE id = ?", (iid,)).fetchone()
        if not r:
            raise ErreurAPI(404, "Intérimaire introuvable.")
        cle = M.cle_nom(d["nom"])
        ex = con.execute("SELECT matricule FROM interimaires WHERE cle = ? AND id <> ?", (cle, iid)).fetchone()
        if ex:
            raise ErreurAPI(409, "Ce nom est déjà celui de %s." % ex[0])
        con.execute("UPDATE interimaires SET nom=?, cle=?, poste=?, lieu=?, hist_debut=?, hist_fin=?, derniere_visite=?, notes=? "
                    "WHERE id=?", (d["nom"], cle, d["poste"], d["lieu"], d["hist_debut"], d["hist_fin"],
                                   d["derniere_visite"], d["notes"], iid))
        journaliser(ctx, "interimaire_modifie", r["matricule"])
    return {"ok": True}


def _date_fr(iso):
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[:4]) if iso else ""


def _cellule_csv(v):
    """Cellule CSV pour Excel : séparateur « ; », guillemets doublés, et
    neutralisation des formules (=, +, -, @) pour éviter l'injection."""
    if v is None:
        return ""
    if isinstance(v, int):
        return str(v)
    t = str(v).replace("\r", " ").replace("\n", " ")
    if t[:1] in ("=", "+", "-", "@", "\t"):
        t = "'" + t
    if any(c in t for c in ';"'):
        t = '"' + t.replace('"', '""') + '"'
    return t


def factures_csv(ctx, g, body):
    """Liste des factures (mêmes filtres que l'écran) en CSV lisible par
    Excel et Numbers. Aucun salaire : seulement les montants facturés."""
    res = liste_factures(ctx, g, body)["factures"]
    entetes = ["N° facture", "Mois", "Type", "Agent", "Poste", "Client", "BC", "Montant HT", "TVA", "TTC",
               "Date facture", "Échéance", "Statut", "Envoyée le", "Payée le", "Réf. paiement", "Remarque"]
    types = {"MAD": "Mise à disposition", "VISITE": "Visite médicale", "BIS": "Facture bis (PV)"}
    lignes = [";".join(entetes)]
    for f in res:
        lignes.append(";".join(_cellule_csv(v) for v in (
            f["numero"] or "", M.libelle_mois(dt.date.fromisoformat(f["mois"])), types.get(f["type"], f["type"]),
            f["agent"], f["poste"], f["client_nom"], f["bc_numero"], f["montant_ht"], f["tva"], f["ttc"],
            _date_fr(f["date_facture"]), _date_fr(f["echeance"]), f["statut"], _date_fr(f["envoyee_le"]),
            _date_fr(f["paye_le"]), f["ref_paiement"],
            f["remarque"])))
    journaliser(ctx, "factures_export", "", "%d ligne(s)" % len(res))
    contenu = ("\ufeff" + "\r\n".join(lignes) + "\r\n").encode("utf-8")   # BOM : accents corrects dans Excel
    q = ctx["query"]
    nom = "Factures ANO Services - %s.csv" % (M.libelle_mois(mois_(q["mois"])) if q.get("mois") else "tous les mois")
    return Fichier(contenu, "text/csv; charset=utf-8", M.sans_accents(nom))
