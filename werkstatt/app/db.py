"""SQLite-Datenbank: Schema, Verbindung, kleine Helfer."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date

DATA_DIR = os.environ.get("DATA_DIR", "/var/lib/werkstatt")
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "werkstatt.db"))
BILDER_DIR = os.path.join(DATA_DIR, "bilder")
DOKU_DIR = os.path.join(DATA_DIR, "dokumente")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
VORLAGE_DIR = os.path.join(DATA_DIR, "vorlage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY,
  nr TEXT,
  firma TEXT, anrede TEXT, vorname TEXT, nachname TEXT,
  strasse TEXT, plz TEXT, ort TEXT, land TEXT,
  email TEXT, telefon TEXT, uid TEXT,
  notizen TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persons(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  stundensatz REAL DEFAULT 25,        -- interne Kosten €/h
  verrechnungssatz REAL DEFAULT 35,   -- €/h an Kunden (für Positionen)
  farbe TEXT,
  aktiv INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS machines(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  typ TEXT DEFAULT 'fdm',             -- fdm | laser | sonstige
  hersteller TEXT, modell TEXT,
  anschaffung_preis REAL DEFAULT 0,
  anschaffung_datum TEXT,
  lebensdauer_h REAL DEFAULT 5000,    -- Stunden bis abgeschrieben
  leistung_w REAL DEFAULT 100,        -- mittlere Leistungsaufnahme
  stunden_vorher REAL DEFAULT 0,      -- Betriebsstunden ohne Aufträge
  wartung_eur_h REAL DEFAULT 0,       -- sonstige Pauschale €/h
  farbe TEXT,
  notizen TEXT,
  ha_liste TEXT,                      -- Home-Assistant-Druckprotokoll, z. B. todo.p1s_druckprotokoll
  aktiv INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS wear_parts(
  id INTEGER PRIMARY KEY,
  machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  preis REAL DEFAULT 0,
  lebensdauer_h REAL DEFAULT 1000,
  gewechselt_bei_h REAL DEFAULT 0,    -- Betriebsstunde des letzten Wechsels
  notizen TEXT
);

CREATE TABLE IF NOT EXISTS materials(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  typ TEXT DEFAULT 'filament',        -- filament | platte | sonstiges
  hersteller TEXT, farbe TEXT,
  einheit TEXT DEFAULT 'kg',          -- kg (Eingabe in g) | Stück | m² | m
  preis REAL DEFAULT 0,               -- € pro Einheit
  bestand REAL,
  notizen TEXT,
  aktiv INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY,
  nr TEXT,
  customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
  titel TEXT NOT NULL,
  beschreibung TEXT,
  status TEXT DEFAULT 'anfrage',
  eingang TEXT, termin TEXT,
  ordner TEXT,                         -- Pfad relativ zur Auftrags-Freigabe
  aufschlag_pct REAL,                  -- leer = Standard aus Einstellungen
  vertrieb TEXT,                       -- z. B. Kreativabend, Online, Markt
  uebergabe TEXT,                      -- abholung | versand
  versand REAL,                        -- Versandkosten (an Kunden)
  zahlungsart TEXT,                    -- Bar | Überweisung | PayPal | Sonstiges
  anzahlung REAL,
  zahlungsstatus TEXT DEFAULT 'offen', -- offen | angezahlt | bezahlt
  zahlungsdatum TEXT,
  wuensche TEXT,                       -- besondere Wünsche / Hinweise (für den Kunden sichtbar)
  notizen TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_jobs(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  machine_id INTEGER REFERENCES machines(id) ON DELETE SET NULL,
  material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL,
  bezeichnung TEXT,
  datum TEXT,
  dauer_h REAL DEFAULT 0,
  menge REAL DEFAULT 0,                -- g bei Einheit kg, sonst Einheit
  stueck REAL,
  kwh REAL,                            -- gemessen (Home Assistant), sonst geschätzt
  notizen TEXT
);

CREATE TABLE IF NOT EXISTS order_times(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
  datum TEXT,
  stunden REAL DEFAULT 0,
  taetigkeit TEXT
);

CREATE TABLE IF NOT EXISTS order_costs(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  bezeichnung TEXT,
  datum TEXT,
  betrag REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sort INTEGER DEFAULT 0,
  bezeichnung TEXT,
  beschreibung TEXT,
  farbe_material TEXT,                 -- Farbe / Material / Größe
  personalisierung TEXT,               -- genauer Text
  menge REAL DEFAULT 1,
  einheit TEXT DEFAULT 'Stk',
  einzelpreis REAL DEFAULT 0          -- netto
);

CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY,
  order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
  customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
  datei TEXT NOT NULL,
  original TEXT,
  titel TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  typ TEXT NOT NULL,                   -- rechnung | angebot
  nr TEXT NOT NULL,
  order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
  customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
  datum TEXT, leistungsdatum TEXT, faellig TEXT,
  kunde_json TEXT, positionen_json TEXT,
  einleitung TEXT, schluss TEXT,
  netto REAL, ust_satz REAL, ust REAL, brutto REAL,
  kleinunternehmer INTEGER DEFAULT 0,
  anzahlung REAL,
  status TEXT DEFAULT 'offen',        -- offen | bezahlt | storniert | angenommen | abgelehnt
  bezahlt_am TEXT,
  pdf TEXT,
  notizen TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prints(
  id INTEGER PRIMARY KEY,
  ha_uid TEXT UNIQUE,
  ha_liste TEXT,
  ha_summary TEXT,
  ha_status TEXT,
  machine_id INTEGER REFERENCES machines(id) ON DELETE SET NULL,
  name TEXT,
  datum TEXT, uhrzeit TEXT,
  dauer_h REAL, kwh REAL, gramm REAL,
  erfolg INTEGER DEFAULT 1,
  art TEXT DEFAULT 'offen',            -- offen | privat | gewerbe
  order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
  job_id INTEGER REFERENCES order_jobs(id) ON DELETE SET NULL,
  sync_pending INTEGER DEFAULT 0,      -- Einstufung muss noch nach HA
  notizen TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_order ON order_jobs(order_id);
CREATE INDEX IF NOT EXISTS idx_times_order ON order_times(order_id);
CREATE INDEX IF NOT EXISTS idx_costs_order ON order_costs(order_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_images_order ON images(order_id);
CREATE INDEX IF NOT EXISTS idx_docs_order ON documents(order_id);
"""


def _connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def conn():
    c = _connect()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def one(cur):
    r = cur.fetchone()
    return dict(r) if r else None


def init():
    for d in (DATA_DIR, BILDER_DIR, DOKU_DIR, BACKUP_DIR, VORLAGE_DIR):
        os.makedirs(d, exist_ok=True)
    first = not os.path.exists(DB_PATH)
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        migrate(c)
    return first


# Spalten, die in späteren Versionen dazukommen, werden bei Updates automatisch ergänzt.
COLUMNS = {
    "orders": {"vertrieb": "TEXT", "uebergabe": "TEXT", "versand": "REAL", "zahlungsart": "TEXT",
               "anzahlung": "REAL", "zahlungsstatus": "TEXT DEFAULT 'offen'", "zahlungsdatum": "TEXT",
               "wuensche": "TEXT"},
    "order_items": {"farbe_material": "TEXT", "personalisierung": "TEXT"},
    "documents": {"anzahlung": "REAL"},
    "machines": {"ha_liste": "TEXT"},
    "order_jobs": {"kwh": "REAL"},
}


def migrate(c):
    for table, cols in COLUMNS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def next_nr(c, table, prefix, yearly=True, digits=3, typ=None, year=None):
    """Fortlaufende Nummer: PREFIX2026-001 (jährlich) oder PREFIX0001."""
    base = f"{prefix}{year or date.today().year}-" if yearly else prefix
    sql, args = f"SELECT nr FROM {table} WHERE nr LIKE ?", [base + "%"]
    if typ:
        sql += " AND typ=?"
        args.append(typ)
    n = 0
    for r in c.execute(sql, args):
        tail = (r["nr"] or "")[len(base):]
        if tail.isdigit():
            n = max(n, int(tail))
    return f"{base}{n + 1:0{digits}d}"
