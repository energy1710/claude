"""Sicherung: Datenbank (+ Bilder, Dokumente, Logo) als ZIP – lokal und auf das Netzlaufwerk."""
import logging
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime

from . import db, settings, storage

log = logging.getLogger("werkstatt.backup")
_run_lock = threading.Lock()
LOCAL_KEEP = 7


def make_zip(with_images=True):
    """Erzeugt ein ZIP im Backup-Ordner und gibt den Pfad zurück."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    zpath = os.path.join(db.BACKUP_DIR, f"werkstatt-{stamp}.zip")
    fd, tmpdb = tempfile.mkstemp(suffix=".db", dir=db.BACKUP_DIR)
    os.close(fd)
    try:
        src = sqlite3.connect(db.DB_PATH)
        dst = sqlite3.connect(tmpdb)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmpdb, "werkstatt.db")
            dirs = [("dokumente", db.DOKU_DIR), ("vorlage", db.VORLAGE_DIR)]
            if with_images:
                dirs.append(("bilder", db.BILDER_DIR))
            for arc, d in dirs:
                for root, _, files in os.walk(d):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, arc + "/" + os.path.relpath(full, d).replace(os.sep, "/"))
    finally:
        try:
            os.remove(tmpdb)
        except OSError:
            pass
    # lokal nur die letzten Sicherungen behalten
    local = sorted(f for f in os.listdir(db.BACKUP_DIR) if f.startswith("werkstatt-") and f.endswith(".zip"))
    for old in local[:-LOCAL_KEEP]:
        try:
            os.remove(os.path.join(db.BACKUP_DIR, old))
        except OSError:
            pass
    return zpath


def run(manual=False):
    """Sicherung erstellen und auf das Netzlaufwerk kopieren. Liefert (ok, text)."""
    if not _run_lock.acquire(blocking=False):
        return False, "Es läuft bereits eine Sicherung."
    try:
        zpath = make_zip(settings.flag("backup_mit_bildern"))
        name = os.path.basename(zpath)
        size_mb = os.path.getsize(zpath) / 1024 / 1024
        try:
            fs = storage.FS("backup")
            fs.makedirs()
            fs.copy_from_local(zpath, name)
            keep = int(settings.num("backup_behalten", 30))
            remote = sorted(e["name"] for e in fs.listdir()
                            if not e["dir"] and e["name"].startswith("werkstatt-") and e["name"].endswith(".zip"))
            if keep > 0:
                for old in remote[:-keep]:
                    try:
                        fs.remove(old)
                    except storage.StorageError:
                        pass
            ok, text = True, f"Gesichert nach {fs.unc(name)} ({size_mb:.1f} MB)"
        except storage.StorageError as e:
            ok, text = False, f"Nur lokal gesichert – Netzlaufwerk: {e}"
        settings.set_many({"backup_letzt": datetime.now().strftime("%Y-%m-%d %H:%M"),
                           "backup_letzt_status": ("ok: " if ok else "fehler: ") + text,
                           "backup_letzt_datei": name})
        log.info(text)
        return ok, text
    except Exception as e:  # pragma: no cover
        log.exception("Backup fehlgeschlagen")
        settings.set_many({"backup_letzt": datetime.now().strftime("%Y-%m-%d %H:%M"),
                           "backup_letzt_status": f"fehler: {e}"})
        return False, str(e)
    finally:
        _run_lock.release()


def list_local():
    out = []
    for f in sorted(os.listdir(db.BACKUP_DIR), reverse=True):
        if f.startswith("werkstatt-") and f.endswith(".zip"):
            p = os.path.join(db.BACKUP_DIR, f)
            out.append({"name": f, "size": os.path.getsize(p)})
    return out


def restore(zip_or_db_path):
    """Spielt eine Sicherung ein. Vorher wird der aktuelle Stand gesichert."""
    make_zip(True)
    if zipfile.is_zipfile(zip_or_db_path):
        with zipfile.ZipFile(zip_or_db_path) as z:
            names = z.namelist()
            if "werkstatt.db" not in names:
                raise ValueError("Im ZIP fehlt werkstatt.db")
            tmp = os.path.join(db.DATA_DIR, "restore.tmp.db")
            with z.open("werkstatt.db") as src, open(tmp, "wb") as dst:
                dst.write(src.read())
            _check_db(tmp)
            for arc, d in (("bilder/", db.BILDER_DIR), ("dokumente/", db.DOKU_DIR), ("vorlage/", db.VORLAGE_DIR)):
                for n in names:
                    if n.startswith(arc) and not n.endswith("/"):
                        rel = storage.clean_rel(n[len(arc):])
                        target = os.path.join(d, *rel)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with z.open(n) as s, open(target, "wb") as t:
                            t.write(s.read())
    else:
        tmp = zip_or_db_path
        _check_db(tmp)
    src = sqlite3.connect(tmp)
    dst = sqlite3.connect(db.DB_PATH)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    if tmp.endswith("restore.tmp.db"):
        os.remove(tmp)


def _check_db(path):
    try:
        c = sqlite3.connect(path)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        c.close()
    except sqlite3.DatabaseError as e:
        raise ValueError("Datei ist keine gültige Datenbank") from e
    if not {"orders", "customers", "settings"} <= tables:
        raise ValueError("Das ist keine Werkstatt-Sicherung")


# ---------- Zeitplan ----------

def _loop():
    last_day = None
    while True:
        try:
            if settings.flag("backup_aktiv"):
                now = datetime.now()
                hhmm = settings.get("backup_uhrzeit") or "02:30"
                today = now.strftime("%Y-%m-%d")
                already = (settings.get("backup_letzt") or "").startswith(today) and \
                    (settings.get("backup_letzt_status") or "").startswith("ok")
                if now.strftime("%H:%M") >= hhmm and last_day != today and not already:
                    last_day = today
                    run()
        except Exception:  # pragma: no cover
            log.exception("Fehler im Backup-Zeitplan")
        time.sleep(60)


def start_scheduler():
    t = threading.Thread(target=_loop, name="backup", daemon=True)
    t.start()
