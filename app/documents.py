"""Documents gardés sur le serveur, dans le dossier de chaque entreprise :
- copie figée de chaque facture au moment où elle est émise (Word, et PDF
  quand LibreOffice est installé) ;
- pièces reçues du client (DA, BC, PV…) en PDF, PNG ou JPEG.

Les fichiers ne sont jamais servis en accès direct : seulement par l'API, à un
utilisateur connecté de la même entreprise. Ils portent un nom aléatoire
(le nom d'origine reste dans la base) et ne sont jamais modifiés ni effacés :
retirer une pièce la masque de la liste, le fichier reste.
"""
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import uuid

import db

CATEGORIES_PIECES = ("DA", "BC", "PV", "Autre")
TAILLE_MAX_PIECE = 8 * 1024 * 1024          # 8 Mo par fichier
FORMATS = {                                  # signature du fichier -> (type, extension)
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
}
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def dossier_documents(chemin_db):
    """documents/ à côté de la base de l'entreprise (jamais dans le programme)."""
    return os.path.join(os.path.dirname(os.path.abspath(chemin_db)), "documents")


def format_fichier(contenu):
    for sig, (mime, ext) in FORMATS.items():
        if contenu.startswith(sig):
            return mime, ext
    return None


def enregistrer(con, chemin_db, dossier_id, facture_id, categorie, nom, contenu, type_mime, ext, user_id):
    """Écrit le fichier (droits 600) puis sa ligne dans la base. Retourne l'id."""
    racine = dossier_documents(chemin_db)
    sous = dt.date.today().strftime("%Y-%m")
    os.makedirs(os.path.join(racine, sous), mode=0o700, exist_ok=True)
    rel = os.path.join(sous, uuid.uuid4().hex + ext)
    cible = os.path.join(racine, rel)
    fd = os.open(cible, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    cur = con.execute(
        "INSERT INTO documents(dossier_id, facture_id, categorie, nom, fichier, type_mime, taille, sha256, "
        "ajoute_par, ajoute_le) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (dossier_id, facture_id, categorie, nom, rel, type_mime, len(contenu),
         hashlib.sha256(contenu).hexdigest(), user_id, db.maintenant()))
    return cur.lastrowid


def lire(chemin_db, ligne):
    """Contenu d'un document ; refuse tout chemin qui sortirait du dossier."""
    racine = os.path.realpath(dossier_documents(chemin_db))
    chemin = os.path.realpath(os.path.join(racine, ligne["fichier"]))
    if not chemin.startswith(racine + os.sep):
        raise FileNotFoundError(ligne["fichier"])
    with open(chemin, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Conversion Word -> PDF (facultative : LibreOffice sur le serveur ou le Mac)
# ---------------------------------------------------------------------------
def soffice():
    c = os.environ.get("ANO_SOFFICE")
    if c:
        return c if os.path.exists(c) else None
    for nom in ("soffice", "libreoffice"):
        p = shutil.which(nom)
        if p:
            return p
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    return mac if os.path.exists(mac) else None


_VERROU_PDF = threading.Lock()               # une conversion à la fois (mémoire)


def en_pdf(docx, delai=120):
    """PDF du .docx, ou None si LibreOffice est absent ou échoue."""
    exe = soffice()
    if not exe:
        return None
    with _VERROU_PDF, tempfile.TemporaryDirectory(prefix="erp_pdf_") as tmp:
        src = os.path.join(tmp, "facture.docx")
        with open(src, "wb") as f:
            f.write(docx)
        profil = "file://" + os.path.join(tmp, "profil")
        try:
            subprocess.run([exe, "-env:UserInstallation=" + profil, "--headless", "--norestore",
                            "--convert-to", "pdf", "--outdir", tmp, src],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=delai, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        sortie = os.path.join(tmp, "facture.pdf")
        if not os.path.exists(sortie):
            return None
        with open(sortie, "rb") as f:
            pdf = f.read()
        return pdf if pdf.startswith(b"%PDF-") else None


def convertir_en_tache_de_fond(chemin_db, a_convertir, user_id, categorie="Facture", hs_id=None):
    """a_convertir = [(dossier_id, facture_id, nom_docx, contenu_docx)]. Ajoute
    les PDF un par un, sans faire attendre la personne qui a émis."""
    if not a_convertir or not soffice():
        return None

    def travail():
        for dossier_id, facture_id, nom, contenu in a_convertir:
            try:
                pdf = en_pdf(contenu)
                if not pdf:
                    continue
                con = db.connecter(chemin_db)
                try:
                    with con:
                        doc = enregistrer(con, chemin_db, dossier_id, facture_id, categorie, nom[:-5] + ".pdf",
                                          pdf, "application/pdf", ".pdf", user_id)
                        if hs_id:
                            con.execute("UPDATE documents SET hs_id = ? WHERE id = ?", (hs_id, doc))
                finally:
                    con.close()
            except Exception:       # le Word est déjà gardé : un PDF manqué ne bloque rien
                continue

    t = threading.Thread(target=travail, name="archives-pdf", daemon=True)
    t.start()
    return t
