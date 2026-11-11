"""Rechnungsablage: jede Rechnung zusätzlich als PDF nach <Rechnungen>/<Jahr>/ auf dem Netzlaufwerk.

Dateiname „RE-2026-005 Anna Huber.pdf“, stornierte Rechnungen bekommen „ (storniert)“ angehängt.
documents.ablage merkt sich den zuletzt geschriebenen Pfad: Ändert sich der Soll-Pfad (Storno, Kunde, Datum),
wird die alte Datei ersetzt. Klappt das Schreiben nicht (NAS aus), holt der Hintergrund-Abgleich es nach.
"""
import json
import logging
import os
import threading

from . import archiv, db, settings, storage

log = logging.getLogger("werkstatt.ablage")
_lock = threading.Lock()


def enabled():
    return settings.flag("rechnungen_ablage") and archiv.configured()


def _kunde(d):
    k = d.get("kunde")
    if isinstance(k, str):
        try:
            k = json.loads(k or "{}")
        except ValueError:
            k = {}
    k = k or {}
    return k.get("firma") or " ".join(x for x in (k.get("vorname"), k.get("nachname")) if x) or "Direktverkauf"


def soll(d):
    """Relativer Ablagepfad einer Rechnung – None für Angebote."""
    if d.get("typ") != "rechnung":
        return None
    jahr = (d.get("datum") or "")[:4] or "ohne Datum"
    name = storage.safe_name(f"{d['nr']} {_kunde(d)}", 90)
    if d.get("status") == "storniert":
        name += " (storniert)"
    return f"{jahr}/{name}.pdf"


def sync_doc(did, force=False):
    """Legt die PDF einer Rechnung in der Ablage ab. force = auch bei gleichem Pfad neu schreiben (PDF geändert)."""
    if not enabled():
        return None
    with _lock:
        with db.conn() as c:
            d = db.one(c.execute("SELECT id, typ, nr, datum, status, kunde_json AS kunde, pdf, ablage "
                                 "FROM documents WHERE id=?", (did,)))
        if not d:
            return None
        want, cur = soll(d), d.get("ablage")
        if want == cur and not force:
            return None
        local = os.path.join(db.DOKU_DIR, d["pdf"] or "")
        if want and (not d["pdf"] or not os.path.exists(local)):
            return None  # PDF wird bei Bedarf erzeugt und dann abgelegt
        try:
            fs = storage.FS("rechnungen")
            if fs.kind == "lokal" and not os.path.isdir(fs.base):
                raise storage.StorageError("Netzlaufwerk nicht erreichbar")  # nicht eingehängt: nichts lokal anlegen
            fs.makedirs()
            if want:
                fs.copy_from_local(local, want)
            if cur and cur != want:
                try:
                    fs.remove(cur)
                except storage.StorageError:
                    pass  # alte Datei schon weg
        except storage.StorageError as e:
            return f"Rechnung {d['nr']} nicht in der Rechnungsablage gespeichert: {e} – wird später erneut versucht."
        with db.conn() as c:
            c.execute("UPDATE documents SET ablage=? WHERE id=?", (want, did))
        log.info("Rechnung %s abgelegt: %s", d["nr"], want)
    return None


def remove(path):
    """Datei einer gelöschten Rechnung aus der Ablage entfernen (ohne Fehler, falls nicht möglich)."""
    if not path or not archiv.configured():
        return
    try:
        storage.FS("rechnungen").remove(path)
    except storage.StorageError:
        pass


def sync_all():
    if not enabled():
        return {"ok": True, "abgelegt": 0, "text": "Rechnungsablage ist ausgeschaltet."}
    with db.conn() as c:
        docs = db.rows(c.execute("SELECT id, typ, nr, datum, status, kunde_json AS kunde, ablage FROM documents "
                                 "WHERE typ='rechnung' ORDER BY datum, id"))
    todo = [d["id"] for d in docs if soll(d) != d.get("ablage")]
    n, fehler = 0, []
    for did in todo:
        w = sync_doc(did)
        if w:
            fehler.append(w)
            if "nicht erreichbar" in w or "nicht eingerichtet" in w:
                break
        else:
            n += 1
    if not todo:
        return {"ok": True, "abgelegt": 0, "text": "Alle Rechnungen sind schon in der Ablage."}
    return {"ok": not fehler, "abgelegt": n, "fehler": fehler[:5],
            "text": f"{n} Rechnung(en) abgelegt" + (f", {len(fehler)} Fehler" if fehler else "")}
