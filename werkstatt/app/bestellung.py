"""Kundenbestellung (Bestellformular) als PDF – nach der Papiervorlage der Werkstatt."""
from . import settings
from .pdf import DocPDF, dmy, eur, num


class BestellPDF(DocPDF):
    multi = False

    def footer(self):
        if self.multi:
            self.set_xy(15, -9)
            self.font(7, color=(150, 150, 150))
            self.cell(180, 4, f"Seite {self.page_no()} / {{nb}}", align="R")


def render(order=None, kunde=None, items=None, rechnung_nr=None):
    """Bestellformular als PDF. Ohne order = leeres Formular zum Ausdrucken."""
    s = {k: settings.get(k) for k in settings.DEFAULTS}
    o = order or {}
    k = kunde or {}
    items = items or []
    pdf = BestellPDF(s)
    pdf.set_margins(15, 12, 15)
    pdf.set_auto_page_break(False)
    pdf.multi = len(items) > 6
    pdf.add_page()
    X, BW = 15, 180
    grey = (120, 120, 120)
    line = (175, 175, 175)

    def box(x, y, w, h):
        pdf.set_draw_color(*line)
        pdf.set_line_width(0.25)
        pdf.rect(x, y, w, h)

    def field(x, y, w, h, label, value="", vsize=10):
        box(x, y, w, h)
        pdf.set_xy(x + 2, y + 1.3)
        pdf.font(8.3, True, (50, 50, 50))
        lw = pdf.get_string_width(pdf.t(label)) + 2
        pdf.cell(lw, 4.2, pdf.t(label))
        if value:
            pdf.font(vsize)
            if lw + pdf.get_string_width(pdf.t(value)) < w - 4 and h <= 11:
                pdf.set_xy(x + 2 + lw, y + 1.3)
                pdf.cell(w - lw - 4, 4.2, pdf.t(value))
            else:
                pdf.set_xy(x + 2, y + 5.6)
                pdf.multi_cell(w - 4, 4.4, pdf.t(value), align="L")

    def check(x, y, on, label):
        pdf.set_draw_color(90, 90, 90)
        pdf.set_line_width(0.3)
        if on:
            pdf.set_fill_color(*pdf.acc)
            pdf.rect(x, y + 0.6, 3.2, 3.2, style="DF")
        else:
            pdf.rect(x, y + 0.6, 3.2, 3.2)
        pdf.set_xy(x + 4.4, y)
        pdf.font(9, False, (40, 40, 40))
        w = pdf.get_string_width(pdf.t(label)) + 2
        pdf.cell(w, 4.4, pdf.t(label))
        return x + 4.4 + w + 3

    def section(y, title):
        pdf.set_xy(X, y)
        pdf.font(11.5, True, (105, 105, 105))
        pdf.cell(BW, 6, pdf.t(title))
        return y + 7

    def need(y, h):
        if y + h > 287:
            pdf.multi = True
            pdf.add_page()
            return 15
        return y

    # ---- Kopf ----
    pdf.set_xy(X, 10)
    pdf.font(21, True, pdf.acc)
    pdf.cell(BW, 9, pdf.t((s.get("firma_name") or "").upper()), align="C")
    if s.get("firma_slogan"):
        pdf.set_xy(X, 19.5)
        pdf.font(10, False, grey)
        pdf.cell(BW, 5, pdf.t(s["firma_slogan"]), align="C")
    pdf.set_xy(X, 27)
    pdf.font(15, True, (40, 40, 40))
    pdf.cell(BW, 7, "KUNDENBESTELLUNG", align="C")

    # ---- Kopfraster ----
    y = 37
    c1, c2, c3 = 65, 62, 53
    field(X, y, c1, 11, "Bestellnummer:", o.get("nr", ""))
    field(X + c1, y, c2, 11, "Bestelldatum:", dmy(o.get("eingang")))
    field(X + c1 + c2, y, c3, 11, "Vertrieb / Kreativabend:", o.get("vertrieb") or "", 9.5)
    y += 11
    field(X, y, c1, 11, "Voraussichtl. Fertigstellung:", dmy(o.get("termin")))
    box(X + c1, y, c2, 11)
    pdf.set_xy(X + c1 + 2, y + 3.4)
    pdf.font(8.3, True, (50, 50, 50))
    pdf.cell(17, 4.4, pdf.t("Übergabe:"))
    xx = check(X + c1 + 19, y + 3.4, o.get("uebergabe") == "abholung", "Abholung")
    check(xx, y + 3.4, o.get("uebergabe") == "versand", "Versand")
    field(X + c1 + c2, y, c3, 11, "Rechnungsnummer:", rechnung_nr or "", 9.5)
    y += 14

    # ---- 1. Kundendaten ----
    y = section(y, "1. Kundendaten")
    name = " ".join(x for x in (k.get("vorname"), k.get("nachname")) if x)
    if k.get("firma"):
        name = k["firma"] + (f" ({name})" if name else "")
    land = (k.get("land") or "").strip()
    adr = ", ".join(x for x in (k.get("strasse"), " ".join(v for v in (k.get("plz"), k.get("ort")) if v),
                                land if land.upper() not in ("", "AT", "ÖSTERREICH") else "") if x)
    field(X, y, 110, 10, "Name:", name)
    field(X + 110, y, 70, 10, "Telefon:", k.get("telefon") or "")
    y += 10
    field(X, y, 110, 10, "E-Mail:", k.get("email") or "")
    field(X + 110, y, 70, 10, "Kunden-Nr. (optional):", k.get("nr") or "")
    y += 10
    field(X, y, BW, 13, "Rechnungs-/Lieferanschrift:", adr)
    y += 17

    # ---- 2. Bestellte Artikel ----
    y = section(y, "2. Bestellte Artikel")
    cols = [("Pos.", 10, "C"), ("Artikel / Beschreibung", 44, "L"), ("Farbe / Material / Größe", 35, "L"),
            ("Personalisierung (genauer Text)", 42, "L"), ("Menge", 14, "R"), ("Einzelpreis €", 17.5, "R"),
            ("Gesamt €", 17.5, "R")]

    def thead(y):
        pdf.set_fill_color(236, 236, 236)
        x = X
        for name_, w, al in cols:
            pdf.set_draw_color(*line)
            pdf.rect(x, y, w, 10, style="DF")
            pdf.set_xy(x + 1, y + 1.2)
            pdf.font(7.6, True, (70, 70, 70))
            pdf.multi_cell(w - 2, 3.7, pdf.t(name_), align="R" if al == "R" else "L")
            x += w
        return y + 10

    y = thead(y)
    rows = list(items) + [None] * max(0, 5 - len(items))
    zwischen = 0.0
    for i, it in enumerate(rows, 1):
        texts = [str(i), "", "", "", "", "", ""]
        if it:
            menge, ep = float(it.get("menge") or 0), float(it.get("einzelpreis") or 0)
            zwischen += menge * ep
            art = it.get("bezeichnung") or ""
            if it.get("beschreibung"):
                art += "\n" + it["beschreibung"]
            texts = [str(i), art, it.get("farbe_material") or "", it.get("personalisierung") or "",
                     num(menge), eur(ep, " ").strip(), eur(menge * ep, " ").strip()]
        pdf.font(8.8)
        hmax = 9
        for (_, w, _), tx in zip(cols, texts):
            if tx:
                n = len(pdf.multi_cell(w - 2.4, 4.1, pdf.t(tx), dry_run=True, output="LINES"))
                hmax = max(hmax, n * 4.1 + 3)
        if y + hmax > 287:
            pdf.multi = True
            pdf.add_page()
            y = thead(15)
        x = X
        for ci, ((_, w, al), tx) in enumerate(zip(cols, texts)):
            pdf.set_draw_color(*line)
            pdf.rect(x, y, w, hmax)
            if tx:
                pdf.set_xy(x + 1.2, y + 1.6 if ci else y + hmax / 2 - 2)
                pdf.font(9 if ci == 0 else 8.8, ci == 0, (40, 40, 40))
                pdf.multi_cell(w - 2.4, 4.1, pdf.t(tx), align=al)
            x += w
        y += hmax

    versand = float(o.get("versand") or 0)
    ku = settings.flag("kleinunternehmer")
    ust_satz = 0 if ku else settings.num("ust_satz", 20)
    gesamt = (zwischen + versand) * (1 + ust_satz / 100)
    has = bool(items)
    y = need(y, 12) + 2
    field(X, y, 60, 10, "Zwischensumme:", eur(zwischen) if has else "")
    field(X + 60, y, 55, 10, "Versand:", (eur(versand) if versand else "–") if has else "")
    field(X + 115, y, 65, 10, "Gesamtbetrag:" if ku else f"Gesamt inkl. {num(ust_satz)} % USt:",
          eur(gesamt) if has else "", 10.5)
    y += 13

    # ---- 3. Ausführung & Zahlung ----
    y = need(y, 45)
    y = section(y, "3. Ausführung & Zahlung")
    lw, rw, hbox = 105, 75, 30
    box(X, y, lw, hbox)
    box(X + lw, y, rw, hbox)
    xx = X + 2
    za = (o.get("zahlungsart") or "").strip().lower()
    for art in [a.strip() for a in (s.get("zahlungsarten") or "").split(",") if a.strip()]:
        xx = check(xx, y + 2, za == art.lower(), art)
    anz = float(o.get("anzahlung") or 0)
    for dy, lab, val in ((8.5, "Anzahlung (falls vereinbart):", eur(anz) if anz else ("–" if has else "")),
                         (13.5, "Restbetrag:", eur(gesamt - anz) if has else "")):
        pdf.set_xy(X + 2, y + dy)
        pdf.font(8.3, True, (50, 50, 50))
        pdf.cell(44, 4.4, pdf.t(lab))
        pdf.font(9.5)
        pdf.cell(40, 4.4, pdf.t(val))
    pdf.set_xy(X + 2, y + 19)
    pdf.font(8.3, True, (50, 50, 50))
    pdf.cell(60, 4.4, pdf.t("Besondere Wünsche / Hinweise:"))
    if o.get("wuensche"):
        pdf.font(8.6)
        lines = pdf.multi_cell(lw - 4, 3.8, pdf.t(o["wuensche"]), dry_run=True, output="LINES")[:2]
        pdf.set_xy(X + 2, y + 23)
        pdf.multi_cell(lw - 4, 3.8, "\n".join(lines), align="L")
    zs = o.get("zahlungsstatus") or ""
    pdf.set_xy(X + lw + 2, y + 2)
    pdf.font(8.3, True, (50, 50, 50))
    pdf.cell(30, 4.4, "Zahlungsstatus:")
    xx = X + lw + 2
    for st in ("offen", "angezahlt", "bezahlt"):
        xx = check(xx, y + 7.5, zs == st, st)
    field(X + lw, y + 15, rw, 9, "Zahlungsdatum:", dmy(o.get("zahlungsdatum")))
    y += hbox + 4

    # ---- 4. Bestätigung ----
    y = need(y, 42)
    y = section(y, "4. Bestätigung der Bestellung")
    pdf.set_xy(X, y)
    pdf.font(9, False, (40, 40, 40))
    pdf.multi_cell(BW, 4.4, pdf.t(s.get("bestellung_bestaetigung") or ""), align="L")
    y = pdf.get_y() + 9
    pdf.set_draw_color(90, 90, 90)
    pdf.set_line_width(0.25)
    pdf.set_xy(X + 2, y)
    pdf.font(9, True, (50, 50, 50))
    pdf.cell(22, 4.4, "Ort, Datum:")
    pdf.line(X + 24, y + 4.4, X + 88, y + 4.4)
    pdf.set_xy(X + 98, y - 6)
    pdf.cell(60, 4.4, "Unterschrift Kunde/in:")
    pdf.line(X + 98, y + 4.4, X + BW, y + 4.4)
    y += 10

    # ---- Hinweis + Kontakt ----
    y = need(y, 16)
    pdf.set_draw_color(*line)
    pdf.line(X, y, X + BW, y)
    pdf.set_xy(X, y + 1.5)
    pdf.font(6.8, False, grey)
    pdf.multi_cell(BW, 3.2, pdf.t(s.get("bestellung_hinweis") or ""), align="L")
    y = pdf.get_y() + 2.5
    kontakt = ", ".join(x for x in (s.get("firma_strasse"), s.get("firma_plz_ort"),
                                    ("Tel. " + s["firma_tel"]) if s.get("firma_tel") else "") if x)
    pdf.set_xy(X, y)
    pdf.font(7.5, True, (80, 80, 80))
    lab = f"Kontaktdaten der {s.get('firma_name')}: "
    pdf.cell(pdf.get_string_width(pdf.t(lab)) + 1, 4, pdf.t(lab))
    pdf.font(7.5, False, (80, 80, 80))
    pdf.cell(90, 4, pdf.t(kontakt))
    pdf.set_x(X + 125)
    pdf.font(7.5, True, (80, 80, 80))
    pdf.cell(12, 4, "E-Mail:")
    pdf.font(7.5, False, (80, 80, 80))
    pdf.cell(43, 4, pdf.t(s.get("firma_email") or ""))
    return bytes(pdf.output())
