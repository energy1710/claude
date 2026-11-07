"""Home Assistant: Druckprotokolle (To-do-Listen) abholen und Privat/Gewerbe zurückmelden.

HA schreibt nach jedem Druck einen Eintrag in todo.<drucker>_druckprotokoll:
  Titel:        "04.11.26 14:32 · Name"   (Uhrzeit optional, Präfix 💼/🏠 = schon eingestuft)
  Beschreibung: "Dauer 2:15 h · Strom 0,221 kWh (0,07 €) · Filament 84 g (1,09 €) · Gesamt 1,16 €"
Die Werkstatt holt die Einträge per REST-API ab (langlebiges Zugangstoken) und stuft sie ein.
Eingestufte Einträge werden in HA mit Präfix versehen und abgehakt.
"""
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import db, settings

log = logging.getLogger("werkstatt.ha")
_lock = threading.Lock()

PREFIX = {"gewerbe": "💼", "privat": "🏠"}
PREFIX_ART = {v: k for k, v in PREFIX.items()}

RE_SUMMARY = re.compile(r"^\s*(💼|🏠)?\s*(\d{2})\.(\d{2})\.(\d{2,4})(?:\s+(\d{1,2}:\d{2}))?\s*·\s*(.*?)\s*$")
RE_DAUER = re.compile(r"Dauer\s+(\d+):(\d{2})")
RE_KWH = re.compile(r"Strom\s+([\d.,]+)\s*kWh")
RE_GRAMM = re.compile(r"Filament\s+([\d.,]+)\s*g")


class HAError(Exception):
    pass


def _num(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_item(item):
    """Liest einen To-do-Eintrag aus. Gibt None zurück, wenn er nicht nach Druckprotokoll aussieht."""
    m = RE_SUMMARY.match(item.get("summary") or "")
    if not m:
        return None
    pre, d, mo, y, hhmm, name = m.groups()
    year = int(y) + 2000 if len(y) == 2 else int(y)
    erfolg = 1
    if name.endswith("❌"):
        erfolg = 0
        name = name[:-1].strip()
    desc = item.get("description") or ""
    md = RE_DAUER.search(desc)
    mk = RE_KWH.search(desc)
    mg = RE_GRAMM.search(desc)
    return {
        "ha_uid": item.get("uid"),
        "ha_summary": item.get("summary"),
        "ha_status": item.get("status"),
        "art_ha": PREFIX_ART.get(pre),
        "datum": f"{year:04d}-{int(mo):02d}-{int(d):02d}",
        "uhrzeit": hhmm,
        "name": name,
        "erfolg": erfolg,
        "dauer_h": round(int(md.group(1)) + int(md.group(2)) / 60, 4) if md else None,
        "kwh": _num(mk.group(1)) if mk else None,
        "gramm": _num(mg.group(1)) if mg else None,
    }


def strip_prefix(summary):
    s = (summary or "").strip()
    for p in PREFIX_ART:
        if s.startswith(p):
            return s[len(p):].strip()
    return s


# ---------- REST ----------

def _cfg():
    url = (settings.get("ha_url") or "").strip().rstrip("/")
    token = settings.get("ha_token") or ""
    if not url or not token:
        raise HAError("Home Assistant ist nicht eingerichtet (Adresse und Zugangstoken fehlen).")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    return url, token


def _post(path, body, timeout=15):
    url, token = _cfg()
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise HAError("Zugangstoken wird von Home Assistant abgelehnt") from e
        if e.code == 400:
            raise HAError(f"Home Assistant meldet einen Fehler (400) – gibt es die Liste? {e.read()[:200]!r}") from e
        raise HAError(f"Home Assistant antwortet mit Fehler {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HAError(f"Home Assistant nicht erreichbar ({getattr(e, 'reason', e)})") from e


def get_items(liste):
    r = _post("/api/services/todo/get_items?return_response", {"entity_id": liste})
    resp = (r or {}).get("service_response") or {}
    return (resp.get(liste) or {}).get("items") or []


def update_item(liste, uid, rename=None, status=None):
    body = {"entity_id": liste, "item": uid}
    if rename is not None:
        body["rename"] = rename
    if status is not None:
        body["status"] = status
    _post("/api/services/todo/update_item", body)


def listen():
    return [x.strip() for x in (settings.get("ha_listen") or "").split(",") if x.strip().startswith("todo.")]


# ---------- Abgleich ----------

def _machine_for(c, liste):
    r = c.execute("SELECT id FROM machines WHERE ha_liste=?", (liste,)).fetchone()
    if r:
        return r["id"]
    token = liste.split(".", 1)[-1].split("_")[0].lower()
    for m in c.execute("SELECT id, name FROM machines"):
        if re.search(r"\b" + re.escape(token) + r"\b", (m["name"] or "").lower()):
            return m["id"]
    return None


def push_art(print_row):
    """Einstufung nach HA melden: Präfix in den Titel und abhaken."""
    p = print_row
    base = strip_prefix(p["ha_summary"])
    pre = PREFIX.get(p["art"])
    new = f"{pre} {base}" if pre else base
    update_item(p["ha_liste"], p["ha_uid"], rename=new, status="completed" if pre else None)
    with db.conn() as c:
        c.execute("UPDATE prints SET ha_summary=?, ha_status=?, sync_pending=0 WHERE id=?",
                  (new, "completed" if pre else p["ha_status"], p["id"]))


def sync():
    """Holt alle Einträge ab, legt neue Drucke an und meldet offene Einstufungen zurück."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "text": "Abruf läuft bereits"}
    try:
        neu = aktualisiert = gemeldet = 0
        fehler = []
        ab = settings.get("ha_import_ab") or ""
        for liste in listen():
            try:
                items = get_items(liste)
            except HAError as e:
                fehler.append(f"{liste}: {e}")
                continue
            with db.conn() as c:
                mid = _machine_for(c, liste)
                for it in items:
                    p = parse_item(it)
                    if not p or not p["ha_uid"]:
                        continue
                    old = db.one(c.execute("SELECT * FROM prints WHERE ha_uid=?", (p["ha_uid"],)))
                    if not old:
                        if ab and p["datum"] < ab:
                            continue
                        notiz = None
                        if (p["name"] or "").lower().startswith("auto_cali"):
                            # Kalibrierlauf des Druckers: kein Auftrag, Filamentgewicht stammt vom letzten Druck
                            p["art_ha"] = p["art_ha"] or "privat"
                            p["gramm"] = 0
                            notiz = "Kalibrierung"
                        c.execute(
                            "INSERT INTO prints(ha_uid, ha_liste, ha_summary, ha_status, machine_id, name, datum, uhrzeit,"
                            " dauer_h, kwh, gramm, erfolg, art, notizen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (p["ha_uid"], liste, p["ha_summary"], p["ha_status"], mid, p["name"], p["datum"],
                             p["uhrzeit"], p["dauer_h"], p["kwh"], p["gramm"], p["erfolg"], p["art_ha"] or "offen",
                             notiz))
                        neu += 1
                        continue
                    upd = {"ha_summary": p["ha_summary"], "ha_status": p["ha_status"]}
                    # In HA (Push-Knopf) eingestuft, hier noch offen → übernehmen
                    if p["art_ha"] and old["art"] == "offen" and not old["sync_pending"]:
                        upd["art"] = p["art_ha"]
                        aktualisiert += 1
                    if old["machine_id"] is None and mid:
                        upd["machine_id"] = mid
                    c.execute(f"UPDATE prints SET {', '.join(k + '=?' for k in upd)} WHERE id=?",
                              [*upd.values(), old["id"]])
        # Einstufungen aus der Werkstatt nach HA melden
        with db.conn() as c:
            pending = db.rows(c.execute("SELECT * FROM prints WHERE sync_pending=1"))
        for p in pending:
            try:
                push_art(p)
                gemeldet += 1
            except HAError as e:
                fehler.append(f"Rückmeldung {p['name']}: {e}")
                break
        teile = [f"{neu} neu"]
        if aktualisiert:
            teile.append(f"{aktualisiert} in HA eingestuft")
        if gemeldet:
            teile.append(f"{gemeldet} an HA gemeldet")
        text = ", ".join(teile)
        ok = not fehler
        if fehler:
            text += " – Fehler: " + "; ".join(fehler[:3])
        settings.set_many({"ha_letzt": datetime.now().strftime("%Y-%m-%d %H:%M"),
                           "ha_letzt_status": ("ok: " if ok else "fehler: ") + text})
        return {"ok": ok, "text": text, "neu": neu}
    finally:
        _lock.release()


def set_art(print_id, art, push=True):
    if art not in ("offen", "privat", "gewerbe"):
        raise ValueError("Art muss offen, privat oder gewerbe sein")
    with db.conn() as c:
        p = db.one(c.execute("SELECT * FROM prints WHERE id=?", (print_id,)))
        if not p:
            raise ValueError("Druck nicht gefunden")
        c.execute("UPDATE prints SET art=?, sync_pending=? WHERE id=?",
                  (art, 1 if p["ha_uid"] else 0, print_id))
        p = db.one(c.execute("SELECT * FROM prints WHERE id=?", (print_id,)))
    if p["ha_uid"] and push:
        try:
            push_art(p)
        except HAError as e:
            return str(e)  # bleibt vorgemerkt, wird beim nächsten Abruf gemeldet
    return None if push or not p["ha_uid"] else "vorgemerkt"


def _loop():
    time.sleep(20)
    while True:
        try:
            if settings.flag("ha_aktiv") and settings.get("ha_url") and settings.get("ha_token"):
                sync()
        except Exception:  # pragma: no cover
            log.exception("HA-Abruf fehlgeschlagen")
        time.sleep(max(1.0, settings.num("ha_intervall_min", 3)) * 60)


def start_scheduler():
    threading.Thread(target=_loop, name="ha-sync", daemon=True).start()
