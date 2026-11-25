"""Base de données SQLite : schéma, valeurs initiales, sauvegardes."""
import datetime as dt
import json
import os
import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS parametres (
    cle TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY,
    ordre INTEGER NOT NULL,
    libelle TEXT NOT NULL,
    taux_pdm INTEGER NOT NULL CHECK (taux_pdm >= 0 AND taux_pdm <= 100000)
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    nom TEXT NOT NULL,
    adresse TEXT NOT NULL DEFAULT '',
    ville TEXT NOT NULL DEFAULT '',
    telephone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    actif INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS dossiers (
    id INTEGER PRIMARY KEY,
    num_seq INTEGER NOT NULL UNIQUE,
    numero_proforma TEXT NOT NULL UNIQUE,
    nom_numero TEXT NOT NULL,
    date_proforma TEXT NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    num_da TEXT NOT NULL DEFAULT '',
    service TEXT NOT NULL DEFAULT '',
    imputation TEXT NOT NULL DEFAULT '',
    lieu TEXT NOT NULL DEFAULT '',
    date_debut TEXT NOT NULL,
    date_fin TEXT NOT NULL,
    visite_mode TEXT NOT NULL DEFAULT 'Auto' CHECK (visite_mode IN ('Auto','Non')),
    statut TEXT NOT NULL DEFAULT 'Brouillon',
    date_validation TEXT,
    bc_numero TEXT NOT NULL DEFAULT '',
    bc_montant INTEGER,
    bc_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    bareme_json TEXT NOT NULL,
    cree_par INTEGER REFERENCES utilisateurs(id),
    cree_le TEXT NOT NULL,
    maj_le TEXT NOT NULL,
    CHECK (date_fin >= date_debut)
);
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY,
    dossier_id INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    rang INTEGER NOT NULL,
    nom TEXT NOT NULL,
    poste TEXT NOT NULL,
    salaire_base INTEGER NOT NULL CHECK (salaire_base > 0),
    derniere_visite TEXT
);
CREATE TABLE IF NOT EXISTS interimaires (
    id INTEGER PRIMARY KEY,
    matricule TEXT NOT NULL UNIQUE,
    nom TEXT NOT NULL,
    cle TEXT NOT NULL UNIQUE,
    cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS factures (
    id INTEGER PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('MAD','VISITE','BIS')),
    mois TEXT NOT NULL,
    jours INTEGER,
    jours_mois INTEGER,
    montant_ht INTEGER NOT NULL,
    tva INTEGER NOT NULL,
    ttc INTEGER NOT NULL,
    numero TEXT UNIQUE,
    num_seq INTEGER,
    date_facture TEXT,
    echeance TEXT,
    envoyee_le TEXT,
    pv_montant INTEGER,
    pv_date TEXT,
    remplace_id INTEGER REFERENCES factures(id),
    remplacee_par_id INTEGER REFERENCES factures(id),
    paye_le TEXT,
    montant_paye INTEGER,
    ref_paiement TEXT NOT NULL DEFAULT '',
    remarque TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_factures_unique
    ON factures(agent_id, type, mois) WHERE type <> 'BIS';
CREATE INDEX IF NOT EXISTS ix_factures_mois ON factures(mois);
CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY,
    identifiant TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nom TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','gestion','lecture')),
    mdp_hash TEXT NOT NULL,
    actif INTEGER NOT NULL DEFAULT 1,
    echecs INTEGER NOT NULL DEFAULT 0,
    bloque_jusqu TEXT,
    doit_changer_mdp INTEGER NOT NULL DEFAULT 0,
    cree_le TEXT NOT NULL,
    dernier_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES utilisateurs(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    cree_le TEXT NOT NULL,
    vu_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    dossier_id INTEGER NOT NULL REFERENCES dossiers(id),
    facture_id INTEGER REFERENCES factures(id),
    categorie TEXT NOT NULL CHECK (categorie IN ('Facture','DA','BC','PV','Autre')),
    nom TEXT NOT NULL,
    fichier TEXT NOT NULL UNIQUE,           -- chemin relatif au dossier « documents » de l'entreprise
    type_mime TEXT NOT NULL,
    taille INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    ajoute_par INTEGER REFERENCES utilisateurs(id),
    ajoute_le TEXT NOT NULL,
    retire_le TEXT                          -- pièce retirée de la liste (le fichier est gardé)
);
CREATE INDEX IF NOT EXISTS ix_documents_dossier ON documents(dossier_id);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY,
    quand TEXT NOT NULL,
    user_id INTEGER,
    identifiant TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    objet TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT ''
);
"""

PARAMETRES_INITIAUX = {
    "raison_sociale": "ANO Services",
    "adresse": "BP 130",
    "ville": "Moanda – Gabon",
    "telephone": "077 56 72 01 / 066 04 50 64",
    "email": "yatony1_2005@yahoo.fr",
    "rccm": "RG/FCV N° 2021 A368",
    "nif": "746 590 E",
    "cnss": "021-0212774-P",
    "banque": "BGFIbank",
    "compte": "4003 04160 21109056001",
    "devise": "XAF",
    "tva_pdm": 1800,
    "validite_devis_jours": 30,
    "modalite_reglement": "30 JFDM",
    "delai_paiement_jours": 30,
    "visite_ht": 45000,
    "validite_visite_mois": 12,
    "heures": "40 heures / semaine; soit 173,33 heures / mois",
    "dernier_num_proforma": 348,   # dernier devis réel (Luc, 24/11/2026)
    "dernier_num_facture": 161,    # dernière facture réelle FA 161 (Luc, 24/11/2026)
    "alerte_fin_jours": 30,
    "alerte_visite_jours": 30,
    # V1 B2B : ce qui était écrit en dur pour ANO devient réglable
    "code_entreprise": "ANO",          # 348-11-ANO-NOM/2026
    "prefixe_facture": "FA",           # FA 161/11-MAD/2026
    "code_mad": "MAD",
    "code_visite": "Visite Médicale",
    "tva_visite": False,               # visite médicale sans TVA (règle ANO)
    "bc_chiffres": 6,                  # longueur habituelle d'un n° de BC (0 = pas de contrôle)
    "lieux": ["Moanda", "Libreville", "Port-Gentil"],
    "services": ["DAF"],
}

CHARGES_INITIALES = [
    ("CNSS", 1850), ("CNAMGS", 610), ("Indemnité de précarité", 2000), ("TCS", 500),
    ("Frais liés aux charges du personnel", 957), ("FNH", 300), ("CFP", 50),
    ("Congés", 833), ("Marge sociétale", 2000),
]

CLIENTS_INITIAUX = [
    ("CLI001", "COMILOG SA", "BP 27 – 28", "Moanda – Gabon", "011664015"),
    ("CLI002", "COMILOG SA (Libreville)", "", "Libreville – Gabon", ""),
]


def maintenant():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connecter(chemin):
    con = sqlite3.connect(chemin, timeout=10, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


def parametres_vierges(nom, code):
    """Nouvelle entreprise (V3) : réglages par défaut SANS les données d'ANO
    (identité vide, compteurs à 0, code des n° = code de l'entreprise)."""
    p = dict(PARAMETRES_INITIAUX)
    for k in ("adresse", "ville", "telephone", "email", "rccm", "nif", "cnss", "banque", "compte"):
        p[k] = ""
    p.update(raison_sociale=nom, code_entreprise=re.sub(r"[^A-Z0-9]", "", code.upper())[:12] or "ENT",
             dernier_num_proforma=0, dernier_num_facture=0, lieux=[], services=[],
             maj_compteurs_20261124=True)       # compteurs d'ANO : jamais appliqués ici
    return p


def initialiser(chemin, vierge=False, nom="", code=""):
    neuf = not os.path.exists(chemin)
    con = connecter(chemin)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    if neuf or con.execute("SELECT COUNT(*) FROM parametres").fetchone()[0] == 0:
        con.execute("BEGIN")
        for k, v in (parametres_vierges(nom, code) if vierge else PARAMETRES_INITIAUX).items():
            con.execute("INSERT OR IGNORE INTO parametres(cle, valeur) VALUES (?, ?)", (k, json.dumps(v)))
        if con.execute("SELECT COUNT(*) FROM charges").fetchone()[0] == 0:
            for i, (lib, t) in enumerate(CHARGES_INITIALES):
                con.execute("INSERT INTO charges(ordre, libelle, taux_pdm) VALUES (?, ?, ?)", (i + 1, lib, t))
        if not vierge and con.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
            for c in CLIENTS_INITIAUX:
                con.execute("INSERT INTO clients(code, nom, adresse, ville, telephone) VALUES (?,?,?,?,?)", c)
        con.execute("COMMIT")
    # base existante : ajoute les paramètres apparus depuis (ex. V1 B2B), sans
    # jamais toucher aux valeurs déjà enregistrées
    with con:
        for k, v in PARAMETRES_INITIAUX.items():
            con.execute("INSERT OR IGNORE INTO parametres(cle, valeur) VALUES (?, ?)", (k, json.dumps(v)))
    migrer_interimaires(con)
    con.close()
    try:
        os.chmod(chemin, 0o600)
    except OSError:
        pass


def sauvegarder(chemin, dossier_sauvegardes, garder=30):
    """Copie cohérente de la base (API de sauvegarde SQLite). Garde les N
    dernières copies."""
    if not os.path.exists(chemin):
        return None
    os.makedirs(dossier_sauvegardes, mode=0o700, exist_ok=True)
    nom = "ano_%s.db" % dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    cible = os.path.join(dossier_sauvegardes, nom)
    src = sqlite3.connect(chemin)
    dst = sqlite3.connect(cible)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    try:
        os.chmod(cible, 0o600)
    except OSError:
        pass
    copies = sorted(f for f in os.listdir(dossier_sauvegardes) if f.startswith("ano_") and f.endswith(".db"))
    for f in copies[:-garder]:
        os.remove(os.path.join(dossier_sauvegardes, f))
    return cible


def interimaire_id(con, nom):
    """Matricule fixe : retrouve l'intérimaire par son nom normalisé, ou le crée."""
    from metier import cle_nom, matricule
    cle = cle_nom(nom)
    r = con.execute("SELECT id FROM interimaires WHERE cle = ?", (cle,)).fetchone()
    if r:
        return r[0]
    n = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM interimaires").fetchone()[0]
    con.execute("INSERT INTO interimaires(id, matricule, nom, cle, cree_le) VALUES (?,?,?,?,?)",
                (n, matricule(n), " ".join(str(nom).split()), cle, maintenant()))
    return n


def migrer_interimaires(con):
    """Base existante : ajoute agents.interimaire_id et numérote les agents
    déjà saisis (dans l'ordre de saisie)."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(agents)")]
    con.execute("BEGIN")
    if "interimaire_id" not in cols:
        con.execute("ALTER TABLE agents ADD COLUMN interimaire_id INTEGER REFERENCES interimaires(id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_agents_interimaire ON agents(interimaire_id)")
    # anciens intérimaires saisis à la main (historique, sans facture)
    cols_i = [r[1] for r in con.execute("PRAGMA table_info(interimaires)")]
    for col in ("poste", "lieu", "hist_debut", "hist_fin", "derniere_visite", "notes"):
        if col not in cols_i:
            con.execute("ALTER TABLE interimaires ADD COLUMN %s TEXT" % col)
    # compteurs réels donnés par Luc le 24/11/2026 (une seule fois, sans jamais reculer)
    if not con.execute("SELECT 1 FROM parametres WHERE cle = 'maj_compteurs_20261124'").fetchone():
        for cle, v in (("dernier_num_proforma", 348), ("dernier_num_facture", 161)):
            r = con.execute("SELECT valeur FROM parametres WHERE cle = ?", (cle,)).fetchone()
            actuel = json.loads(r[0]) if r else None
            if actuel is None or int(actuel) < v:
                con.execute("INSERT OR REPLACE INTO parametres(cle, valeur) VALUES (?, ?)", (cle, json.dumps(v)))
        con.execute("INSERT INTO parametres(cle, valeur) VALUES ('maj_compteurs_20261124', 'true')")
    for aid, nom in con.execute("SELECT id, nom FROM agents WHERE interimaire_id IS NULL ORDER BY id").fetchall():
        con.execute("UPDATE agents SET interimaire_id = ? WHERE id = ?", (interimaire_id(con, nom), aid))
    con.execute("COMMIT")
