"""Serveur web de l'ERP ANO Services (Python 3.9+, bibliothèque standard seule).

Lancement : python3 app/serveur.py   (ou double-clic sur « Lancer ANO.command »)
Le serveur n'écoute que sur cet ordinateur (127.0.0.1).
"""
import hmac
import json
import urllib.parse
import os
import re
import sys
import threading
import traceback
import webbrowser
import datetime as dt
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

import api  # noqa: E402
import db  # noqa: E402
import plateforme  # noqa: E402
import securite as S  # noqa: E402

RACINE = os.path.dirname(ICI)
DONNEES = os.environ.get("ANO_DONNEES", os.path.join(RACINE, "donnees"))
CHEMIN_DB = os.path.join(DONNEES, "ano.db")
SAUVEGARDES = os.path.join(DONNEES, "sauvegardes")
HOTE = os.environ.get("ANO_ECOUTE", "127.0.0.1")     # en ligne : reste 127.0.0.1, derrière Caddy (HTTPS)
PORT = int(os.environ.get("ANO_PORT", "8765"))
# V3 en ligne (plusieurs entreprises) ; sans ces variables : installation sur un poste, comme avant
EN_LIGNE = os.environ.get("ANO_EN_LIGNE") == "1"
HTTPS = os.environ.get("ANO_HTTPS") == "1"
DERRIERE_PROXY = os.environ.get("ANO_PROXY") == "1"
HOTES = [h.strip().lower() for h in os.environ.get("ANO_HOTES", "").split(",") if h.strip()]
REGISTRE = plateforme.Registre(DONNEES)
TAILLE_MAX = 1_000_000
TAILLE_MAX_PIECE = 11_500_000      # pièce jointe de 8 Mo encodée en base64
COOKIE = "ano_session"

STATIQUES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/logo.png": ("logo.png", "image/png"),
}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

A, G, L = "admin", "gestion", "lecture"
TOUS = (A, G, L)
EQUIPE = (A, G)

# (méthode, motif, fonction, rôles autorisés ; None = sans connexion)
ROUTES = [
    ("GET", r"/api/etat", api.etat, None),
    ("GET", r"/api/sante", None, None),     # supervision : répond sans ouvrir aucune base
    ("POST", r"/api/installation", api.installation, None),
    ("POST", r"/api/connexion", api.connexion, None),
    ("POST", r"/api/deconnexion", api.deconnexion, TOUS),
    ("GET", r"/api/moi", api.moi, TOUS),
    ("POST", r"/api/moi/mot-de-passe", api.changer_mdp, TOUS),
    ("GET", r"/api/parametres", api.lire_parametres, TOUS),
    ("PUT", r"/api/parametres", api.modifier_parametres, (A,)),
    ("GET", r"/api/clients", api.clients, EQUIPE),
    ("POST", r"/api/clients", api.creer_client, EQUIPE),
    ("PUT", r"/api/clients/(\d+)", api.modifier_client, EQUIPE),
    ("GET", r"/api/interimaires", api.liste_interimaires, EQUIPE),
    ("POST", r"/api/interimaires", api.creer_interimaire, EQUIPE),
    ("PUT", r"/api/interimaires/(\d+)", api.modifier_interimaire, EQUIPE),
    ("GET", r"/api/dossiers", api.liste_dossiers, EQUIPE),
    ("POST", r"/api/dossiers", api.creer_dossier, EQUIPE),
    ("POST", r"/api/dossiers/apercu", api.apercu_dossier, EQUIPE),
    ("GET", r"/api/dossiers/(\d+)", api.detail_dossier, EQUIPE),
    ("PUT", r"/api/dossiers/(\d+)", api.modifier_dossier, EQUIPE),
    ("POST", r"/api/dossiers/(\d+)/statut", api.statut_dossier, EQUIPE),
    ("POST", r"/api/dossiers/(\d+)/bc", api.bc_dossier, EQUIPE),
    ("POST", r"/api/dossiers/(\d+)/generer-factures", api.generer_factures, EQUIPE),
    ("GET", r"/api/dossiers/(\d+)/documents", api.documents_dossier, EQUIPE),
    ("POST", r"/api/dossiers/(\d+)/pieces", api.ajouter_piece, EQUIPE),
    ("GET", r"/api/documents/(\d+)", api.telecharger_document, EQUIPE),
    ("POST", r"/api/documents/(\d+)/retirer", api.retirer_piece, (A,)),
    ("GET", r"/api/factures", api.liste_factures, TOUS),
    ("GET", r"/api/factures/word", api.factures_word, EQUIPE),
    ("GET", r"/api/factures/export\.csv", api.factures_csv, TOUS),
    ("POST", r"/api/factures/emettre", api.emettre, EQUIPE),
    ("POST", r"/api/factures/envoyees", api.marquer_envoyees, EQUIPE),
    ("POST", r"/api/factures/paiement", api.paiement, EQUIPE),
    ("POST", r"/api/factures/(\d+)/annuler-paiement", api.annuler_paiement, EQUIPE),
    ("POST", r"/api/factures/(\d+)/bis", api.facture_bis, EQUIPE),
    ("PUT", r"/api/factures/(\d+)/remarque", api.remarque_facture, EQUIPE),
    ("PUT", r"/api/factures/(\d+)", api.modifier_facture, EQUIPE),
    ("GET", r"/api/tableau-de-bord", api.tableau_de_bord, TOUS),
    ("GET", r"/api/recherche", api.recherche, TOUS),
    ("GET", r"/api/signature", api.signature, TOUS),
    ("GET", r"/api/logo", api.logo, TOUS),
    ("PUT", r"/api/images/(logo|signature)", api.televerser_image, (A,)),
    ("GET", r"/api/utilisateurs", api.utilisateurs, (A,)),
    ("POST", r"/api/utilisateurs", api.creer_utilisateur, (A,)),
    ("PUT", r"/api/utilisateurs/(\d+)", api.modifier_utilisateur, (A,)),
    ("GET", r"/api/journal", api.journal, (A,)),
    ("POST", r"/api/sauvegarde", api.sauvegarde, (A,)),
]
ROUTES = [(m, re.compile("^" + p + "$"), f, r) for m, p, f, r in ROUTES]
# Routes accessibles quand l'utilisateur doit d'abord changer son mot de passe
ROUTES_MDP = {api.moi, api.changer_mdp, api.deconnexion}

LIMITEUR = S.LimiteurIP()


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "ANO"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- journal console : méthode, chemin sans paramètres, code -----------------
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        sys.stderr.write("%s %s %s %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), self.command,
                                            urlsplit(self.path).path, code))

    # -- réponses ---------------------------------------------------------------
    def _entetes_securite(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Cache-Control", "no-store")
        if HTTPS:
            self.send_header("Strict-Transport-Security", "max-age=31536000")

    def _envoyer(self, status, corps, type_="application/json; charset=utf-8", cookie=None, nom_fichier=None):
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_securite()
        if not getattr(self, "_corps_lu", True):
            # corps de requête non lu : on ferme la connexion pour ne pas le
            # confondre avec la requête suivante
            self.send_header("Connection", "close")
            self.close_connection = True
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        if nom_fichier:
            ascii_ = "".join(c if c.isalnum() or c in "._-" else "_" for c in nom_fichier.encode("ascii", "replace").decode())
            self.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                             % (ascii_, urllib.parse.quote(nom_fichier)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def _erreur(self, status, message, code=None):
        d = {"erreur": message}
        if code:
            d["code"] = code
        self._envoyer(status, d)

    # -- contrôles communs ------------------------------------------------------
    def _hote_ok(self):
        """Protection contre le « DNS rebinding » : seul l'hôte local est accepté."""
        h = (self.headers.get("Host") or "").lower()
        return h in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT) or h in HOTES

    def _origine_ok(self):
        o = self.headers.get("Origin")
        if o is None:
            return True
        schema = "https://" if HTTPS else "http://"
        return o.lower() in (("http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT)
                             + tuple(schema + h for h in HOTES))

    def _ip(self):
        """IP du visiteur ; derrière Caddy, la dernière adresse ajoutée par le proxy."""
        if DERRIERE_PROXY:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
            if xff:
                return xff
        return self.client_address[0]

    def _cookie(self):
        """Cookie de session = « code-entreprise.jeton »."""
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except cookies.CookieError:
            return "", ""
        if COOKIE not in c:
            return "", ""
        code, _, jeton = c[COOKIE].value.partition(".")
        return code, jeton

    def _session(self, con, jeton):
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", jeton):
            return None, None
        h = S.empreinte(jeton)
        s = con.execute("SELECT * FROM sessions WHERE token_hash = ?", (h,)).fetchone()
        if not s:
            return None, None
        now = dt.datetime.now()
        if (now - dt.datetime.fromisoformat(s["vu_le"]) > S.DUREE_INACTIVITE
                or now - dt.datetime.fromisoformat(s["cree_le"]) > S.DUREE_MAX_SESSION):
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (h,))
            return None, None
        u = con.execute("SELECT * FROM utilisateurs WHERE id = ? AND actif = 1", (s["user_id"],)).fetchone()
        if not u:
            return None, None
        if (now - dt.datetime.fromisoformat(s["vu_le"])).total_seconds() > 30:
            con.execute("UPDATE sessions SET vu_le = ? WHERE token_hash = ?", (db.maintenant(), h))
        return dict(s), dict(u)

    # -- aiguillage ---------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def do_PUT(self):
        self._traiter("PUT")

    def do_DELETE(self):
        self._erreur(405, "Méthode non autorisée.")

    def _traiter(self, methode):
        self._corps_lu = methode not in ("POST", "PUT")
        try:
            if not self._hote_ok():
                return self._erreur(400, "Hôte non autorisé.")
            url = urlsplit(self.path)
            if not url.path.startswith("/api/"):
                if methode != "GET":
                    return self._erreur(405, "Méthode non autorisée.")
                return self._statique(url.path)
            self._api(methode, url)
        except Exception:  # ne jamais renvoyer de détail technique au navigateur
            traceback.print_exc()
            try:
                self._erreur(500, "Erreur interne. Réessayez ; si cela persiste, relancez l'application.")
            except Exception:
                pass

    def _statique(self, chemin):
        if chemin not in STATIQUES:
            return self._erreur(404, "Page introuvable.")
        nom, type_ = STATIQUES[chemin]
        fichier = os.path.join(ICI, "static", nom)
        if chemin == "/static/logo.png" and os.path.exists(os.path.join(ICI, "prive", "logo.png")):
            fichier = os.path.join(ICI, "prive", "logo.png")   # logo chargé par l'entreprise
        with open(fichier, "rb") as f:
            self._envoyer(200, f.read(), type_)

    def _api(self, methode, url):
        route = None
        groupes = ()
        for m, motif, fonction, roles in ROUTES:
            g = motif.match(url.path)
            if g and m == methode:
                route, groupes = (fonction, roles), g.groups()
                break
        if route is None:
            return self._erreur(404, "Adresse inconnue.")
        fonction, roles = route
        if fonction is None:
            return self._envoyer(200, {"ok": True})

        corps = {}
        if methode in ("POST", "PUT"):
            if not self._origine_ok():
                return self._erreur(403, "Origine refusée.")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._erreur(415, "Format JSON attendu.")
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._erreur(400, "Requête invalide.")
            if n > (TAILLE_MAX_PIECE if fonction is api.ajouter_piece else TAILLE_MAX):
                return self._erreur(413, "Requête trop volumineuse.")
            brut = self.rfile.read(n) if n > 0 else b"{}"
            self._corps_lu = True
            try:
                corps = json.loads(brut.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._erreur(400, "JSON invalide.")
            if not isinstance(corps, dict):
                return self._erreur(400, "JSON invalide.")

        # Entreprise de la requête : par le cookie de session (comptes connectés),
        # sinon par le code saisi à la connexion. Une requête n'ouvre QUE la
        # base de cette entreprise.
        ip = self._ip()
        query = dict(parse_qsl(url.query))
        multi = False
        if roles is None:
            code = corps.get("entreprise") if methode != "GET" else query.get("entreprise")
            code = code if isinstance(code, str) else ""
            ent = REGISTRE.choisir(code)
            multi = EN_LIGNE or len(REGISTRE.actives()) > 1
            if ent is None:
                if fonction is api.etat:
                    return self._envoyer(200, {"installation_requise": False, "multi": True})
                if fonction is api.connexion:
                    # même réponse et même durée qu'un mauvais mot de passe :
                    # on ne révèle pas quels codes d'entreprise existent
                    if LIMITEUR.bloque(ip):
                        return self._erreur(429, "Trop de tentatives. Réessayez dans 15 minutes.")
                    S.verifier_factice(str(corps.get("mot_de_passe") or "x")[:S.MDP_MAX])
                    LIMITEUR.echec(ip)
                    return self._erreur(401, "Identifiant ou mot de passe incorrect.")
                return self._erreur(400, "Entreprise inconnue.")
            jeton = ""
        else:
            code, jeton = self._cookie()
            ent = REGISTRE.trouver(code) if jeton else None
            if ent is None:
                return self._erreur(401, "Session expirée : reconnectez-vous.", "NON_CONNECTE")
        con = db.connecter(ent["chemin_db_abs"])
        try:
            ctx = {"con": con, "ip": ip, "limiteur": LIMITEUR, "query": query,
                   "chemin_db": ent["chemin_db_abs"], "dossier_sauvegardes": ent["sauvegardes_abs"],
                   "prive": ent["prive_abs"], "origine": ent["origine"], "entreprise": ent["code"],
                   "en_ligne": EN_LIGNE, "multi": multi}
            if roles is not None:
                session, user = self._session(con, jeton)
                if not user:
                    return self._erreur(401, "Session expirée : reconnectez-vous.", "NON_CONNECTE")
                if methode != "GET":
                    jeton = self.headers.get("X-CSRF-Token") or ""
                    if not hmac.compare_digest(jeton, session["csrf"]):
                        return self._erreur(403, "Jeton de sécurité invalide : rechargez la page.")
                if user["doit_changer_mdp"] and fonction not in ROUTES_MDP:
                    return self._erreur(403, "Changez d'abord votre mot de passe.", "CHANGER_MDP")
                if user["role"] not in roles:
                    return self._erreur(403, "Votre rôle ne permet pas cette action.")
                ctx.update(user=user, csrf=session["csrf"], session_hash=session["token_hash"])
            try:
                res = fonction(ctx, groupes, corps)
            except api.ErreurAPI as e:
                return self._erreur(e.status, e.message, e.code)
            cookie = None
            secure = "; Secure" if HTTPS else ""
            if ctx.get("nouveau_cookie"):
                cookie = "%s=%s.%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (
                    COOKIE, ent["code"], ctx["nouveau_cookie"], int(S.DUREE_MAX_SESSION.total_seconds()), secure)
            elif ctx.get("effacer_cookie"):
                cookie = "%s=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0%s" % (COOKIE, secure)
            if isinstance(res, api.Fichier):
                return self._envoyer(200, res.contenu, res.type_, nom_fichier=res.nom)
            self._envoyer(200, res, cookie=cookie)
        finally:
            con.close()


def nettoyer_sessions(chemin_db):
    con = db.connecter(chemin_db)
    limite = (dt.datetime.now() - S.DUREE_INACTIVITE).replace(microsecond=0).isoformat(sep=" ")
    con.execute("DELETE FROM sessions WHERE vu_le < ?", (limite,))
    con.close()


def demarrer(ouvrir_navigateur=True):
    os.makedirs(DONNEES, mode=0o700, exist_ok=True)
    try:
        os.chmod(DONNEES, 0o700)
    except OSError:
        pass
    REGISTRE.initialiser(en_ligne=EN_LIGNE)
    for e in REGISTRE.actives():       # chaque entreprise : sauvegarde, mise à niveau, sessions
        if os.path.exists(e["chemin_db_abs"]):
            db.sauvegarder(e["chemin_db_abs"], e["sauvegardes_abs"])
        db.initialiser(e["chemin_db_abs"])
        nettoyer_sessions(e["chemin_db_abs"])
    if EN_LIGNE:
        ouvrir_navigateur = False
    try:
        serveur = ThreadingHTTPServer((HOTE, PORT), Gestionnaire)
    except OSError:
        print("\nLe port %d est déjà utilisé : l'application est sans doute déjà ouverte." % PORT)
        print("Ouvrez http://localhost:%d dans votre navigateur.\n" % PORT)
        if ouvrir_navigateur:
            webbrowser.open("http://localhost:%d/" % PORT)
        return
    serveur.daemon_threads = True
    adresse = "http://localhost:%d/" % PORT
    print("\n  ERP mise à disposition (version MVP)")
    print("  Ouvert sur : %s" % adresse)
    print("  Données    : %s" % DONNEES)
    print("  Pour arrêter : fermez cette fenêtre (ou Ctrl + C).\n")
    if ouvrir_navigateur:
        threading.Timer(1.0, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    finally:
        serveur.server_close()


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        print("Python 3.9 ou plus récent est nécessaire (version actuelle : %s)." % sys.version.split()[0])
        sys.exit(1)
    demarrer(ouvrir_navigateur="--sans-navigateur" not in sys.argv)
