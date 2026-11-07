"""Startdaten beim allerersten Start: Personen, Maschinen (grobe Richtwerte), Materialien.

Alle Zahlen sind grobe Schätzwerte (Stand Ende 2026) und in der Oberfläche änderbar.
"""

PERSONS = [
    ("Tanja", 25, 35, "#e8590c"),
    ("Christian", 25, 35, "#4ea1ff"),
]

# name, typ, hersteller, modell, preis €, lebensdauer h, mittlere Leistung W, farbe, notiz, verschleißteile
MACHINES = [
    ("Bambu Lab X2D", "fdm", "Bambu Lab", "X2D (Combo mit AMS 2 Pro)", 950, 8000, 200, "#4ea1ff",
     "Doppeldüse, beheizter Bauraum. Verbrauch: PLA ca. 150–170 W, ABS/ASA mit Kammerheizung ca. 330 W.",
     [("Hotend / Düse (2 Stück)", 45, 1500), ("Bauplatte (PEI)", 35, 2000),
      ("Aktivkohle-/HEPA-Filter", 25, 1000), ("Riemen, Lager, Schmierung", 40, 4000),
      ("Schneidklinge / PTFE-Schläuche", 10, 1500)]),
    ("Bambu Lab P1S", "fdm", "Bambu Lab", "P1S (Combo mit AMS)", 700, 6000, 130, "#3fb950",
     "Geschlossener CoreXY. Mittlere Leistung PLA ca. 110–140 W.",
     [("Hotend komplett", 20, 1000), ("Bauplatte (PEI)", 35, 1500),
      ("Carbonstangen + Riemen", 35, 3000), ("Aktivkohlefilter", 10, 1000),
      ("Schneidklinge / PTFE-Schläuche", 8, 1500)]),
    ("Bambu Lab A1", "fdm", "Bambu Lab", "A1 (Combo mit AMS lite)", 480, 5000, 95, "#d29922",
     "Bettschubser, offen. Mittlere Leistung PLA ca. 80–110 W.",
     [("Hotend komplett", 15, 1000), ("Bauplatte (PEI)", 30, 1500),
      ("Riemen, Rollen, Lager", 25, 3000), ("Schneidklinge / PTFE-Schläuche", 6, 1500)]),
    ("Bambu Lab A2L", "fdm", "Bambu Lab", "A2L (Combo mit AMS lite)", 490, 6000, 120, "#b083f0",
     "Großer Bettschubser 330 × 320 × 325 mm. Mittlere Leistung PLA ca. 100–140 W.",
     [("Hotend komplett", 15, 1000), ("Bauplatte (PEI, groß)", 40, 1500),
      ("Riemen, Rollen, Lager", 30, 3000), ("Schneidklinge / PTFE-Schläuche", 6, 1500)]),
    ("Longer Ray5 20W", "laser", "Longer", "Ray5 20 W Diodenlaser", 550, 6000, 150, "#f85149",
     "20 W optisch, Leistungsaufnahme inkl. Air-Assist ca. 120–160 W. Absaugung ggf. extra.",
     [("Lasermodul 20 W", 300, 8000), ("Schutzglas / Linse", 12, 300),
      ("Wabentisch", 40, 2000), ("Riemen, Rollen", 20, 3000)]),
]

# name, typ, hersteller, farbe, einheit, preis
MATERIALS = [
    ("PLA Basic", "filament", "Bambu Lab", "diverse", "kg", 20),
    ("PLA Matte", "filament", "Bambu Lab", "diverse", "kg", 20),
    ("PLA Silk", "filament", "Bambu Lab", "diverse", "kg", 25),
    ("PETG HF", "filament", "Bambu Lab", "diverse", "kg", 20),
    ("ABS", "filament", "Bambu Lab", "diverse", "kg", 20),
    ("ASA", "filament", "Bambu Lab", "diverse", "kg", 25),
    ("TPU 95A", "filament", "Bambu Lab", "diverse", "kg", 35),
    ("Pappel-Sperrholz 3 mm (300×400)", "platte", "", "natur", "Stück", 2.5),
    ("Pappel-Sperrholz 4 mm (300×400)", "platte", "", "natur", "Stück", 3.0),
    ("MDF 3 mm (300×400)", "platte", "", "natur", "Stück", 1.5),
    ("Acryl 3 mm (300×400)", "platte", "", "diverse", "Stück", 8.0),
    ("Schiefer-Untersetzer 10×10", "sonstiges", "", "schwarz", "Stück", 1.5),
]


HA_LISTEN = {"Bambu Lab X2D": "todo.x2d_druckprotokoll", "Bambu Lab P1S": "todo.p1s_druckprotokoll",
             "Bambu Lab A1": "todo.a1_druckprotokoll", "Bambu Lab A2L": "todo.a2l_druckprotokoll"}


def run(c):
    for name, sts, vs, farbe in PERSONS:
        c.execute("INSERT INTO persons(name, stundensatz, verrechnungssatz, farbe) VALUES(?,?,?,?)",
                  (name, sts, vs, farbe))
    for (name, typ, her, modell, preis, lh, w, farbe, notiz, parts) in MACHINES:
        cur = c.execute(
            "INSERT INTO machines(name, typ, hersteller, modell, anschaffung_preis, lebensdauer_h, leistung_w,"
            " farbe, notizen, ha_liste) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (name, typ, her, modell, preis, lh, w, farbe, notiz, HA_LISTEN.get(name)))
        for pname, ppreis, plh in parts:
            c.execute("INSERT INTO wear_parts(machine_id, name, preis, lebensdauer_h) VALUES(?,?,?,?)",
                      (cur.lastrowid, pname, ppreis, plh))
    for name, typ, her, farbe, einheit, preis in MATERIALS:
        c.execute("INSERT INTO materials(name, typ, hersteller, farbe, einheit, preis) VALUES(?,?,?,?,?,?)",
                  (name, typ, her, farbe, einheit, preis))
