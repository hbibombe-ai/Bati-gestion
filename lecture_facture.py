"""Lecture d'une facture fournisseur jointe : extrait le texte d'un PDF et propose les champs de saisie.

Sans texte lisible (image, PDF scanné) ou sans bibliothèque PDF, rien n'est proposé : l'usager saisit les champs.
Les valeurs proposées doivent être vérifiées avant l'enregistrement."""
from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
RE_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b"
                     r"|\b(\d{1,2})\s+([A-Za-zéûèôâ]+)\.?\s+(\d{4})\b", re.I)
RE_NOMBRE = re.compile(r"\d{1,3}(?:[ .,  ]\d{3})+(?:[.,]\d{1,2})?\b|\d+(?:[.,]\d{1,2})?")


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def texte_pdf(contenu: bytes) -> str:
    """Texte des cinq premières pages d'un PDF, ou chaîne vide si la lecture est impossible."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        lecteur = PdfReader(io.BytesIO(contenu))
        return "\n".join((p.extract_text() or "") for p in lecteur.pages[:5])
    except Exception:
        return ""


def date_iso(texte: str) -> str | None:
    """Première date reconnue dans le texte, au format AAAA-MM-JJ."""
    m = RE_DATE.search(texte)
    if not m:
        return None
    try:
        if m.group(1):
            j, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif m.group(4):
            a, mo, j = int(m.group(4)), int(m.group(5)), int(m.group(6))
        else:
            j, a = int(m.group(7)), int(m.group(9))
            mo = MOIS.get(_norm(m.group(8)).rstrip("."))
            if not mo:
                return None
        return dt.date(a, mo, j).isoformat()
    except ValueError:
        return None


def montant_centimes(jeton: str) -> int | None:
    """« 1 234,56 » , « 1,234.56 » ou « 1.234 » → centimes."""
    jeton = jeton.replace(" ", " ").replace(" ", " ").strip()
    dec = None
    if "," in jeton and "." in jeton:
        dec = "," if jeton.rfind(",") > jeton.rfind(".") else "."
    elif "," in jeton or "." in jeton:
        sep = "," if "," in jeton else "."
        parties = jeton.split(sep)
        if len(parties) == 2 and len(parties[1]) in (1, 2):
            dec = sep
    entier, frac = (jeton.rsplit(dec, 1) if dec else (jeton, ""))
    entier = re.sub(r"[ .,]", "", entier)
    if not entier.isdigit() or (frac and not frac.isdigit()):
        return None
    return int(entier) * 100 + int(frac.ljust(2, "0")[:2] or 0)


def _lignes_avec(lignes: list[str], motif: str, exclure: str | None = None) -> list[str]:
    return [l for l in lignes if re.search(motif, _norm(l)) and not (exclure and re.search(exclure, _norm(l)))]


def _reference(lignes: list[str]) -> str | None:
    valeur = r"[\s:#.n°o]*([A-Za-z0-9][A-Za-z0-9\-/_.]*\d[A-Za-z0-9\-/_.]*)"
    for motif in (r"facture\s*(?:n[°o]|no|#|num)", r"invoice\s*(?:no|n[°o]|number|#)?", r"r[ée]f[ée]rence"):
        for ligne in lignes:
            for m in re.finditer(motif + valeur, ligne, re.I):
                jeton = m.group(1).rstrip(".")
                if len(jeton) >= 3 and not RE_DATE.search(jeton):
                    return jeton
    return None


def _montant(lignes: list[str]) -> int | None:
    groupes = (r"ttc|a payer|amount due|net a payer|total due|montant total|total general",
               r"total")
    for motif in groupes:
        for ligne in reversed(_lignes_avec(lignes, motif, exclure=r"\bht\b|hors taxe|tva\b.*total")):
            nombres = [montant_centimes(n) for n in RE_NOMBRE.findall(ligne)]
            nombres = [n for n in nombres if n]
            if nombres:
                return nombres[-1]
    return None


def _devise(texte: str) -> str | None:
    compte = {"USD": len(re.findall(r"\bUSD\b|US\$", texte)),
              "CDF": len(re.findall(r"\bCDF\b|\bFC\b", texte)),
              "EUR": len(re.findall(r"\bEUR\b|€", texte))}
    cible, n = max(compte.items(), key=lambda kv: kv[1])
    return cible if n else None


def _fournisseur(texte: str, fournisseurs: list[tuple[str, str]]) -> str | None:
    t = " " + re.sub(r"[^a-z0-9]+", " ", _norm(texte)) + " "
    meilleur, longueur = None, 0
    for identifiant, nom in fournisseurs:
        n = " " + re.sub(r"[^a-z0-9]+", " ", _norm(nom)).strip() + " "
        if len(n.strip()) >= 4 and n in t and len(n) > longueur:
            meilleur, longueur = identifiant, len(n)
    return meilleur


def extraire(texte: str, fournisseurs: list[tuple[str, str]]) -> dict:
    """Champs proposés à partir du texte : référence, dates, montant (centimes), monnaie, fournisseur."""
    lignes = [l for l in texte.splitlines() if l.strip()]
    res = {"reference": None, "date": None, "due": None, "amount": None, "currency": None, "party_id": None}
    if len(texte.strip()) < 20:
        res["lisible"] = False
        return res
    res["lisible"] = True
    res["reference"] = _reference(lignes)
    dates_facture = _lignes_avec(lignes, r"\bdate\b", exclure=r"echeance|due|paiement|payer")
    res["date"] = next((date_iso(l) for l in dates_facture if date_iso(l)), None)
    dates_echeance = _lignes_avec(lignes, r"echeance|due date|a payer avant|date limite")
    res["due"] = next((date_iso(l) for l in dates_echeance if date_iso(l)), None)
    res["amount"] = _montant(lignes)
    res["currency"] = _devise(texte)
    res["party_id"] = _fournisseur(texte, fournisseurs)
    return res


LIBELLES = {"reference": "référence", "date": "date de facture", "due": "échéance", "amount": "montant total",
            "currency": "monnaie", "party_id": "fournisseur"}


def bilan(res: dict) -> tuple[list[str], list[str]]:
    """Champs trouvés et champs à saisir à la main."""
    trouves = [LIBELLES[k] for k in LIBELLES if res.get(k)]
    manquants = [LIBELLES[k] for k in LIBELLES if not res.get(k)]
    return trouves, manquants
