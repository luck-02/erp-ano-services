"""Export des factures au format Word (.docx) modifiable.

Bibliothèque standard uniquement : un .docx est un zip de fichiers XML.
La mise en page reprend celle de la facture imprimée (logo à gauche, bloc
ANO Services à droite, cadre client bleu, tableau des prestations, totaux,
cachet + signature, pied de page RCCM / NIF / banque).
"""
import datetime as dt
import io
import os
import struct
import zipfile
from xml.sax.saxutils import escape

import metier as M

ICI = os.path.dirname(os.path.abspath(__file__))
LOGO_DEFAUT = os.path.join(ICI, "static", "logo.png")


def chemin_logo(prive=None, origine=True):
    """Logo chargé par l'entreprise (Paramètres) ; sinon le logo livré pour
    l'installation d'origine (ANO), aucun logo pour une autre entreprise."""
    perso = os.path.join(prive or os.path.join(ICI, "prive"), "logo.png")
    if os.path.exists(perso):
        return perso
    return LOGO_DEFAUT if origine else None

EMU_MM = 36000
LARGEUR = 10204          # largeur utile en twips (A4, marges 1,5 cm)
BLEU = "4472C4"
GRIS = "D6DCE5"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------------------
# Mise en forme des valeurs (identique à la facture imprimée)
# ---------------------------------------------------------------------------
def fmt_pt(n):
    return "{:,}".format(int(n or 0)).replace(",", ".")


def date_fr(iso):
    if not iso:
        return ""
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[0:4])


def mois_fr(iso):
    return M.libelle_mois(dt.date.fromisoformat(iso[:10])) if iso else ""


def pct(pdm):
    v = pdm / 100
    return ("%g" % v).replace(".", ",") + " %"


def propre(t):
    """Nom de fichier sûr : sans accents ni caractères interdits."""
    t = M.sans_accents(t)
    return "".join("-" if c in '/\\:*?"<>|' else c for c in t if c.isprintable() and ord(c) < 128).strip()


def nom_fichier(f):
    """Client d'abord, puis « Facture Mois Année », l'agent et le n°."""
    return propre("%s - Facture %s - %s - %s" % (f["client_nom"], mois_fr(f["mois"]), f["agent"], f["numero"])) + ".docx"


# ---------------------------------------------------------------------------
# Briques XML
# ---------------------------------------------------------------------------
def run(texte, gras=False, taille=None, couleur=None, italique=False, police=None):
    rpr = '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>' % (police, police, police) if police else ""
    if gras:
        rpr += "<w:b/>"
    if italique:
        rpr += "<w:i/>"
    if couleur:
        rpr += '<w:color w:val="%s"/>' % couleur
    if taille:
        rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (round(taille * 2), round(taille * 2))
    morceaux = str(texte).split("\n")
    corps = '<w:br/>'.join('<w:t xml:space="preserve">%s</w:t>' % escape(m) for m in morceaux)
    return "<w:r>%s%s</w:r>" % ("<w:rPr>%s</w:rPr>" % rpr if rpr else "", corps)


def para(contenu, align=None, avant=0, apres=0, interligne=None):
    ppr = '<w:spacing w:before="%d" w:after="%d"%s/>' % (
        avant, apres, ' w:line="%d" w:lineRule="auto"' % interligne if interligne else "")
    if align:
        ppr += '<w:jc w:val="%s"/>' % align
    return "<w:p><w:pPr>%s</w:pPr>%s</w:p>" % (ppr, contenu)


def bordures(haut=None, bas=None, gauche=None, droite=None):
    def b(nom, v):
        if not v:
            return '<w:%s w:val="nil"/>' % nom
        return '<w:%s w:val="single" w:sz="%d" w:space="0" w:color="000000"/>' % (nom, v)
    return "<w:tcBorders>%s%s%s%s</w:tcBorders>" % (b("top", haut), b("left", gauche), b("bottom", bas), b("right", droite))


def cellule(contenu, largeur, fond=None, bords="", valign="top", marges=None):
    tcpr = '<w:tcW w:w="%d" w:type="dxa"/>%s' % (largeur, bords)
    if fond:
        tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fond
    if marges:
        tcpr += "<w:tcMar>%s</w:tcMar>" % "".join('<w:%s w:w="%d" w:type="dxa"/>' % (k, v) for k, v in marges.items())
    tcpr += '<w:vAlign w:val="%s"/>' % valign
    return "<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (tcpr, contenu)


def tableau(lignes, largeurs, align="left", bords_tableau=False, hauteurs=None):
    b = ('<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/>'
         '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>')
    tblpr = ('<w:tblW w:w="%d" w:type="dxa"/><w:jc w:val="%s"/>%s<w:tblLayout w:type="fixed"/>'
             '<w:tblCellMar><w:left w:w="85" w:type="dxa"/><w:right w:w="85" w:type="dxa"/></w:tblCellMar>'
             % (sum(largeurs), align, b))
    grille = "".join('<w:gridCol w:w="%d"/>' % l for l in largeurs)
    rows = []
    for i, cells in enumerate(lignes):
        trpr = ""
        if hauteurs and hauteurs[i]:
            trpr = '<w:trPr><w:trHeight w:val="%d" w:hRule="atLeast"/></w:trPr>' % hauteurs[i]
        rows.append("<w:tr>%s%s</w:tr>" % (trpr, "".join(cells)))
    return "<w:tbl><w:tblPr>%s</w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl>" % (tblpr, grille, "".join(rows))


def taille_png(chemin):
    with open(chemin, "rb") as fh:
        tete = fh.read(24)
    return struct.unpack(">II", tete[16:24])


def image(rid, num, nom, larg_mm=None, haut_mm=None, chemin=None):
    lp, hp = taille_png(chemin)
    if larg_mm:
        cx = int(larg_mm * EMU_MM)
        cy = int(cx * hp / lp)
    else:
        cy = int(haut_mm * EMU_MM)
        cx = int(cy * lp / hp)
    return (
        '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="%s"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:nvPicPr><pic:cNvPr id="%d" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
        % (cx, cy, num, nom, num, nom, rid, cx, cy))


# ---------------------------------------------------------------------------
# Corps de la facture
# ---------------------------------------------------------------------------
def mention(p):
    """Nom de l'entreprise sous la désignation, comme sur les factures d'ANO (« ANO SERVICE »)."""
    return (p.get("mention_designation") or p.get("raison_sociale") or "").strip().upper()


def _designation(f, p=None):
    """(désignation, quantité, unité, prix unitaire HT) ; 1re ligne, nom de l'entreprise, agent"""
    m = mention(p or {})
    d, q, u, pu = _designation_brute(f)
    if m:
        premiere, _, reste = d.partition("\n")
        d = "%s\n%s\n%s" % (premiere, m, reste)
    return d, q, u, pu


def _designation_brute(f):
    ht = f["montant_ht"]
    if f.get("groupe"):
        # facture groupée (ex. 9 infirmiers) : une ligne pour tout le groupe
        nb = f.get("nb_agents") or 1
        if f["type"] == M.TYPE_MAD:
            complet = f["jours"] == f["jours_mois"]
            return ("MAD de %d %s\n%s" % (nb, f["poste"], f["agent"]), "1" if complet else "%02d" % (f["jours"] or 0),
                    f.get("unite") or ("Mois" if complet else "Jours"), ht)
        if f["type"] == M.TYPE_VISITE:
            q = f["jours"] or 1
            return "Visite médicale\n%s" % f["agent"], str(q), f.get("unite") or "1", ht // q if q else ht
    if f["type"] == M.TYPE_MAD:
        # désignation sans dates : le mois facturé est dans le titre
        txt = "MAD d'un %s\n%s" % (f["poste"], f["agent"])
        return txt, "%02d" % (f["jours"] or 0), f.get("unite") or "Jours", ht
    if f["type"] == M.TYPE_VISITE:
        return "Visite médicale\n%s" % f["agent"], "1", f.get("unite") or "1", ht
    return "Ajustement selon PV\n%s" % f["agent"], "1", f.get("unite") or "Forfait", ht


def corps_document(p, f, avec_signature, logo=None, signature=None):
    x = []
    # En-tête : logo à gauche, émetteur à droite (souligné)
    # bloc ANO en Arial, double trait épais sous le logo (comme la facture 152 bis)
    emet = (para(run(p["raison_sociale"], gras=True, taille=11, police="Arial")) +
            "".join(para(run(t, taille=10.5, police="Arial")) for t in (p["adresse"], p["ville"], p["telephone"])) +
            para(run(p["email"], taille=9.5, couleur="0563C1", police="Arial")))
    trait = '<w:tcBorders><w:bottom w:val="double" w:sz="12" w:space="0" w:color="000000"/></w:tcBorders>'
    x.append(tableau([[cellule(para((image("rLogo", 1, "logo", haut_mm=25, chemin=logo) if logo else run(""))), 4800, bords=trait),
                       cellule("", 1000), cellule(emet, 3600, valign="top", marges={"top": 200})]],
                     [4800, 1000, 3600], align="center"))
    x.append(para("", apres=560))
    # Infos + client
    gauche = [
        "Date d'émission : %s" % date_fr(f["date_facture"]),
        "Emis par : %s" % p["raison_sociale"],
        "Commande client N° : %s" % (f["bc_numero"] or ""),
    ]
    cl = ["Nom du client : %s" % f["client_nom"], f["client_adresse"] or "", f["client_ville"] or ""]
    if f.get("client_telephone"):
        cl.append("Téléphone : %s" % f["client_telephone"])
    x.append(tableau([[
        cellule("".join(para(run(t, taille=11), align="right", apres=120) for t in gauche), 4700),
        cellule("", 600),
        cellule("".join(para(run(t, taille=11, couleur="FFFFFF"), align="center", apres=80) for t in cl if t), 4300,
                fond=BLEU, valign="center", marges={"top": 120, "bottom": 120, "left": 200, "right": 200}),
    ]], [4700, 600, 4300], align="center"))
    # Titre
    x.append(para(run("Facture %s" % mois_fr(f["mois"]), gras=True, taille=17), align="right", avant=1000))
    x.append(para(run("N° %s" % f["numero"], gras=True, taille=13), align="right", apres=900))
    # Tableau des prestations
    des, qte, unite, pu = _designation(f, p)
    larg = [3060, 1640, 1640, 1932, 1932]
    entetes = ["Désignation des produits ou des prestations", "Quantité", "Unité", "Prix unitaire HT", "TOTAL HT"]
    bt = bordures(1 * 8, 1 * 8, 1 * 8, 1 * 8)
    ligne_titres = [cellule(para(run(t, gras=True, taille=10), align="center"), l, fond=GRIS, bords=bt)
                    for t, l in zip(entetes, larg)]
    vals = [des, qte, unite, fmt_pt(pu), fmt_pt(f["montant_ht"])]
    ligne_vals = [cellule(para(run(v, taille=9), align="center", avant=60), l, bords=bt) for v, l in zip(vals, larg)]
    x.append(tableau([ligne_titres, ligne_vals], larg, align="center", hauteurs=[None, 500]))
    # Totaux
    lignes = [("Total HT", fmt_pt(f["montant_ht"]))]
    # « TVA (18 %) » partout (Luc) ; montant 0 sur la visite médicale
    lignes.append(("TVA (%s)" % pct(p["tva_pdm"]), fmt_pt(f["tva"])))
    tot = [[cellule(para(run(a, gras=True, taille=11), avant=60, apres=60), 1700),
            cellule(para(run(b, taille=11), avant=60, apres=60), 1600)] for a, b in lignes]
    tot.append([cellule(para("", apres=0), 1700, bords=bordures(bas=24)), cellule(para("", apres=0), 1600, bords=bordures(bas=24))])
    tot.append([cellule(para(run("Total TTC", gras=True, taille=11), avant=60), 1700),
                cellule(para(run(fmt_pt(f["ttc"]), gras=True, taille=11), avant=60), 1600)])
    x.append(para("", apres=560))
    x.append(tableau(tot, [1700, 1600], align="right"))
    # Signature
    sig = run("Signature :", gras=True, taille=11)
    if avec_signature:
        sig += run("\t") + image("rSig", 2, "cachet", larg_mm=30, chemin=signature)
    x.append('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="2600"/></w:tabs><w:spacing w:before="900"/>'
             '<w:ind w:left="1000"/></w:pPr>%s</w:p>' % sig)
    return "".join(x)


NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def facture_docx(p, f, avec_signature=True, prive=None, origine=True):
    """Renvoie le contenu binaire du .docx d'une facture émise. `prive` =
    dossier privé de l'entreprise (logo, cachet)."""
    logo = chemin_logo(prive, origine)
    signature = os.path.join(prive or os.path.join(ICI, "prive"), "signature.png")
    avec_signature = avec_signature and os.path.exists(signature)
    return paquet_docx(p, corps_document(p, f, avec_signature, logo, signature), logo, signature, avec_signature)


def paquet_docx(p, corps, logo, signature, avec_signature, marges=(567, 851, 851, 851)):
    """Assemble le .docx (zip) : corps XML, pied RCCM / NIF / banque, logo et cachet."""
    pied = (para(run("RCCM %s – NIF %s – N° CNSS %s" % (p["rccm"], p["nif"], p["cnss"]), taille=10), align="center") +
            para(run("Compte bancaire %s %s" % (p["banque"], p["compte"]), taille=10), align="center"))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s'
        '<w:sectPr><w:footerReference w:type="default" r:id="rPied"/>'
        '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
        'w:header="0" w:footer="400" w:gutter="0"/></w:sectPr></w:body></w:document>'
        % ((NS, corps) + tuple(marges)))
    footer = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr %s>%s</w:ftr>' % (NS, pied)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
              '<w:sz w:val="22"/><w:lang w:val="fr-FR"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
              '</w:docDefaults></w:styles>')
    rels_doc = ['<Relationship Id="rStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
                '<Relationship Id="rPied" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>']
    if logo:
        rels_doc.append('<Relationship Id="rLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/logo.png"/>')
    if avec_signature:
        rels_doc.append('<Relationship Id="rSig" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/cachet.png"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                   '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   '</Relationships>')
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
                   % "".join(rels_doc))
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/footer1.xml", footer)
        if logo:
            z.write(logo, "word/media/logo.png")
        if avec_signature:
            z.write(signature, "word/media/cachet.png")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fiche d'attachement des heures supplémentaires (remise au client, signée par l'agent)
# ---------------------------------------------------------------------------
GRIS_FONCE = "595959"
JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _plage(l):
    def h(t):
        return t.replace(":00", "h").replace(":", "h") if t else ""
    return "%s à %s" % (h(l["debut"]), h(l["fin"])) if l.get("debut") and l.get("fin") else ""


def _h(v):
    return ("%g" % float(v)).replace(".", ",")


def fiche_hs_docx(p, h, prive=None, origine=True):
    """Fiche d'attachement en Word, calquée sur la fiche imprimée : en-tête, titre, identité de l'agent,
    encadré client, créneaux, tableau semaine par semaine, signatures (agent : avant, après, payées,
    récupérées ; responsable : cachet)."""
    logo = chemin_logo(prive, origine)
    signature = os.path.join(prive or os.path.join(ICI, "prive"), "signature.png")
    avec_sig = os.path.exists(signature)
    x = []
    emet = (para(run(p["raison_sociale"], gras=True, taille=11, police="Arial")) +
            "".join(para(run(t, taille=10, police="Arial")) for t in (p["adresse"], p["ville"], p["telephone"])) +
            para(run(p["email"], taille=9, couleur="0563C1", police="Arial")))
    trait = '<w:tcBorders><w:bottom w:val="double" w:sz="6" w:space="0" w:color="000000"/></w:tcBorders>'
    x.append(tableau([[cellule(para(image("rLogo", 1, "logo", haut_mm=22, chemin=logo) if logo else run("")), 5200, bords=trait),
                       cellule("", 800), cellule(emet, 4200)]], [5200, 800, 4200], align="center"))
    x.append(para("", apres=160))
    x.append(tableau([[cellule(para(run("Fiche d'attachement pour la réalisation d'heures supplémentaires", gras=True, taille=13,
                                        couleur="FFFFFF"), align="center", avant=40, apres=40), LARGEUR, fond=GRIS_FONCE)]],
                     [LARGEUR], align="center"))
    x.append(para("", apres=160))
    ident = []
    if h.get("direction"):
        ident.append(para(run("Direction : ", gras=True, taille=10) + run(h["direction"], taille=10), apres=40))
    ident.append(para(run("Service : %s" % h.get("service", ""), gras=True, italique=True, taille=11), apres=40))
    for lib, cle in (("Section", "section"), ("Matricule", "matricule_client"), ("Catégorie", "categorie")):
        if h.get(cle):
            ident.append(para(run("%s : %s" % (lib, h[cle]), gras=True, taille=10), apres=20))
    ident.append(para(run(h["agent"], gras=True, taille=10), apres=20))
    c = h["client"]
    cl = ["Nom du client : %s" % c["nom"], c.get("adresse") or "", c.get("ville") or ""]
    if c.get("telephone"):
        cl.append("Téléphone : %s" % c["telephone"])
    bc = bordures(12, 12, 12, 12)
    x.append(tableau([[cellule("".join(ident), 5600), cellule("", 400),
                       cellule("".join(para(run(t, taille=10), apres=30) for t in cl if t), 4200, bords=bc,
                               marges={"top": 100, "bottom": 100, "left": 200, "right": 120})]],
                     [5600, 400, 4200], align="center"))
    x.append(para("", apres=200))
    bt = bordures(8, 8, 8, 8)
    x.append(tableau([[cellule(para(run("Planification d'heures supplémentaires pour raisons de service, selon les modalités suivantes :",
                                        italique=True, taille=9.5), align="center", avant=40, apres=40), LARGEUR, bords=bt)]],
                     [LARGEUR], align="center"))
    x.append(para("", apres=120))
    larg = [2100, 1700, 4100, 2300]
    lignes = [[cellule(para(run(t, gras=True, taille=9.5), align="center"), l, bords=bt, valign="center")
               for t, l in zip(["Heures prévues", "Date", "Justifications", "Heures supplémentaires réalisées"], larg)]]
    for l in h["lignes"]:
        vals = [_plage(l), date_fr(l["date"]), l.get("justification") or "", "%s H" % _h(l["heures"])]
        lignes.append([cellule(para(run(v, taille=9.5), align="center"), w, bords=bt, valign="center") for v, w in zip(vals, larg)])
    lignes.append([cellule(para(run("Total", gras=True, italique=True, taille=9.5), align="right"), sum(larg[:3]), bords=bt)
                   .replace("<w:tcPr>", '<w:tcPr><w:gridSpan w:val="3"/>', 1),
                   cellule(para(run("%s H" % _h(h["total_heures"]), gras=True, taille=9.5), align="center"), larg[3], bords=bt)])
    x.append(tableau(lignes, larg, align="center"))
    # semaine par semaine : total par jour, total de la semaine, répartition
    x.append(para("", apres=160))
    t = h["taux_pdm"]
    larg2 = [1900, 3900, 1100, 1100, 1100, 1100]
    sem = [[cellule(para(run(v, gras=True, taille=9), align="center"), w, bords=bt, valign="center") for v, w in zip(
        ["Semaine", "Heures par jour", "Total semaine", "%g%%" % (t[0] / 100), "%g%%" % (t[1] / 100), "%g%% (dim./férié)" % (t[2] / 100)], larg2)]]
    for w in h["semaines"]:
        jours = " · ".join("%s %s : %s h" % (JOURS[dt.date.fromisoformat(j["date"]).weekday()], date_fr(j["date"])[:5], _h(j["heures"]))
                           for j in w["jours"])
        vals = ["du %s au %s" % (date_fr(w["du"])[:5], date_fr(w["au"])[:5]), jours, _h(w["total"]), _h(w["h1"]), _h(w["h2"]), _h(w["h3"])]
        sem.append([cellule(para(run(v, taille=8.5), align="center"), l, bords=bt, valign="center") for v, l in zip(vals, larg2)])
    tot = h["proposition"]
    sem.append([cellule(para(run(v, gras=True, taille=9), align="center"), l, bords=bt) for v, l in zip(
        ["Total", "", _h(h["total_heures"]), _h(tot["h1"]), _h(tot["h2"]), _h(tot["h3"])], larg2)])
    x.append(tableau(sem, larg2, align="center"))
    # signatures : l'agent signe à chaque étape (avant, après, payées, récupérées)
    x.append(para("", apres=240))
    etapes = h.get("etapes") or {}
    agent = para(run("Signature de l'agent :", gras=True, taille=10), apres=80)
    for k, lib in ETAPES_HS:
        d = (etapes.get(k) or {}).get("date")
        agent += para(run("%s :%s" % (lib, "  signé le " + date_fr(d) if d else ""), taille=9.5), apres=160)
    resp = para(run("Signature Responsable %s :" % p["raison_sociale"], gras=True, taille=10), align="center", apres=60)
    if avec_sig:
        resp += para(image("rSig", 2, "cachet", larg_mm=26, chemin=signature), align="center")
    x.append(tableau([[cellule(agent, 4600), cellule("", 600), cellule(resp, 5000)]], [4600, 600, 5000], align="center"))
    return paquet_docx(p, "".join(x), logo, signature, avec_sig, marges=(567, 709, 851, 709))


ETAPES_HS = (("avant", "Avant"), ("apres", "Après"), ("payees", "Payées"), ("recuperees", "Récupérées"))


def nom_fiche_hs(h):
    return propre("Fiche d'attachement des heures supplementaires - %s_%s" % (
        date_fr(h.get("periode_au") or "").replace("/", "."), h["agent"])) + ".docx"


def lot_zip(fichiers):
    """Plusieurs factures : un .zip contenant un .docx par facture."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in fichiers:
            z.writestr(nom, contenu)
    return buf.getvalue()
