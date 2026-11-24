"""Mots de passe, sessions, limitation des tentatives de connexion."""
import base64
import datetime as dt
import hashlib
import hmac
import secrets
import threading
import time

ITERATIONS = 600_000          # PBKDF2-HMAC-SHA256 (recommandation OWASP)
DUREE_INACTIVITE = dt.timedelta(minutes=30)
DUREE_MAX_SESSION = dt.timedelta(hours=10)
ECHECS_AVANT_BLOCAGE = 5
DUREE_BLOCAGE = dt.timedelta(minutes=15)
MDP_MIN = 12
MDP_MAX = 128

MDP_TROP_COURANTS = {
    "motdepasse123", "azertyuiop12", "123456789012", "password1234", "anoservices1",
    "anoservices2026", "comilog12345", "qwertyuiop12", "000000000000", "111111111111",
}


def hacher_mdp(mdp):
    sel = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, base64.b64encode(sel).decode(), base64.b64encode(h).decode())


def verifier_mdp(mdp, stocke):
    try:
        algo, it, sel, h = stocke.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), base64.b64decode(sel), int(it))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


# Hash factice : on fait le même calcul quand l'identifiant n'existe pas,
# pour ne pas révéler par le temps de réponse quels comptes existent.
_HASH_FACTICE = hacher_mdp(secrets.token_urlsafe(16))


def verifier_factice(mdp):
    verifier_mdp(mdp, _HASH_FACTICE)


def probleme_mdp(mdp, identifiant=""):
    """Renvoie un message si le mot de passe est refusé, sinon None."""
    if not isinstance(mdp, str):
        return "Mot de passe invalide."
    if len(mdp) < MDP_MIN:
        return "Le mot de passe doit faire au moins %d caractères." % MDP_MIN
    if len(mdp) > MDP_MAX:
        return "Le mot de passe est trop long (%d caractères maximum)." % MDP_MAX
    if mdp.lower() in MDP_TROP_COURANTS or len(set(mdp)) < 4:
        return "Ce mot de passe est trop facile à deviner."
    if identifiant and identifiant.lower() in mdp.lower():
        return "Le mot de passe ne doit pas contenir l'identifiant."
    return None


def nouveau_jeton():
    return secrets.token_urlsafe(32)


def empreinte(jeton):
    return hashlib.sha256(jeton.encode("ascii", "ignore")).hexdigest()


class LimiteurIP:
    """Au plus N échecs de connexion par adresse sur une fenêtre glissante."""

    def __init__(self, maxi=20, fenetre_s=900):
        self.maxi, self.fenetre = maxi, fenetre_s
        self.echecs = {}
        self.verrou = threading.Lock()

    def _purger(self, ip, t):
        self.echecs[ip] = [x for x in self.echecs.get(ip, []) if t - x < self.fenetre]

    def bloque(self, ip):
        with self.verrou:
            self._purger(ip, time.time())
            return len(self.echecs[ip]) >= self.maxi

    def echec(self, ip):
        with self.verrou:
            t = time.time()
            self._purger(ip, t)
            self.echecs[ip].append(t)

    def reussite(self, ip):
        with self.verrou:
            self.echecs.pop(ip, None)
