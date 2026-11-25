"""Points d'entrée de l'API (logique applicative). Chaque fonction reçoit
le contexte de la requête (ctx), les groupes de l'URL et le corps JSON, et
renvoie un objet JSON. Les erreurs passent par ErreurAPI."""
import datetime as dt
import json
import os
import re
import unicodedata

import db
import docx_facture
import documents as DOC
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
    # en ligne : les comptes sont créés par l'administration de la plateforme
    return {"installation_requise": n == 0 and not ctx.get("en_ligne"), "multi": bool(ctx.get("multi"))}


def installation(ctx, g, body):
    """Création du premier compte administrateur (seulement si aucun compte,
    et jamais sur la version en ligne)."""
    if ctx.get("en_ligne"):
        raise ErreurAPI(403, "Installation fermée : compte créé par l'administration de la plateforme.")
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


# 1 pixel transparent : entreprise sans logo (jamais le logo d'une autre)
PNG_VIDE = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c48900"
                         "00000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082")
IMAGES_ENTREPRISE = {"logo": "logo.png", "signature": "signature.png"}
PNG = b"\x89PNG\r\n\x1a\n"


def televerser_image(ctx, g, body):
    """Logo ou cachet/signature de l'entreprise (direction seulement).
    PNG uniquement, 600 Ko au plus, rangé dans le dossier privé de
    l'entreprise (jamais public pour la signature)."""
    import base64
    import binascii
    quoi = g[0]
    if quoi not in IMAGES_ENTREPRISE:
        raise ErreurAPI(404, "Image inconnue.")
    b64 = body.get("png")
    if not isinstance(b64, str) or len(b64) > 820_000:
        raise ErreurAPI(400, "Image manquante ou trop lourde (600 Ko au plus).")
    try:
        data = base64.b64decode(b64.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise ErreurAPI(400, "Image illisible.")
    if not data.startswith(PNG) or len(data) > 600_000:
        raise ErreurAPI(400, "Format PNG attendu (600 Ko au plus).")
    os.makedirs(ctx["prive"], mode=0o700, exist_ok=True)
    cible = os.path.join(ctx["prive"], IMAGES_ENTREPRISE[quoi])
    tmp = cible + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, cible)
    with Transaction(ctx["con"]):
        journaliser(ctx, "image_entreprise", quoi, "%d octets" % len(data))
    return {"ok": True}


def signature(ctx, g, body):
    """Cachet + signature de la direction : servi seulement aux comptes
    connectés (direction, gestion), jamais comme fichier public."""
    try:
        with open(os.path.join(ctx["prive"], "signature.png"), "rb") as f:
            return Fichier(f.read(), "image/png")
    except OSError:
        raise ErreurAPI(404, "Aucune signature enregistrée.")


def logo(ctx, g, body):
    """Logo de l'entreprise de l'utilisateur connecté (documents, Paramètres)."""
    chemin = docx_facture.chemin_logo(ctx["prive"], ctx["origine"])
    if not chemin:
        return Fichier(PNG_VIDE, "image/png")
    with open(chemin, "rb") as f:
        return Fichier(f.read(), "image/png")


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
    "code_entreprise": 12, "prefixe_facture": 10, "code_mad": 20, "code_visite": 30,
}
# morceaux de n° : pas de « / » ni de « - » (ils séparent les parties du n°)
CHAMPS_CODE_PARAM = ("code_entreprise", "prefixe_facture", "code_mad", "code_visite")
CHAMPS_ENTIER_PARAM = {
    "tva_pdm": (0, 5000), "validite_devis_jours": (1, 365), "delai_paiement_jours": (0, 365),
    "visite_ht": (0, 10_000_000), "validite_visite_mois": (1, 60), "dernier_num_proforma": (0, 10_000_000),
    "alerte_fin_jours": (1, 365), "alerte_visite_jours": (1, 365), "bc_chiffres": (0, 20),
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
    for k in CHAMPS_CODE_PARAM:
        if k in nouv and any(c in nouv[k] for c in "/-\\"):
            raise ErreurAPI(400, "« %s » ne doit contenir ni « / » ni « - » (ils séparent les parties du n°)." % k)
    if "code_entreprise" in nouv and not M.nom_pour_numero(nouv["code_entreprise"]):
        raise ErreurAPI(400, "Code entreprise obligatoire (lettres ou chiffres, ex. ANO).")
    for k, (a, b) in CHAMPS_ENTIER_PARAM.items():
        if k in p_in:
            nouv[k] = entier(p_in, k, a, b)
    if "tva_visite" in p_in:
        nouv["tva_visite"] = booleen(p_in, "tva_visite")
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
# Recherche globale : dossiers, factures, documents, clients, intérimaires
# ---------------------------------------------------------------------------
TYPES_RECHERCHE = ("dossier", "facture", "document", "client", "interimaire")
STATUTS_FACTURE = ["À émettre", "À envoyer", "Envoyée", "En retard", "Payée", "Remplacée"]
LIBELLE_TYPE_FACTURE = {"MAD": "mise à disposition", "VISITE": "visite médicale", "BIS": "bis ajustée PV"}


def _normal(t):
    """Minuscules, sans accents, espaces des nombres retirés (6 921 000 = 6921000)."""
    t = unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"(?<=\d)[\s.  ](?=\d{3}\b)", "", t)


def _mots(q):
    return [m for m in _normal(q).split() if m]


def _trouve(mots, *champs):
    blob = _normal(" ".join(str(c) for c in champs if c not in (None, "")))
    blob += " " + blob.replace(" ", "")
    return all(m in blob for m in mots)


def _mois_lisible(m):
    try:
        d = dt.date.fromisoformat(m[:10])
        return "%s %d" % (M.MOIS_FR[d.month - 1], d.year)
    except (TypeError, ValueError):
        return ""


def recherche(ctx, g, body):
    """Recherche dans toute l'entreprise connectée (une seule base : rien d'une autre
    entreprise). Plusieurs mots = tous doivent se trouver. Filtres facultatifs :
    type, client, statut, période (du/au), montant HT (min/max). Rôle Lecture :
    factures seulement (pas de dossiers, documents ni intérimaires)."""
    con, q = ctx["con"], ctx["query"]
    texte_q = (q.get("q") or "").strip()[:120]
    mots = _mots(texte_q)
    type_ = q.get("type") or ""
    if type_ and type_ not in TYPES_RECHERCHE:
        raise ErreurAPI(400, "Type de recherche inconnu.")
    client = q.get("client") or ""
    if client and not client.isdigit():
        raise ErreurAPI(400, "Client invalide.")
    client = int(client) if client else None
    statut = q.get("statut") or ""
    if statut and statut not in M.STATUTS + STATUTS_FACTURE:
        raise ErreurAPI(400, "Statut inconnu.")
    du = date_(q, "du", requis=False)
    au = date_(q, "au", requis=False)
    mini = entier(q, "min", 0, 10_000_000_000, requis=False) if q.get("min") else None
    maxi = entier(q, "max", 0, 10_000_000_000, requis=False) if q.get("max") else None
    if not mots and not any([client, statut, du, au, mini is not None, maxi is not None]):
        return {"resultats": [], "total": 0, "tronque": False}
    lecture = ctx["user"]["role"] == "lecture"
    types = ("facture",) if lecture else TYPES_RECHERCHE
    if type_:
        types = tuple(t for t in types if t == type_)
    filtre_doc = statut or mini is not None or maxi is not None   # sans objet pour clients / intérimaires
    res = []

    def montant_ok(v):
        if mini is None and maxi is None:
            return True
        return v is not None and (mini is None or v >= mini) and (maxi is None or v <= maxi)

    def periode_ok(debut, fin=None):
        fin = fin or debut
        if not debut:
            return not (du or au)
        return (not du or fin >= du.isoformat()) and (not au or debut[:10] <= au.isoformat())

    if "dossier" in types:
        rows = con.execute(
            "SELECT d.id, d.numero_proforma, d.num_da, d.service, d.imputation, d.lieu, d.date_debut, d.date_fin, "
            "d.date_proforma, d.statut, d.bc_numero, d.bc_montant, d.notes, d.client_id, c.nom AS client_nom, "
            "(SELECT GROUP_CONCAT(a.nom || ' ' || a.poste || ' ' || COALESCE(i.matricule, ''), ' | ') FROM agents a "
            " LEFT JOIN interimaires i ON i.id = a.interimaire_id WHERE a.dossier_id = d.id) AS agents, "
            "(SELECT GROUP_CONCAT(a.nom, ' | ') FROM agents a WHERE a.dossier_id = d.id) AS noms, "
            "(SELECT COUNT(*) FROM agents a WHERE a.dossier_id = d.id) AS nb_agents "
            "FROM dossiers d JOIN clients c ON c.id = d.client_id ORDER BY d.num_seq DESC").fetchall()
        for d in rows:
            if client and d["client_id"] != client or statut and d["statut"] != statut:
                continue
            if not periode_ok(d["date_debut"], d["date_fin"]) or not montant_ok(d["bc_montant"]):
                continue
            if mots and not _trouve(mots, d["numero_proforma"], d["num_da"], d["service"], d["imputation"], d["lieu"],
                                    d["bc_numero"], d["client_nom"], d["agents"], d["notes"], d["statut"]):
                continue
            noms = (d["noms"] or "").split(" | ")
            res.append({"type": "dossier", "id": d["id"], "titre": d["numero_proforma"], "statut": d["statut"],
                        "detail": "%s · %s · %s · %d agent(s)%s" % (d["client_nom"], d["service"], d["lieu"], d["nb_agents"],
                                                                    (" · BC " + d["bc_numero"]) if d["bc_numero"] else ""),
                        "agents": ", ".join(noms[:3]) + (" …" if len(noms) > 3 else ""),
                        "date": d["date_debut"], "date_fin": d["date_fin"], "montant_ht": d["bc_montant"],
                        "lien": "#/dossier/%d" % d["id"]})

    if "facture" in types:
        client_de = dict(con.execute("SELECT id, client_id FROM dossiers").fetchall())
        for f in _vue_factures(con.execute(SQL_FACTURES + ORDRE_FACTURES).fetchall(), con):
            if client and client_de[f["dossier_id"]] != client:
                continue
            if statut and f["statut"] != statut:
                continue
            if not periode_ok(f["date_facture"] or f["mois"]) or not montant_ok(f["montant_ht"]):
                continue
            if mots and not _trouve(mots, f["numero"], f["agent"], f.get("matricule"), f["client_nom"], f["bc_numero"],
                                    f["numero_proforma"], f["service"], f["lieu"], _mois_lisible(f["mois"]),
                                    LIBELLE_TYPE_FACTURE.get(f["type"]), f["montant_ht"], f["ttc"], f["ref_paiement"],
                                    f["remarque"], f["statut"], "facture"):
                continue
            res.append({"type": "facture", "id": f["id"], "titre": f["numero"] or "Facture prévue (pas encore émise)",
                        "statut": f["statut"], "detail": "%s · %s · %s" % (f["client_nom"], LIBELLE_TYPE_FACTURE.get(f["type"], ""),
                                                                          _mois_lisible(f["mois"])),
                        "agents": f["agent"], "date": f["date_facture"] or f["mois"], "montant_ht": f["montant_ht"],
                        "ttc": f["ttc"], "dossier_id": f["dossier_id"],
                        "lien": ("#/imprimer/factures/%d" % f["id"]) if f["numero"] and f["statut"] != "Remplacée"
                        else ("#/factures" if lecture else "#/dossier/%d" % f["dossier_id"])})

    if "document" in types and not filtre_doc:
        rows = con.execute(
            "SELECT o.id, o.categorie, o.nom, o.ajoute_le, o.taille, o.dossier_id, d.numero_proforma, d.bc_numero, d.client_id, "
            "c.nom AS client_nom, f.numero AS facture_numero, "
            "(SELECT GROUP_CONCAT(a.nom, ' | ') FROM agents a WHERE a.dossier_id = d.id) AS agents "
            "FROM documents o JOIN dossiers d ON d.id = o.dossier_id JOIN clients c ON c.id = d.client_id "
            "LEFT JOIN factures f ON f.id = o.facture_id WHERE o.retire_le IS NULL ORDER BY o.ajoute_le DESC, o.id DESC").fetchall()
        for o in rows:
            if client and o["client_id"] != client or not periode_ok(o["ajoute_le"][:10]):
                continue
            if mots and not _trouve(mots, o["categorie"], o["nom"], o["numero_proforma"], o["bc_numero"], o["client_nom"],
                                    o["facture_numero"], o["agents"], "document piece"):
                continue
            res.append({"type": "document", "id": o["id"], "titre": o["nom"], "statut": o["categorie"],
                        "detail": "%s · %s" % (o["client_nom"], o["numero_proforma"]), "date": o["ajoute_le"][:10],
                        "taille": o["taille"], "dossier_id": o["dossier_id"],
                        "lien": "/api/documents/%d" % o["id"], "lien_dossier": "#/dossier/%d" % o["dossier_id"]})

    if "client" in types and not filtre_doc and not (du or au):
        for c in con.execute("SELECT * FROM clients ORDER BY nom").fetchall():
            if client and c["id"] != client:
                continue
            if mots and not _trouve(mots, c["code"], c["nom"], c["ville"], c["adresse"], c["contact"], c["email"], c["telephone"]):
                continue
            if not mots and not client:
                continue
            res.append({"type": "client", "id": c["id"], "titre": c["nom"], "statut": "Actif" if c["actif"] else "Inactif",
                        "detail": " · ".join(x for x in (c["ville"], c["contact"], c["telephone"], c["email"]) if x),
                        "lien": "#/clients"})

    if "interimaire" in types and not filtre_doc and not (du or au) and not client and mots:
        for i in con.execute(
                "SELECT i.id, i.matricule, i.nom, (SELECT GROUP_CONCAT(DISTINCT a.poste) FROM agents a WHERE a.interimaire_id = i.id) "
                "AS postes, (SELECT MAX(a.dossier_id) FROM agents a WHERE a.interimaire_id = i.id) AS dernier, "
                "(SELECT COUNT(DISTINCT a.dossier_id) FROM agents a WHERE a.interimaire_id = i.id) AS nb "
                "FROM interimaires i ORDER BY i.nom").fetchall():
            if not _trouve(mots, i["matricule"], i["nom"], i["postes"]):
                continue
            res.append({"type": "interimaire", "id": i["id"], "titre": i["nom"], "statut": i["matricule"],
                        "detail": "%s · %d dossier(s)" % (i["postes"] or "", i["nb"]),
                        "lien": ("#/dossier/%d" % i["dernier"]) if i["dernier"] else "#/interimaires"})

    # le plus pertinent d'abord : n° / nom qui contient toute la recherche, puis tous les mots dans le titre
    if mots:
        entier_q = "".join(mots)

        def rang(r):
            t = _normal(r["titre"])
            if entier_q in t.replace(" ", ""):
                return 0
            t += " " + _normal("%s %s" % (r.get("detail", ""), r.get("agents", "")))
            return 1 if all(m in t for m in mots) else 2
        res.sort(key=rang)      # tri stable : à pertinence égale, dossiers, factures, documents, clients, intérimaires
    total = len(res)
    return {"resultats": res[:300], "total": total, "tronque": total > 300}

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
        "facture_groupee": 1 if booleen(body, "facture_groupee") else 0,
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
    if d["facture_groupee"] and len(ags) < 2:
        d["facture_groupee"] = 0          # un seul agent : rien à regrouper
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
            "validite_visite_mois": p["validite_visite_mois"], "tva_visite": bool(p.get("tva_visite", False))}


def _tva_ligne(type_, ht, bareme):
    """Visite médicale sans TVA, sauf si l'entreprise l'a réglé autrement
    (barème figé dans le dossier ; anciens dossiers : sans TVA)."""
    if type_ == M.TYPE_VISITE and not bareme.get("tva_visite"):
        return 0
    return M.tva(ht, bareme["tva_pdm"])


def _codes_facture(p):
    return {"prefixe": p.get("prefixe_facture", "FA"), "code_mad": p.get("code_mad", ""),
            "code_visite": p.get("code_visite", "Visite médicale")}


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
    pro["numero_propose"] = M.numero_proforma(seq, d["date_proforma"], d["nom_numero"], p.get("code_entreprise", "ANO"))
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
        numero = M.numero_proforma(seq, d["date_proforma"], d["nom_numero"], p.get("code_entreprise", "ANO"))
        if con.execute("SELECT 1 FROM dossiers WHERE numero_proforma = ?", (numero,)).fetchone():
            raise ErreurAPI(409, "Le n° de proforma %s existe déjà." % numero)
        if d["num_da"]:
            _verifier_num_da_libre(con, d["num_da"])
        else:
            d["num_da"] = prochain_num_da(con, d["date_proforma"].year)
        now = db.maintenant()
        cur = con.execute(
            "INSERT INTO dossiers(num_seq, numero_proforma, nom_numero, date_proforma, client_id, num_da, service, "
            "imputation, lieu, date_debut, date_fin, visite_mode, statut, notes, bareme_json, cree_par, cree_le, maj_le, "
            "facture_groupee) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (seq, numero, d["nom_numero"], d["date_proforma"].isoformat(), d["client_id"], d["num_da"], d["service"],
             d["imputation"], d["lieu"], d["date_debut"].isoformat(), d["date_fin"].isoformat(), d["visite_mode"],
             "Brouillon", d["notes"], json.dumps(_bareme_actuel(con)), ctx["user"]["id"], now, now, d["facture_groupee"]))
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
        "matricules": [a["matricule"] for a in agents], "salaires": [a["salaire_base"] for a in agents],
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
    ags = None
    for r in rows:
        x = dict(r)
        x["statut"] = M.statut_facture(x, auj)
        if x.get("groupe"):
            if ags is None:
                ags = [g["nom"] for g in con.execute("SELECT nom FROM agents WHERE dossier_id = ? ORDER BY rang", (did,))]
            x["agent"], x["nb_agents"] = M.noms_groupe(ags), len(ags)
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
        # La proforma reste modifiable même après émission (demande de Luc, 25/11/2026) :
        # les factures déjà émises ne changent pas (montants figés) ; les factures
        # prévues sont recalculées. Un agent qui a des factures émises ne peut pas être retiré.
        # Un n° de facture émis reste lié à SON agent (règle de Luc, 25/11/2026) : les agents
        # sont retrouvés par leur nom (sans tenir compte des accents ni des majuscules), pas
        # par leur place dans la liste. Un agent qui a des factures émises ne peut être ni
        # retiré ni remplacé par une autre personne.
        libres = list(anciens)
        correspond = []
        for a in agents:
            k = M.cle_nom(a["nom"])
            ancien = next((x for x in libres if M.cle_nom(x["nom"]) == k), None)
            if ancien is not None:
                libres.remove(ancien)
            correspond.append(ancien)
        for a in libres:
            nums = [x[0] for x in con.execute("SELECT numero FROM factures WHERE agent_id = ? AND numero IS NOT NULL "
                                              "ORDER BY num_seq", (a["id"],)).fetchall()]
            if nums:
                raise ErreurAPI(409, "L'agent « %s » a des factures émises (%s) : il ne peut être ni retiré ni remplacé, "
                                     "car un n° de facture reste lié à son agent. Gardez-le dans la liste (les accents et "
                                     "majuscules de son nom peuvent être corrigés)." % (a["nom"], ", ".join(nums[:3])
                                                                                      + (" …" if len(nums) > 3 else "")))
        # le code entreprise d'origine est gardé (repris du n° existant)
        code = r["numero_proforma"].split("-")[2] if r["numero_proforma"].count("-") >= 3 else "ANO"
        numero = M.numero_proforma(r["num_seq"], d["date_proforma"], d["nom_numero"], code)
        if con.execute("SELECT 1 FROM dossiers WHERE numero_proforma = ? AND id <> ?", (numero, did)).fetchone():
            raise ErreurAPI(409, "Le n° de proforma %s existe déjà." % numero)
        avait_factures = con.execute("SELECT COUNT(*) FROM factures f JOIN agents a ON a.id = f.agent_id "
                                     "WHERE a.dossier_id = ?", (did,)).fetchone()[0] > 0
        con.execute(
            "UPDATE dossiers SET numero_proforma=?, nom_numero=?, date_proforma=?, client_id=?, num_da=?, service=?, "
            "imputation=?, lieu=?, date_debut=?, date_fin=?, visite_mode=?, notes=?, maj_le=?, facture_groupee=? WHERE id=?",
            (numero, d["nom_numero"], d["date_proforma"].isoformat(), d["client_id"], d["num_da"], d["service"],
             d["imputation"], d["lieu"], d["date_debut"].isoformat(), d["date_fin"].isoformat(), d["visite_mode"],
             d["notes"], db.maintenant(), d["facture_groupee"], did))
        # même personne = même ligne d'agent : ses factures (et leurs n°) la suivent, quel que soit l'ordre
        for a in libres:
            con.execute("DELETE FROM factures WHERE agent_id = ? AND numero IS NULL", (a["id"],))
            con.execute("DELETE FROM agents WHERE id = ?", (a["id"],))
        for i, a in enumerate(agents):
            dv = a["derniere_visite"] or _derniere_visite_connue(con, a["nom"], did)
            vals = (a["nom"], a["poste"], a["salaire_base"], dv.isoformat() if dv else None, db.interimaire_id(con, a["nom"]))
            if correspond[i] is not None:
                con.execute("UPDATE agents SET nom=?, poste=?, salaire_base=?, derniere_visite=?, interimaire_id=?, rang=? "
                            "WHERE id=?", vals + (i + 1, correspond[i]["id"]))
            else:
                con.execute("INSERT INTO agents(nom, poste, salaire_base, derniere_visite, interimaire_id, dossier_id, rang) "
                            "VALUES (?,?,?,?,?,?,?)", vals + (did, i + 1))
        if avait_factures:
            _generer(con, did)
        journaliser(ctx, "dossier_modifie", numero,
                    ("%d facture(s) émise(s) gardée(s) telles quelles" % emises) if emises else "")
    return {"ok": True, "emises_gardees": emises}


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
    agents = _agents(con, did)
    groupee = bool(r["facture_groupee"])
    if groupee:
        _, tous = _pour_calcul(r, agents)
        lignes_groupe = M.lignes_factures_groupe(d, tous, b["charges"], b)
    for a in agents:
        if groupee:
            # facture groupée : rattachée au 1er agent, les autres n'ont pas de facture à eux
            prevues = lignes_groupe if a["rang"] == 1 else []
        else:
            _, ags = _pour_calcul(r, [a])
            prevues = M.lignes_factures_agent(d, ags[0], b["charges"], b)
        cles = set()
        for l in prevues:
            mois = l["mois"].isoformat()
            cles.add((l["type"], mois))
            # visite médicale : pas de TVA par défaut (règle de Luc, 24/11/2026), réglable
            t = _tva_ligne(l["type"], l["montant_ht"], b)
            ex = con.execute("SELECT id, numero, modifiee_le FROM factures WHERE agent_id = ? AND type = ? AND mois = ?",
                             (a["id"], l["type"], mois)).fetchone()
            if ex is None:
                con.execute("INSERT INTO factures(agent_id, type, mois, jours, jours_mois, montant_ht, tva, ttc, groupe, cree_le) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?)", (a["id"], l["type"], mois, l["jours"], l["jours_mois"],
                                                             l["montant_ht"], t, l["montant_ht"] + t, int(groupee), now))
                ajout += 1
            elif ex["numero"] is None and ex["modifiee_le"] is None:   # corrigée à la main : on n'y touche pas
                con.execute("UPDATE factures SET jours=?, jours_mois=?, montant_ht=?, tva=?, ttc=?, groupe=? WHERE id=?",
                            (l["jours"], l["jours_mois"], l["montant_ht"], t, l["montant_ht"] + t, int(groupee), ex["id"]))
        for f in con.execute("SELECT id, type, mois FROM factures WHERE agent_id = ? AND numero IS NULL AND type <> 'BIS' "
                             "AND modifiee_le IS NULL",
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
    "c.telephone AS client_telephone, c.email AS client_email, "
    "(SELECT COUNT(*) FROM agents x WHERE x.dossier_id = a.dossier_id) AS nb_agents_dossier "
    "FROM factures f JOIN agents a ON a.id = f.agent_id JOIN dossiers d ON d.id = a.dossier_id "
    "JOIN clients c ON c.id = d.client_id LEFT JOIN interimaires i ON i.id = a.interimaire_id ")
ORDRE_FACTURES = " ORDER BY f.mois, d.num_seq, a.rang, CASE f.type WHEN 'VISITE' THEN 0 WHEN 'MAD' THEN 1 ELSE 2 END, f.id"


def _vue_factures(rows, con=None):
    auj = aujourdhui()
    res = []
    noms = {}
    for r in rows:
        x = dict(r)
        if x.get("groupe") and con is not None:
            if x["dossier_id"] not in noms:
                ags = con.execute("SELECT nom, poste FROM agents WHERE dossier_id = ? ORDER BY rang",
                                  (x["dossier_id"],)).fetchall()
                noms[x["dossier_id"]] = ags
            ags = noms[x["dossier_id"]]
            x["agents_groupe"] = [g["nom"] for g in ags]
            x["agent"] = M.noms_groupe([g["nom"] for g in ags])
            x["nb_agents"] = len(ags)
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
    res = _vue_factures(con.execute(sql, args).fetchall(), con)
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
        # visite médicale et facture du mois émises ensemble pour le même agent (ou le
        # même groupe) et le même mois : un seul n° (FA 159/11/2026 + FA 159/Visite médicale/2026)
        paire = {}
        for r in rows:
            cle = (r["agent_id"], r["mois"])
            # la visite (ou la facture du mois) de ce même agent et de ce même mois a déjà son n° :
            # l'autre reprend ce n°, qui reste lié à l'agent (ex. FA 87/Visite médicale/2026 puis FA 87/12/2026)
            deja = None
            if r["type"] in ("MAD", "VISITE") and cle not in paire:
                autre = "VISITE" if r["type"] == "MAD" else "MAD"
                deja = con.execute(
                    "SELECT f.num_seq FROM factures f WHERE f.agent_id = ? AND f.mois = ? AND f.type = ? AND f.num_seq IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM factures g WHERE g.num_seq = f.num_seq AND g.id <> f.id AND g.type <> 'BIS')",
                    (r["agent_id"], r["mois"], autre)).fetchone()
            if deja is not None:
                num_seq = deja[0]
            elif cle in paire and paire[cle][1] != r["type"] and r["type"] in ("MAD", "VISITE"):
                num_seq = paire.pop(cle)[0]
            else:
                n += 1
                num_seq = n
                paire[cle] = (n, r["type"])
            numero = M.numero_facture(num_seq, r["type"], dfac, **_codes_facture(p))
            if con.execute("SELECT 1 FROM factures WHERE numero = ?", (numero,)).fetchone():
                raise ErreurAPI(409, "Le n° %s existe déjà : vérifiez le dernier n° de facture." % numero)
            ech = M.echeance(dfac, p.get("delai_paiement_jours", 30))
            con.execute("UPDATE factures SET numero=?, num_seq=?, date_facture=?, echeance=? WHERE id=?",
                        (numero, num_seq, dfac.isoformat(), ech.isoformat(), r["id"]))
            ids_emis.append(r["id"])
        if ids_emis:
            con.execute("INSERT OR REPLACE INTO parametres(cle, valeur) VALUES ('dernier_num_facture', ?)", (json.dumps(n),))
            journaliser(ctx, "factures_emises", "", "%d facture(s), jusqu'au n° %d" % (len(ids_emis), n))
    archivees = _archiver_factures(ctx, ids_emis)
    return {"emises": len(ids_emis), "ids": ids_emis, "archivees": archivees}


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
            # un montant plus grand que le TTC reste permis (choix de Luc, 25/11/2026) :
            # le tableau de bord le signale sans le compter dans le reste à encaisser
            if montant == 0:
                raise ErreurAPI(400, "Montant reçu à 0 : laissez vide pour le TTC complet.")
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
        t = _tva_ligne(f["type"], montant, json.loads(r[0]))
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
    _archiver_factures(ctx, [cur.lastrowid])
    return {"id": cur.lastrowid, "numero": num}


def modifier_facture(ctx, g, body):
    """Corriger une facture, émise ou non (demande de Luc et Lola, 25/11/2026) :
    quantité, unité, montant HT, date, remarque. Le n° ne change jamais ; la TVA
    et le TTC sont recalculés ; une nouvelle copie figée est gardée ; le journal
    note l'avant / après. Une facture payée ou remplacée ne se modifie pas."""
    con = ctx["con"]
    fid = int(g[0])
    with Transaction(con):
        f = con.execute(SQL_FACTURES + " WHERE f.id = ?", (fid,)).fetchone()
        if not f:
            raise ErreurAPI(404, "Facture introuvable.")
        if f["remplacee_par_id"]:
            raise ErreurAPI(409, "Cette facture est remplacée par une facture bis : modifiez la bis.")
        if f["paye_le"]:
            raise ErreurAPI(409, "Cette facture est payée : annulez d'abord le paiement pour la modifier.")
        if f["statut_dossier"] == "Annulé":
            raise ErreurAPI(409, "Ce dossier est annulé.")
        ht = entier(body, "montant_ht", 0, 10_000_000_000)
        jours = entier(body, "jours", 0, 1000, requis=False, defaut=f["jours"])
        unite = texte(body, "unite", 20, defaut=f["unite"])
        rq = texte(body, "remarque", 300, defaut=f["remarque"]) if "remarque" in body else f["remarque"]
        dfac = date_(body, "date_facture", requis=False) if f["numero"] else None
        r = con.execute("SELECT d.bareme_json FROM dossiers d JOIN agents a ON a.dossier_id = d.id WHERE a.id = ?",
                        (f["agent_id"],)).fetchone()
        t = _tva_ligne(f["type"], ht, json.loads(r[0]))
        dfac_iso = dfac.isoformat() if dfac else f["date_facture"]
        ech = f["echeance"]
        if dfac and dfac_iso != f["date_facture"]:
            ech = M.echeance(dfac, parametres(con).get("delai_paiement_jours", 30)).isoformat()
        con.execute("UPDATE factures SET montant_ht=?, tva=?, ttc=?, jours=?, unite=?, remarque=?, date_facture=?, "
                    "echeance=?, modifiee_le=? WHERE id=?",
                    (ht, t, ht + t, jours, unite, rq, dfac_iso, ech, db.maintenant(), fid))
        avant = "HT %d, qté %s, unité %s, date %s" % (f["montant_ht"], f["jours"], f["unite"] or "-", f["date_facture"] or "-")
        apres = "HT %d, qté %s, unité %s, date %s" % (ht, jours, unite or "-", dfac_iso or "-")
        journaliser(ctx, "facture_modifiee", f["numero"] or ("prévue %s" % f["mois"][:7]), "%s → %s" % (avant, apres))
    archivee = _archiver_factures(ctx, [fid]) if f["numero"] else 0
    return {"ok": True, "ttc": ht + t, "archivee": archivee}


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
    fact = _vue_factures(con.execute(SQL_FACTURES + ORDRE_FACTURES).fetchall(), con)
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
            # payé = TTC : on le compare au facturé TTC (avant : HT, d'où « payé > facturé »)
            "facture_ttc": sum(f["ttc"] for f in valides if f["mois"] == mm.isoformat()),
            "paye": sum(f["montant_paye"] or 0 for f in valides if f["mois"] == mm.isoformat()),
        })
    tot_fact = sum(f["ttc"] for f in valides)
    tot_paye = sum(f["montant_paye"] or 0 for f in valides)
    # reste dû facture par facture : un paiement saisi en trop ne rend pas le reste négatif
    reste = sum(max(0, f["ttc"] - (f["montant_paye"] or 0)) for f in valides)
    trop_percus = [{"id": f["id"], "numero": f["numero"], "ttc": f["ttc"], "paye": f["montant_paye"]}
                   for f in valides if (f["montant_paye"] or 0) > f["ttc"]]
    return {
        "mois": m.isoformat(), "libelle": M.libelle_mois(m),
        "personnes_en_contrat": personnes, "personnes_en_attente": attente,
        "nouveaux": nouveaux, "fins": fins,
        "a_facturer_ht": a_fact, "visites_ht": visites, "a_facturer_total_ht": a_fact + visites,
        "a_facturer_ttc": a_fact + visites + M.tva(a_fact, p["tva_pdm"]) + (M.tva(visites, p["tva_pdm"]) if p.get("tva_visite") else 0),
        "factures_emises": len(du_mois), "factures_envoyees": sum(1 for f in du_mois if f["envoyee_le"]),
        "factures_payees": sum(1 for f in du_mois if f["paye_le"]),
        "facture_ht": sum(f["montant_ht"] for f in du_mois), "facture_ttc": sum(f["ttc"] for f in du_mois),
        "paye": sum(f["montant_paye"] or 0 for f in du_mois),
        "impaye_mois": sum(max(0, f["ttc"] - (f["montant_paye"] or 0)) for f in du_mois),
        "a_emettre_mois": len(a_emettre_mois), "a_emettre_rattrapage": len(a_emettre_passe),
        "total_facture_ttc": tot_fact, "total_paye": tot_paye, "reste_a_encaisser": reste,
        "trop_percus": trop_percus,
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
    fs = [f for f in _vue_factures(rows, con) if f["numero"]]
    if not fs:
        raise ErreurAPI(409, "Ces factures n'ont pas encore de n° : émettez-les d'abord.")
    p = parametres(con)
    fichiers, vus = [], set()
    for f in fs:
        nom = docx_facture.nom_fichier(f)
        while nom in vus:
            nom = nom[:-5] + "_" + str(f["id"]) + ".docx"
        vus.add(nom)
        fichiers.append((nom, docx_facture.facture_docx(p, f, prive=ctx["prive"], origine=ctx["origine"])))
    journaliser(ctx, "factures_word", ", ".join(f["numero"] for f in fs)[:300], "%d facture(s)" % len(fs))
    if len(fichiers) == 1:
        return Fichier(fichiers[0][1], docx_facture.MIME_DOCX, fichiers[0][0])
    mois = sorted({f["mois"][:7] for f in fs})
    clients = " + ".join(sorted({f["client_nom"] for f in fs}))
    return Fichier(docx_facture.lot_zip(fichiers), "application/zip", docx_facture.propre(
        "%s - Factures %s (%d).zip" % (clients, ", ".join(docx_facture.mois_fr(m + "-01") for m in mois), len(fichiers))))


# ---------------------------------------------------------------------------
# Documents gardés sur le serveur (copies des factures émises, pièces du client)
# ---------------------------------------------------------------------------
def _archiver_factures(ctx, ids):
    """Copie figée (Word, puis PDF en tâche de fond si LibreOffice est là) de
    chaque facture qui vient d'être émise. Un échec n'annule jamais l'émission."""
    if not ids:
        return 0
    con = ctx["con"]
    user_id = ctx["user"]["id"] if ctx.get("user") else None
    a_convertir, n = [], 0
    try:
        rows = con.execute(SQL_FACTURES + " WHERE f.id IN (%s)" % ",".join("?" * len(ids)) + ORDRE_FACTURES,
                           list(ids)).fetchall()
        p = parametres(con)
        with Transaction(con):
            for f in _vue_factures(rows, con):
                contenu = docx_facture.facture_docx(p, f, prive=ctx["prive"], origine=ctx["origine"])
                nom = docx_facture.nom_fichier(f)
                DOC.enregistrer(con, ctx["chemin_db"], f["dossier_id"], f["id"], "Facture", nom, contenu,
                                DOC.MIME_DOCX, ".docx", user_id)
                a_convertir.append((f["dossier_id"], f["id"], nom, contenu))
                n += 1
    except Exception as x:          # pragma: no cover - disque plein, droits…
        with Transaction(con):
            journaliser(ctx, "archive_echec", "", str(x)[:200])
        return 0
    DOC.convertir_en_tache_de_fond(ctx["chemin_db"], a_convertir, user_id)
    return n


def _vue_document(r):
    d = dict(r)
    d.pop("fichier", None)
    d.pop("sha256", None)
    return d


def documents_dossier(ctx, g, body):
    con = ctx["con"]
    did = int(g[0])
    _dossier_row(con, did)
    rows = con.execute("SELECT d.*, f.numero AS facture_numero, u.nom AS ajoute_par_nom FROM documents d "
                       "LEFT JOIN factures f ON f.id = d.facture_id LEFT JOIN utilisateurs u ON u.id = d.ajoute_par "
                       "WHERE d.dossier_id = ? AND d.retire_le IS NULL ORDER BY d.ajoute_le DESC, d.id DESC",
                       (did,)).fetchall()
    return {"documents": [_vue_document(r) for r in rows], "conversion_pdf": DOC.soffice() is not None}


def ajouter_piece(ctx, g, body):
    """Pièce reçue du client (DA, BC, PV…) : PDF, PNG ou JPEG, 8 Mo au plus."""
    import base64
    import binascii
    con = ctx["con"]
    did = int(g[0])
    _dossier_row(con, did)
    cat = body.get("categorie")
    if cat not in DOC.CATEGORIES_PIECES:
        raise ErreurAPI(400, "Type de pièce inconnu (DA, BC, PV ou Autre).")
    nom = texte(body, "nom", 150, True)
    nom = re.sub(r"[\\/\x00-\x1f]", "_", nom).strip() or "piece"
    b64 = body.get("contenu")
    if not isinstance(b64, str) or not b64:
        raise ErreurAPI(400, "Fichier manquant.")
    if len(b64) > DOC.TAILLE_MAX_PIECE * 4 // 3 + 100:
        raise ErreurAPI(413, "Fichier trop lourd (8 Mo au plus).")
    try:
        contenu = base64.b64decode(b64.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise ErreurAPI(400, "Fichier illisible.")
    if not contenu or len(contenu) > DOC.TAILLE_MAX_PIECE:
        raise ErreurAPI(413, "Fichier vide ou trop lourd (8 Mo au plus).")
    fmt = DOC.format_fichier(contenu)
    if not fmt:
        raise ErreurAPI(400, "Format refusé : PDF, PNG ou JPEG seulement.")
    with Transaction(con):
        doc_id = DOC.enregistrer(con, ctx["chemin_db"], did, None, cat, nom, contenu, fmt[0], fmt[1],
                                 ctx["user"]["id"])
        journaliser(ctx, "piece_ajoutee", "dossier %d" % did, "%s : %s (%d Ko)" % (cat, nom, len(contenu) // 1024))
    return {"id": doc_id}


def telecharger_document(ctx, g, body):
    con = ctx["con"]
    r = con.execute("SELECT * FROM documents WHERE id = ?", (int(g[0]),)).fetchone()
    if not r or r["retire_le"]:
        raise ErreurAPI(404, "Document introuvable.")
    try:
        contenu = DOC.lire(ctx["chemin_db"], r)
    except OSError:
        raise ErreurAPI(404, "Fichier introuvable sur le serveur.")
    return Fichier(contenu, r["type_mime"], r["nom"])


def retirer_piece(ctx, g, body):
    """Direction : retire une pièce de la liste (erreur de fichier). Le fichier
    est gardé ; les copies de factures ne se retirent pas."""
    con = ctx["con"]
    with Transaction(con):
        r = con.execute("SELECT * FROM documents WHERE id = ?", (int(g[0]),)).fetchone()
        if not r or r["retire_le"]:
            raise ErreurAPI(404, "Document introuvable.")
        if r["categorie"] == "Facture":
            raise ErreurAPI(409, "La copie d'une facture émise ne se retire pas.")
        con.execute("UPDATE documents SET retire_le = ? WHERE id = ?", (db.maintenant(), r["id"]))
        journaliser(ctx, "piece_retiree", "dossier %d" % r["dossier_id"], "%s : %s" % (r["categorie"], r["nom"]))
    return {"ok": True}


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
    nom = "Factures %s - %s.csv" % (parametres(ctx["con"]).get("raison_sociale", ""),
                                    M.libelle_mois(mois_(q["mois"])) if q.get("mois") else "tous les mois")
    return Fichier(contenu, "text/csv; charset=utf-8", M.sans_accents(nom))
