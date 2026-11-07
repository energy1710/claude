"""PDF-Erzeugung für Rechnungen und Angebote (Layout aus der Rechnungsvorlage in den Einstellungen)."""
import os
from datetime import date

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from . import db, settings

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]

L, R, W = 20, 18, 210 - 20 - 18


def _fonts():
    for reg, bold in FONT_CANDIDATES:
        if os.path.exists(reg) and os.path.exists(bold):
            return reg, bold
    return None, None


def eur(x, cur=None):
    cur = cur or settings.get("currency") or "€"
    s = f"{float(x or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {cur}"


def num(x):
    x = float(x or 0)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")


def dmy(iso):
    if not iso:
        return ""
    try:
        y, m, d = iso[:10].split("-")
        return f"{d}.{m}.{y}"
    except ValueError:
        return iso


def _rgb(hexcol):
    h = (hexcol or "#e8590c").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (232, 89, 12)


def kunde_lines(k):
    if not k:
        return []
    out = []
    if k.get("firma"):
        out.append(k["firma"])
    name = " ".join(x for x in (k.get("anrede"), k.get("vorname"), k.get("nachname")) if x)
    if name:
        out.append(name if not k.get("firma") else "z. H. " + name)
    if k.get("strasse"):
        out.append(k["strasse"])
    po = " ".join(x for x in (k.get("plz"), k.get("ort")) if x)
    if po:
        out.append(po)
    land = (k.get("land") or "").strip()
    norm = {"ÖSTERREICH": "AT", "OESTERREICH": "AT", "AUSTRIA": "AT", "DEUTSCHLAND": "DE", "GERMANY": "DE"}
    if land and norm.get(land.upper(), land.upper()) != (settings.get("firma_land") or "AT").upper():
        out.append({"AT": "Österreich", "DE": "Deutschland"}.get(norm.get(land.upper(), land.upper()), land))
    return out


def pos_desc(p):
    """Beschreibung einer Position inkl. Farbe/Material/Größe und Personalisierung."""
    parts = []
    if p.get("beschreibung"):
        parts.append(p["beschreibung"])
    if p.get("farbe_material"):
        parts.append(p["farbe_material"])
    if p.get("personalisierung"):
        parts.append(f"Personalisierung: „{p['personalisierung']}“")
    return "\n".join(parts)


def fill_placeholders(text, doc):
    vals = {
        "nr": doc.get("nr", ""),
        "datum": dmy(doc.get("datum")),
        "faellig": dmy(doc.get("faellig")),
        "gueltig": dmy(doc.get("faellig")),
        "gesamt": eur(doc.get("brutto")),
        "zahlbetrag": eur(float(doc.get("brutto") or 0) - float(doc.get("anzahlung") or 0)),
        "tage": settings.get("zahlungsziel_tage"),
        "kunde": (doc.get("kunde") or {}).get("firma") or " ".join(
            x for x in ((doc.get("kunde") or {}).get("vorname"), (doc.get("kunde") or {}).get("nachname")) if x),
    }
    out = text or ""
    for k, v in vals.items():
        out = out.replace("{" + k + "}", str(v))
    return out


class DocPDF(FPDF):
    def __init__(self, s):
        super().__init__(format="A4", unit="mm")
        self.s = s
        reg, bold = _fonts()
        if reg:
            self.add_font("W", "", reg)
            self.add_font("W", "B", bold)
            self.fam = "W"
        else:  # Notlösung ohne Unicode-Schrift
            self.fam = "helvetica"
        self.acc = _rgb(s.get("akzentfarbe"))
        self.set_margins(L, 15, R)
        self.set_auto_page_break(True, margin=32)
        self.alias_nb_pages()

    def t(self, s):
        s = "" if s is None else str(s)
        if self.fam == "helvetica":
            s = s.replace("€", "EUR").replace("–", "-").replace("„", '"').replace("“", '"')
            s = s.encode("latin-1", "replace").decode("latin-1")
        return s

    def font(self, size, bold=False, color=(30, 30, 30)):
        self.set_font(self.fam, "B" if bold else "", size)
        self.set_text_color(*color)

    def footer(self):
        s = self.s
        self.set_y(-27)
        self.set_draw_color(*self.acc)
        self.set_line_width(0.4)
        self.line(L, self.get_y(), 210 - R, self.get_y())
        self.ln(2)
        cols = [
            [s.get("firma_name"), s.get("firma_inhaber"), s.get("firma_strasse"), s.get("firma_plz_ort")],
            [("Tel. " + s["firma_tel"]) if s.get("firma_tel") else "", s.get("firma_email"), s.get("firma_web"),
             ("UID: " + s["firma_uid"]) if s.get("firma_uid") else
             (("St.-Nr.: " + s["firma_steuernr"]) if s.get("firma_steuernr") else "")],
            [s.get("bank_name"), ("IBAN: " + s["bank_iban"]) if s.get("bank_iban") else "",
             ("BIC: " + s["bank_bic"]) if s.get("bank_bic") else "", ""],
        ]
        y0 = self.get_y()
        cw = W / 3
        for i, col in enumerate(cols):
            self.set_xy(L + i * cw, y0)
            self.font(7.5, color=(110, 110, 110))
            lines = [x for x in col if x]
            self.multi_cell(cw - 3, 3.6, self.t("\n".join(lines)), new_x=XPos.RIGHT, new_y=YPos.TOP)
        if s.get("fusszeile"):
            self.set_xy(L, y0 + 15)
            self.font(7, color=(140, 140, 140))
            self.cell(W, 3.5, self.t(s["fusszeile"]), align="C")
        self.set_xy(L, -9)
        self.font(7, color=(150, 150, 150))
        self.cell(W, 4, f"Seite {self.page_no()} / {{nb}}", align="R")


def render(doc, out_path=None):
    """doc: typ, nr, datum, leistungsdatum, faellig, kunde{}, positionen[], einleitung, schluss,
    netto, ust_satz, ust, brutto, kleinunternehmer, auftrag_nr, auftrag_titel"""
    s = {k: settings.get(k) for k in settings.DEFAULTS}
    pdf = DocPDF(s)
    pdf.add_page()
    typ = doc.get("typ", "rechnung")
    titel = "Angebot" if typ == "angebot" else ("Stornorechnung" if doc.get("storno") else "Rechnung")

    # ---- Kopf ----
    logo = os.path.join(db.VORLAGE_DIR, s.get("logo") or "") if s.get("logo") else None
    if logo and os.path.exists(logo):
        try:
            pdf.image(logo, x=210 - R - 55, y=12, w=55, h=24, keep_aspect_ratio=True)
        except Exception:
            pass
    pdf.set_xy(L, 15)
    pdf.font(17, True, pdf.acc)
    pdf.cell(110, 8, pdf.t(s.get("firma_name")), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.font(8.5, color=(100, 100, 100))
    if s.get("firma_slogan"):
        pdf.font(9.5, color=(110, 110, 110))
        pdf.cell(110, 5, pdf.t(s["firma_slogan"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.font(8.5, color=(100, 100, 100))
    sub = " · ".join(x for x in (s.get("firma_inhaber"), s.get("firma_web") or s.get("firma_email")) if x)
    if sub:
        pdf.cell(110, 4.5, pdf.t(sub), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- Absenderzeile + Empfänger (Fensterkuvert) ----
    absender = " · ".join(x for x in (s.get("firma_name"), s.get("firma_strasse"), s.get("firma_plz_ort")) if x)
    pdf.set_xy(L, 45)
    pdf.font(7, color=(120, 120, 120))
    pdf.cell(85, 4, pdf.t(absender))
    pdf.set_draw_color(190, 190, 190)
    pdf.set_line_width(0.15)
    pdf.line(L, 49.2, L + 85, 49.2)
    pdf.set_xy(L, 51)
    pdf.font(10.5)
    pdf.multi_cell(85, 5, pdf.t("\n".join(kunde_lines(doc.get("kunde")))))

    # ---- Infoblock rechts ----
    info = [(f"{titel}snummer" if typ != "angebot" else "Angebotsnummer", doc.get("nr"))]
    info.append(("Datum", dmy(doc.get("datum"))))
    if typ == "rechnung" and doc.get("leistungsdatum"):
        info.append(("Leistungsdatum", doc.get("leistungsdatum_text") or dmy(doc.get("leistungsdatum"))))
    if (doc.get("kunde") or {}).get("nr"):
        info.append(("Kundennummer", doc["kunde"]["nr"]))
    if doc.get("auftrag_nr"):
        info.append(("Auftrag", doc["auftrag_nr"]))
    if doc.get("faellig"):
        info.append(("Gültig bis" if typ == "angebot" else "Fällig am", dmy(doc.get("faellig"))))
    if (doc.get("kunde") or {}).get("uid"):
        info.append(("UID Kunde", doc["kunde"]["uid"]))
    y = 51
    for k, v in info:
        pdf.set_xy(122, y)
        pdf.font(8.5, color=(110, 110, 110))
        pdf.cell(32, 5, pdf.t(k))
        pdf.font(9, True)
        pdf.cell(210 - R - 154, 5, pdf.t(v), align="R")
        y += 5.2

    # ---- Titel + Einleitung ----
    pdf.set_xy(L, max(98, y + 8))
    pdf.font(16, True)
    pdf.cell(W, 8, pdf.t(f"{titel} {doc.get('nr', '')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if doc.get("auftrag_titel"):
        pdf.font(9.5, color=(100, 100, 100))
        pdf.cell(W, 5, pdf.t(doc["auftrag_titel"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    if doc.get("einleitung"):
        pdf.font(10)
        pdf.multi_cell(W, 5, pdf.t(fill_placeholders(doc["einleitung"], doc)), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

    # ---- Positionen ----
    cols = [("Pos.", 11, "L"), ("Bezeichnung", W - 11 - 18 - 16 - 27 - 27, "L"), ("Menge", 18, "R"),
            ("Einh.", 16, "L"), ("Einzelpreis", 27, "R"), ("Gesamt", 27, "R")]

    def head():
        pdf.set_fill_color(*[int(c + (255 - c) * 0.88) for c in pdf.acc])
        pdf.font(8.5, True, (60, 60, 60))
        x = L
        for name, w, al in cols:
            pdf.set_xy(x, pdf.get_y())
            pdf.cell(w, 7, pdf.t(name), align=al, fill=True)
            x += w
        pdf.ln(8)

    head()
    for i, p in enumerate(doc.get("positionen") or [], 1):
        bez = pdf.t(p.get("bezeichnung") or "")
        besch = pdf.t(pos_desc(p))
        bw = cols[1][1] - 2
        pdf.font(9.5, True)
        l1 = pdf.multi_cell(bw, 4.8, bez, dry_run=True, output="LINES") if bez else []
        pdf.font(8.5)
        l2 = pdf.multi_cell(bw, 4.2, besch, dry_run=True, output="LINES") if besch else []
        h = len(l1) * 4.8 + len(l2) * 4.2 + 3
        if pdf.get_y() + h > 297 - 34:
            pdf.add_page()
            pdf.set_y(20)
            head()
        y0 = pdf.get_y()
        menge, ep = float(p.get("menge") or 0), float(p.get("einzelpreis") or 0)
        vals = [str(i), None, num(menge), p.get("einheit") or "", eur(ep), eur(menge * ep)]
        x = L
        for (name, w, al), v in zip(cols, vals):
            if v is not None:
                pdf.set_xy(x, y0)
                pdf.font(9.5)
                pdf.cell(w, 4.8, pdf.t(v), align=al)
            x += w
        pdf.set_xy(L + cols[0][1], y0)
        if bez:
            pdf.font(9.5, True)
            pdf.multi_cell(bw, 4.8, bez, new_x=XPos.LEFT, new_y=YPos.NEXT)
        if besch:
            pdf.font(8.5, color=(100, 100, 100))
            pdf.multi_cell(bw, 4.2, besch, new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_y(y0 + h)
        pdf.set_draw_color(225, 225, 225)
        pdf.set_line_width(0.15)
        pdf.line(L, pdf.get_y() - 1, 210 - R, pdf.get_y() - 1)

    # ---- Summen ----
    if pdf.get_y() > 297 - 34 - 30:
        pdf.add_page()
        pdf.set_y(20)
    pdf.ln(2)
    xs, wl, wv = 210 - R - 85, 55, 30

    def sumrow(label, val, bold=False, big=False):
        pdf.set_x(xs)
        pdf.font(11 if big else 9.5, bold)
        pdf.cell(wl, 6 if big else 5.2, pdf.t(label))
        pdf.cell(wv, 6 if big else 5.2, pdf.t(val), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    ku = bool(doc.get("kleinunternehmer"))
    if not ku:
        sumrow("Summe netto", eur(doc.get("netto")))
        sumrow(f"zzgl. {num(doc.get('ust_satz'))} % USt.", eur(doc.get("ust")))
    pdf.set_draw_color(*pdf.acc)
    pdf.set_line_width(0.5)
    pdf.line(xs, pdf.get_y() + 0.5, 210 - R, pdf.get_y() + 0.5)
    pdf.ln(1.5)
    sumrow("Gesamtbetrag" if typ == "rechnung" else "Angebotssumme", eur(doc.get("brutto")), True, True)
    anz = float(doc.get("anzahlung") or 0)
    if anz > 0 and typ == "rechnung":
        sumrow("abzüglich Anzahlung", "– " + eur(anz))
        sumrow("Offener Restbetrag", eur(float(doc.get("brutto") or 0) - anz), True)
    pdf.ln(4)
    if ku and s.get("kleinunternehmer_text"):
        pdf.font(8.5, color=(90, 90, 90))
        pdf.multi_cell(W, 4.5, pdf.t(s["kleinunternehmer_text"]), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
    if doc.get("schluss"):
        pdf.font(10)
        pdf.multi_cell(W, 5, pdf.t(fill_placeholders(doc["schluss"], doc)), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    data = bytes(pdf.output())
    if out_path:
        with open(out_path, "wb") as fh:
            fh.write(data)
    return data


def sample():
    """Musterrechnung für die Vorschau in den Einstellungen."""
    ust = 0 if settings.flag("kleinunternehmer") else settings.num("ust_satz", 20)
    pos = [
        {"bezeichnung": "3D-Druck Ersatzteil Halterung", "beschreibung": "PETG schwarz, inkl. Konstruktion",
         "menge": 4, "einheit": "Stk", "einzelpreis": 12.5},
        {"bezeichnung": "Lasergravur Holzschild 30 × 20 cm", "beschreibung": "Pappel-Sperrholz 4 mm, Wunschtext",
         "menge": 1, "einheit": "Stk", "einzelpreis": 29.0},
        {"bezeichnung": "Konstruktion / CAD", "beschreibung": "", "menge": 1.5, "einheit": "Std", "einzelpreis": 35},
    ]
    netto = sum(p["menge"] * p["einzelpreis"] for p in pos)
    today = date.today().isoformat()
    doc = {"typ": "rechnung", "nr": f"{settings.get('prefix_rechnung')}{date.today().year}-001",
           "datum": today, "leistungsdatum": today, "faellig": today, "auftrag_nr": "A-2026-001",
           "auftrag_titel": "Musterauftrag",
           "kunde": {"nr": "K-0001", "vorname": "Max", "nachname": "Mustermann", "strasse": "Musterstraße 1",
                     "plz": "1234", "ort": "Musterort"},
           "positionen": pos, "einleitung": settings.get("rechnung_einleitung"),
           "schluss": settings.get("rechnung_schluss"), "netto": netto, "ust_satz": ust,
           "ust": round(netto * ust / 100, 2), "brutto": round(netto * (1 + ust / 100), 2),
           "kleinunternehmer": settings.flag("kleinunternehmer")}
    return render(doc)
