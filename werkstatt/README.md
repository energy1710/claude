# Werkstatt (TK Dekowerkstatt)

Auftragsverwaltung für 3D-Druck und Laser: Kunden, Aufträge, Kalkulation, Rechnungen, Produkte, Maschinen, Material.
Läuft als eigener Container (LXC) auf Proxmox.

## Installieren / Updaten

1. `dist/werkstatt-installer.sh` auf den Proxmox-Server kopieren.
2. In der Proxmox-Shell: `bash werkstatt-installer.sh`
3. Gibt es schon eine Installation, „update“ wählen. Die Daten bleiben erhalten, die Datenbank wird vorher
   im Container unter `/var/lib/werkstatt/` gesichert.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `app/` | Programm (FastAPI-Backend + Weboberfläche in `app/static/`) |
| `requirements.txt` | Python-Pakete |
| `installer-head.sh` | Installer-Skript (ohne Programm) |
| `build.sh` | baut `dist/werkstatt-installer.sh` = Installer + gepacktes Programm |

## Neue Version bauen

1. Code ändern.
2. Version erhöhen in `app/main.py` (`VERSION`) **und** `installer-head.sh` (`APP_VERSION`).
3. `./build.sh` ausführen.
4. Neue Datenbank-Spalten in `app/db.py` unter `COLUMNS` eintragen, neue Tabellen in `SCHEMA`
   (`CREATE TABLE IF NOT EXISTS`). Sie werden beim Update automatisch angelegt.

## Versionen

### 1.3.0
- **Schnellrechner mit mehreren Zeilen**: beliebig viele Drucke/Laser (Maschine, Zeit, Material, Menge), Arbeitszeiten
  (Person, Tätigkeit, Zeit) und Zubehör (Bezeichnung, Betrag), jeweils mit + / −. „Als neuen Auftrag anlegen“
  übernimmt alle Zeilen einzeln in den Auftrag.
- **Drucke: Einstufung „🗑️ Müll“** zusätzlich zu Privat/Gewerbe. Müll wird protokolliert (eigener Filter, Kachel
  „Müll diesen Monat“ mit Zeit, Gramm und geschätzten Kosten) und kann optional einem Auftrag zugeordnet werden – dann
  zählen Druckzeit und Filament als Kosten des Auftrags. In Home Assistant bekommt der Eintrag das Präfix 🗑️.

### 1.2.0
- **Produktkatalog** (neuer Reiter „Produkte“): fertige Artikel mit Preis, Kategorie, Herstellkosten und Lagerbestand,
  Lagerzugang buchen, Lagerwert-Übersicht.
- **Rechnungen ohne Auftrag**: im Reiter „Rechnungen“ über „+ Neue Rechnung“ (oder 🧾 beim Produkt).
  Kunde optional (Barverkauf), Option „sofort bezahlt“ mit eigenem Schlusstext (einstellbar unter Einstellungen).
- Produkte lassen sich in jede Rechnung/jedes Angebot übernehmen („+ aus Produktkatalog“). Rechnungen buchen den
  Lagerbestand automatisch ab; Storno, Löschen und Änderungen buchen korrekt zurück. Warnung, wenn zu wenig auf Lager.
- **Schnellrechner & Druck/Laser-Erfassung**: Material passend zur Maschine – 3D-Drucker zeigen nur Filament,
  Laser nur Platten und sonstiges Lasermaterial.

### 1.1.0
- Ausgangsstand.
