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
def _designation(f):
    if f["type"] == M.TYPE_MAD:
        # désignation sans dates : le mois facturé est dans le titre
        txt = "MAD d'un %s\n%s" % (f["poste"], f["agent"])
        return txt, "%02d" % (f["jours"] or 0), "Jours"
    if f["type"] == M.TYPE_VISITE:
        return "Visite médicale\n%s" % f["agent"], "1", "1"
    return "Ajustement selon PV\n%s" % f["agent"], "1", "Forfait"


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
    des, qte, unite = _designation(f)
    larg = [3060, 1640, 1640, 1932, 1932]
    entetes = ["Désignation des produits ou des prestations", "Quantité", "Unité", "Prix unitaire HT", "TOTAL HT"]
    bt = bordures(1 * 8, 1 * 8, 1 * 8, 1 * 8)
    ligne_titres = [cellule(para(run(t, gras=True, taille=10), align="center"), l, fond=GRIS, bords=bt)
                    for t, l in zip(entetes, larg)]
    vals = [des, qte, unite, fmt_pt(f["montant_ht"]), fmt_pt(f["montant_ht"])]
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
    pied = (para(run("RCCM %s – NIF %s – N° CNSS %s" % (p["rccm"], p["nif"], p["cnss"]), taille=10), align="center") +
            para(run("Compte bancaire %s %s" % (p["banque"], p["compte"]), taille=10), align="center"))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s'
        '<w:sectPr><w:footerReference w:type="default" r:id="rPied"/>'
        '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="567" w:right="851" w:bottom="851" w:left="851" '
        'w:header="0" w:footer="400" w:gutter="0"/></w:sectPr></w:body></w:document>'
        % (NS, corps_document(p, f, avec_signature, logo, signature)))
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


def lot_zip(fichiers):
    """Plusieurs factures : un .zip contenant un .docx par facture."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in fichiers:
            z.writestr(nom, contenu)
    return buf.getvalue()
