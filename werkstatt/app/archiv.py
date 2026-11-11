"""Auftragsordner abschließen: bezahlte Aufträge nach <Abgeschlossen>/<Jahr>/ verschieben – und zurück.

Regel: Ordner gehört ins Archiv, wenn der Auftrag „bezahlt“ ist – außer er wurde von Hand festgelegt
(orders.ordner_fix: 1 = immer abgeschlossen, 0 = immer bei den offenen; wird bei Statuswechsel zurückgesetzt).
Klappt das Verschieben nicht (NAS aus, Datei geöffnet), versucht es der Hintergrund-Abgleich später erneut.
"""
import logging
import threading
import time
from datetime import date

from . import db, settings, storage

log = logging.getLogger("werkstatt.archiv")
_lock = threading.Lock()


def configured():
    if settings.get("lokal_auftraege").strip():
        return True
    return bool(settings.get("smb_host").strip() and settings.get("smb_auftraege_share").strip())


def enabled():
    return settings.flag("ordner_abschluss") and configured()


def root_parts():
    return storage.clean_rel(settings.get("ordner_abschluss_name") or "Abgeschlossen") or ["Abgeschlossen"]


def is_archived(rel):
    parts, root = storage.clean_rel(rel), root_parts()
    return len(parts) > len(root) and [p.lower() for p in parts[:len(root)]] == [p.lower() for p in root]


def want_archived(o):
    if o.get("ordner_fix") is not None:
        return bool(o["ordner_fix"])
    return o.get("status") == "bezahlt"


def _jahr(o):
    return (o.get("eingang") or o.get("created_at") or "")[:4] or str(date.today().year)


def _free(fs, rel):
    if not fs.exists(rel):
        return rel
    i = 2
    while fs.exists(f"{rel} ({i})"):
        i += 1
    return f"{rel} ({i})"


def _move(c, o, archive):
    """Verschiebt den Ordner eines Auftrags. Gibt den neuen relativen Pfad zurück."""
    fs = storage.FS("auftraege")
    if not fs.exists(""):
        raise storage.StorageError("Netzlaufwerk nicht erreichbar")
    src = "/".join(storage.clean_rel(o["ordner"]))
    if archive:
        dst = "/".join(root_parts() + [_jahr(o), storage.clean_rel(src)[-1]])
    else:
        dst = o.get("ordner_offen")
        if not dst:
            k = db.one(c.execute("SELECT * FROM customers WHERE id=?", (o["customer_id"],))) if o["customer_id"] else None
            dst = storage.order_folder_name(o, k)
        dst = "/".join(storage.clean_rel(dst))
    if dst == src:
        return src
    if fs.exists(src):
        parent = "/".join(storage.clean_rel(dst)[:-1])
        if parent:
            fs.makedirs(parent)
        dst = _free(fs, dst)
        try:
            fs.rename(src, dst)
        except storage.StorageError as e:
            raise storage.StorageError(f"{e} – ist eine Datei im Ordner gerade geöffnet?") from e
    # Ordner gibt es (noch) nicht: nur den Pfad umstellen, damit er später am richtigen Ort entsteht
    c.execute("UPDATE orders SET ordner=?, ordner_offen=? WHERE id=?", (dst, src if archive else None, o["id"]))
    log.info("Auftrag %s: Ordner %s → %s", o.get("nr"), src, dst)
    return dst


def sync_order(oid, force=False):
    """Bringt den Ordner eines Auftrags an den richtigen Ort. Gibt None oder eine Warnung zurück."""
    if not (enabled() or force) or not configured():
        return None
    with _lock, db.conn() as c:
        o = db.one(c.execute("SELECT * FROM orders WHERE id=?", (oid,)))
        if not o or not o["ordner"]:
            return None
        want = want_archived(o)
        if want == is_archived(o["ordner"]):
            return None
        try:
            _move(c, o, want)
        except storage.StorageError as e:
            return (f"Auftragsordner konnte nicht nach „{'/'.join(root_parts())}“ verschoben werden: {e}"
                    if want else f"Auftragsordner konnte nicht zurückgeholt werden: {e}") + \
                " – wird später automatisch erneut versucht."
    return None


def sync_order_soon(oid, wait=6.0):
    """Wie sync_order, wartet aber höchstens `wait` Sekunden (NAS aus → läuft im Hintergrund weiter)."""
    if not enabled():
        return None
    box = {}
    t = threading.Thread(target=lambda: box.update(w=sync_order(oid)), name="archiv-order", daemon=True)
    t.start()
    t.join(wait)
    return box.get("w")


def sync_all():
    """Alle Aufträge abgleichen (Hintergrund + Knopf in den Einstellungen)."""
    if not enabled():
        return {"ok": True, "verschoben": 0, "text": "Verschieben abgeschlossener Aufträge ist ausgeschaltet."}
    with db.conn() as c:
        todo = [o["id"] for o in db.rows(c.execute("SELECT * FROM orders WHERE ordner IS NOT NULL AND ordner!=''"))
                if want_archived(o) != is_archived(o["ordner"])]
    n, fehler = 0, []
    for oid in todo:
        w = sync_order(oid)
        if w:
            fehler.append(w)
            if "nicht erreichbar" in w:
                break
        else:
            n += 1
    text = f"{n} Auftragsordner verschoben" + (f", {len(fehler)} Fehler" if fehler else "")
    if not todo:
        text = "Alle Auftragsordner sind schon am richtigen Ort."
    return {"ok": not fehler, "verschoben": n, "text": text, "fehler": fehler[:5]}


def _loop():
    time.sleep(60)
    from . import ablage  # erst hier, sonst zirkulärer Import
    while True:
        try:
            sync_all()
        except Exception:  # pragma: no cover
            log.exception("Abgleich der Auftragsordner fehlgeschlagen")
        try:
            ablage.sync_all()
        except Exception:  # pragma: no cover
            log.exception("Abgleich der Rechnungsablage fehlgeschlagen")
        time.sleep(15 * 60)


def start_scheduler():
    threading.Thread(target=_loop, name="archiv", daemon=True).start()
