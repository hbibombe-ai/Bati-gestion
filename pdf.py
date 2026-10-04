"""Documents PDF (devis, factures, bulletins, états, fiches) générés côté serveur avec ReportLab."""
from __future__ import annotations

import datetime as dt
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MARINE = colors.HexColor("#112740")
ORANGE = colors.HexColor("#EFA63A")
GRIS = colors.HexColor("#5B6E83")
FOND = colors.HexColor("#EEF2F6")
TRAIT = colors.HexColor("#CBD5E0")

_ss = getSampleStyleSheet()
ST = {
    "titre": ParagraphStyle("titre", parent=_ss["Title"], fontName="Helvetica-Bold", fontSize=16, leading=20,
                            alignment=0, textColor=MARINE, spaceAfter=4),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15,
                         textColor=MARINE, spaceBefore=8, spaceAfter=4),
    "p": ParagraphStyle("p", parent=_ss["Normal"], fontName="Helvetica", fontSize=9, leading=12),
    "petit": ParagraphStyle("petit", parent=_ss["Normal"], fontName="Helvetica", fontSize=7.8, leading=10,
                            textColor=GRIS),
    "cell": ParagraphStyle("cell", parent=_ss["Normal"], fontName="Helvetica", fontSize=8, leading=10),
    "cellr": ParagraphStyle("cellr", parent=_ss["Normal"], fontName="Helvetica", fontSize=8, leading=10,
                            alignment=TA_RIGHT),
    "cellb": ParagraphStyle("cellb", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10,
                            textColor=colors.white),
    "ent_nom": ParagraphStyle("ent_nom", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=14,
                              textColor=MARINE),
    "mention": ParagraphStyle("mention", parent=_ss["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12,
                              textColor=colors.HexColor("#A62D25"), spaceBefore=6),
}
_REMPLACE = {" ": " ", "→": "->", "≤": "<=", "≥": ">=", "×": "x", "−": "-"}


def _t(v) -> str:
    """Texte sûr pour ReportLab (XML échappé, caractères hors Windows-1252 remplacés)."""
    s = "" if v is None else str(v)
    for a, b in _REMPLACE.items():
        s = s.replace(a, b)
    s = s.encode("cp1252", errors="replace").decode("cp1252")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def entete(c: dict | None) -> list:
    if not c:
        return []
    ids = " · ".join(f"{k} : {v}" for k, v in (("RCCM", c.get("rccm")), ("ID NAT", c.get("nationalId")),
                                                ("NIF", c.get("taxId")), ("TVA", c.get("vatId"))) if v)
    lignes = [_t(c.get("address") or "Adresse officielle à qualifier"), _t(c.get("phone")),
              " · ".join(_t(x) for x in (c.get("email"), c.get("website")) if x), _t(ids)]
    corps = [Paragraph(_t(c.get("name")), ST["ent_nom"])] + [Paragraph(l, ST["petit"]) for l in lignes if l]
    if c.get("footer"):
        corps.append(Paragraph(_t(c["footer"]), ST["petit"]))
    t = Table([[corps]], colWidths=["100%"])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, ORANGE), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [t, Spacer(1, 8)]


def tableau(entetes: list[str], lignes: list[list], droite: set[int] | None = None, largeurs=None,
            total: bool = False) -> Table:
    droite = droite or set()
    data = [[Paragraph(_t(h), ST["cellb"]) for h in entetes]]
    for l in lignes:
        data.append([Paragraph(_t(v), ST["cellr"] if i in droite else ST["cell"]) for i, v in enumerate(l)])
    t = Table(data, colWidths=largeurs, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), MARINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, TRAIT), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FOND]),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if total and len(data) > 1:
        style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def kv(lignes: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(f"<b>{_t(k)}</b>", ST["cell"]), Paragraph(_t(v if v not in (None, "") else "Non renseigné"),
                                                                 ST["cell"])] for k, v in lignes]
    t = Table(data, colWidths=[55 * mm, None])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, TRAIT), ("BACKGROUND", (0, 0), (0, -1), FOND),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def document(titre: str, entete_societe: dict | None, blocs: list, paysage: bool = False,
             auteur: str = "") -> bytes:
    """blocs : ("h2", texte) · ("p", texte) · ("petit", texte) · ("mention", texte) · ("kv", [(k, v)])
    · ("table", entetes, lignes, colonnes_a_droite, largeurs) · ("espace", hauteur_mm)."""
    buf = io.BytesIO()
    taille = landscape(A4) if paysage else A4
    edite = dt.datetime.now().strftime("%d/%m/%Y %H:%M")

    def pied(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRIS)
        txt = f"Bâti Gestion · édité le {edite}" + (f" par {auteur}" if auteur else "") + f" · page {doc_.page}"
        canvas.drawString(15 * mm, 9 * mm, txt.encode("cp1252", "replace").decode("cp1252"))
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=taille, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=titre, author="Bâti Gestion — MY DESTINY")
    els = entete(entete_societe) + [Paragraph(_t(titre), ST["titre"])]
    for b in blocs:
        k = b[0]
        if k in ("h2", "p", "petit", "mention"):
            els.append(Paragraph(_t(b[1]), ST[k]))
        elif k == "kv":
            els += [kv(b[1]), Spacer(1, 6)]
        elif k == "table":
            entetes, lignes = b[1], b[2]
            droite = b[3] if len(b) > 3 else None
            largeurs = b[4] if len(b) > 4 else None
            tot = b[5] if len(b) > 5 else False
            els += [tableau(entetes, lignes, droite, largeurs, tot), Spacer(1, 6)]
        elif k == "espace":
            els.append(Spacer(1, b[1] * mm))
        elif k == "groupe":
            els.append(KeepTogether(b[1]))
    doc.build(els, onFirstPage=pied, onLaterPages=pied)
    return buf.getvalue()
