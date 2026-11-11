import csv
import io
import json
import logging
import mimetypes
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import ablage, archiv, backup, bestellung, calc, db, ha, images, pdf, seed, settings, storage

VERSION = "1.6.0"
STATIC = os.path.join(os.path.dirname(__file__), "static")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for _noisy in ("smbprotocol", "smbclient", "spnego", "fontTools", "fpdf"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app):
    first = db.init()
    settings.init()
    if first:
        with db.conn() as c:
            seed.run(c)
    if os.environ.get("WERKSTATT_NO_BACKUP") != "1":
        backup.start_scheduler()
        ha.start_scheduler()
        archiv.start_scheduler()
    yield


app = FastAPI(title="Werkstatt", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

OPEN_PATHS = {"/login", "/api/login", "/static/style.css", "/favicon.ico"}


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if settings.get("app_password") and path not in OPEN_PATHS:
        if request.cookies.get("ws_session") != settings.session_token():
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Anmeldung erforderlich"}, status_code=401)
            return RedirectResponse("/login")
    resp = await call_next(request)
    if path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def index():
    stamp = int(max(os.path.getmtime(os.path.join(STATIC, f)) for f in ("app.js", "style.css")))
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = re.sub(r"\?v=\d+", f"?v={stamp}", fh.read())
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1a1712"/>'
           '<path d="M14 46h36M20 46V24l12-8 12 8v22" stroke="#e8590c" stroke-width="5" fill="none" stroke-linejoin="round"/>'
           '<rect x="28" y="32" width="8" height="14" fill="#ffb02e"/></svg>')


@app.get("/favicon.ico")
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


# ---------- Login ----------

LOGIN_HTML = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Werkstatt – Anmelden</title>
<link rel="icon" href="/favicon.ico"><link rel="stylesheet" href="/static/style.css"></head><body>
<div class="login"><div class="brand"><span class="logo-dot"></span> Werkstatt</div>
<form id="f"><input type="password" id="pw" placeholder="Passwort" autofocus>
<button>Anmelden</button><p id="err" class="err"></p></form></div>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: document.getElementById('pw').value})});
  if (r.ok) location.href = '/'; else document.getElementById('err').textContent = 'Falsches Passwort';
};
</script></body></html>"""


@app.get("/login")
def login_page():
    return HTMLResponse(LOGIN_HTML)


class LoginIn(BaseModel):
    password: str


def _session_cookie(resp, request):
    resp.set_cookie("ws_session", settings.session_token(), max_age=60 * 60 * 24 * 365, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https")


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    if not settings.check_password(body.password):
        raise HTTPException(401, "Falsches Passwort")
    resp = JSONResponse({"ok": True})
    _session_cookie(resp, request)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("ws_session")
    return resp


# ---------- Tabellen ----------

TABLES = {
    "customers": ["firma", "anrede", "vorname", "nachname", "strasse", "plz", "ort", "land", "email", "telefon",
                  "uid", "notizen"],
    "persons": ["name", "stundensatz", "verrechnungssatz", "farbe", "aktiv"],
    "machines": ["name", "typ", "hersteller", "modell", "anschaffung_preis", "anschaffung_datum", "lebensdauer_h",
                 "leistung_w", "stunden_vorher", "wartung_eur_h", "farbe", "notizen", "aktiv", "ha_liste"],
    "wear_parts": ["machine_id", "name", "preis", "lebensdauer_h", "gewechselt_bei_h", "notizen"],
    "materials": ["name", "typ", "hersteller", "farbe", "einheit", "preis", "bestand", "notizen", "aktiv"],
    "products": ["artikelnr", "name", "kategorie", "beschreibung", "farbe_material", "einheit", "preis",
                 "herstellkosten", "bestand", "notizen", "aktiv", "kalkulation"],
    "orders": ["customer_id", "titel", "beschreibung", "status", "eingang", "termin", "ordner", "aufschlag_pct",
               "vertrieb", "uebergabe", "versand", "zahlungsart", "anzahlung", "zahlungsstatus", "zahlungsdatum",
               "wuensche", "notizen"],
    "order_jobs": ["order_id", "machine_id", "material_id", "bezeichnung", "datum", "dauer_h", "menge", "stueck",
                   "kwh", "notizen"],
    "order_times": ["order_id", "person_id", "datum", "stunden", "taetigkeit"],
    "order_costs": ["order_id", "bezeichnung", "datum", "betrag", "product_id", "material_id", "menge", "einzelpreis"],
    "order_items": ["order_id", "sort", "bezeichnung", "beschreibung", "farbe_material", "personalisierung", "menge",
                    "einheit", "einzelpreis"],
    "images": ["titel"],
    "prints": ["notizen", "machine_id"],
}
NUMERIC = {"stundensatz", "verrechnungssatz", "anschaffung_preis", "lebensdauer_h", "leistung_w", "stunden_vorher",
           "wartung_eur_h", "preis", "gewechselt_bei_h", "bestand", "aufschlag_pct", "dauer_h", "menge", "stueck",
           "stunden", "betrag", "sort", "einzelpreis", "aktiv", "customer_id", "machine_id", "material_id",
           "order_id", "person_id", "versand", "anzahlung", "kwh", "herstellkosten", "product_id"}
REQUIRED = {"persons": "name", "machines": "name", "wear_parts": "name", "materials": "name", "orders": "titel",
            "products": "name"}
STATUS = ["anfrage", "angebot", "in_arbeit", "fertig", "abgeholt", "abgerechnet", "bezahlt", "storniert"]


def _clean(table, body: dict, partial=False):
    out = {}
    for k in TABLES[table]:
        if k not in body:
            continue
        v = body[k]
        if k in NUMERIC:
            if v in (None, ""):
                v = None
            else:
                try:
                    v = float(str(v).replace(",", "."))
                    if k.endswith("_id") or k in ("aktiv", "sort"):
                        v = int(v)
                except ValueError:
                    raise HTTPException(400, f"„{k}“ ist keine Zahl")
        elif isinstance(v, str):
            v = v.strip()
        out[k] = v
    req = REQUIRED.get(table)
    if req and (req in out or not partial) and not out.get(req):
        raise HTTPException(400, "Bitte einen Namen/Titel angeben")
    if table == "orders" and out.get("status") and out["status"] not in STATUS:
        raise HTTPException(400, "Unbekannter Status")
    if table == "orders" and out.get("uebergabe") not in (None, "", "abholung", "versand"):
        raise HTTPException(400, "Übergabe: abholung oder versand")
    if table == "orders" and out.get("zahlungsstatus") not in (None, "", "offen", "angezahlt", "bezahlt"):
        raise HTTPException(400, "Unbekannter Zahlungsstatus")
    return out


def _mat_qty(c, material_id, menge):
    if not material_id or not menge:
        return None, 0.0
    m = db.one(c.execute("SELECT einheit, bestand FROM materials WHERE id=?", (material_id,)))
    if not m or m["bestand"] is None:
        return None, 0.0
    return material_id, (float(menge) / 1000.0 if m["einheit"] == "kg" else float(menge))


def _stock(c, job, sign):
    """Lagerbestand anpassen: sign=-1 verbraucht, +1 zurückbuchen."""
    mid, q = _mat_qty(c, job.get("material_id"), job.get("menge"))
    if mid:
        c.execute("UPDATE materials SET bestand = ROUND(bestand + ?, 4) WHERE id=?", (sign * q, mid))


def _cost_stock(c, row, sign):
    """Zubehör aus dem Produktkatalog / Material: Lager anpassen (sign=-1 verbraucht, +1 zurück)."""
    menge = calc.f(row.get("menge"))
    if not menge:
        return
    if row.get("product_id"):
        c.execute("UPDATE products SET bestand = ROUND(bestand + ?, 4) WHERE id=? AND bestand IS NOT NULL",
                  (sign * menge, row["product_id"]))
    if row.get("material_id"):
        _stock(c, {"material_id": row["material_id"], "menge": menge}, sign)


def _row_stock(c, table, row, sign):
    if table == "order_jobs":
        _stock(c, row, sign)
    elif table == "order_costs":
        _cost_stock(c, row, sign)


def _cost_betrag(c, data, old=None):
    """Betrag = Menge × Preis pro Einheit (Material in kg: Menge in Gramm)."""
    m = {**(old or {}), **data}
    if m.get("menge") is None or m.get("einzelpreis") is None:
        return
    faktor = 1.0
    if m.get("material_id"):
        mat = db.one(c.execute("SELECT einheit FROM materials WHERE id=?", (m["material_id"],)))
        if mat and mat["einheit"] == "kg":
            faktor = 0.001
    data["betrag"] = round(calc.f(m["menge"]) * faktor * calc.f(m["einzelpreis"]), 2)


@app.post("/api/t/{table}")
def create(table: str, body: dict):
    if table not in TABLES or table in ("images", "prints"):
        raise HTTPException(404)
    data = _clean(table, body)
    warn = None
    with db.conn() as c:
        if table == "customers":
            data["nr"] = db.next_nr(c, "customers", settings.get("prefix_kunde"), yearly=False, digits=4)
        if table == "orders":
            data["nr"] = db.next_nr(c, "orders", settings.get("prefix_auftrag"))
            data.setdefault("eingang", date.today().isoformat())
            data["eingang"] = data["eingang"] or date.today().isoformat()
            data.setdefault("status", "anfrage")
        if table in ("order_jobs", "order_times", "order_costs") and not data.get("datum"):
            data["datum"] = date.today().isoformat()
        if table == "order_costs":
            _cost_betrag(c, data)
        if table == "order_items" and data.get("sort") is None:
            r = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM order_items WHERE order_id=?",
                          (data.get("order_id"),)).fetchone()
            data["sort"] = r[0]
        cols = list(data)
        cur = c.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                        [data[k] for k in cols])
        new_id = cur.lastrowid
        _row_stock(c, table, data, -1)
        row = db.one(c.execute(f"SELECT * FROM {table} WHERE id=?", (new_id,)))
    if table == "orders" and settings.flag("smb_ordner_auto") and _storage_configured():
        try:
            row["ordner"] = _ensure_folder(new_id)
        except (storage.StorageError, HTTPException) as e:
            warn = f"Auftragsordner konnte nicht angelegt werden: {getattr(e, 'detail', e)}"
    if table == "orders":
        ha.termin_soon(new_id)
    return {"row": row, "warning": warn}


@app.put("/api/t/{table}/{rid}")
def update(table: str, rid: int, body: dict):
    if table not in TABLES:
        raise HTTPException(404)
    data = _clean(table, body, partial=True)
    if not data:
        return {"ok": True}
    with db.conn() as c:
        old = db.one(c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)))
        if not old:
            raise HTTPException(404, "Nicht gefunden")
        _row_stock(c, table, old, +1)
        if table == "order_costs":
            _cost_betrag(c, data, old)
        sets = ", ".join(f"{k}=?" for k in data)
        if table in ("customers", "orders"):
            sets += ", updated_at=CURRENT_TIMESTAMP"
        if table == "orders" and data.get("status") and data["status"] != old["status"]:
            sets += ", ordner_fix=NULL"
        if table == "orders" and "ordner" in data and data["ordner"] != old["ordner"]:
            sets += ", ordner_offen=NULL"
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*data.values(), rid])
        row = db.one(c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)))
        _row_stock(c, table, row, -1)
    warn = None
    if table == "orders" and {"titel", "termin", "status", "customer_id"} & set(data):
        ha.termin_soon(rid)
    if table == "customers":
        with db.conn() as c:
            for r in c.execute("SELECT id FROM orders WHERE customer_id=? AND ha_termin_uid IS NOT NULL", (rid,)):
                ha.termin_soon(r["id"])
    if table == "orders" and data.get("status") and data["status"] != old["status"]:
        warn = archiv.sync_order_soon(rid)
        with db.conn() as c:
            row = db.one(c.execute("SELECT * FROM orders WHERE id=?", (rid,)))
    return {"row": row, "warning": warn}


@app.delete("/api/t/{table}/{rid}")
def delete(table: str, rid: int):
    if table not in TABLES:
        raise HTTPException(404)
    termin_uid = None
    with db.conn() as c:
        if table in ("order_jobs", "order_costs"):
            old = db.one(c.execute(f"SELECT * FROM {table} WHERE id=?", (rid,)))
            if old:
                _row_stock(c, table, old, +1)
        if table == "order_jobs":
            c.execute("UPDATE prints SET order_id=NULL, job_id=NULL WHERE job_id=?", (rid,))
        if table == "orders":
            n = c.execute("SELECT COUNT(*) FROM documents WHERE order_id=? AND typ='rechnung' AND status!='storniert'",
                          (rid,)).fetchone()[0]
            if n:
                raise HTTPException(400, "Zu diesem Auftrag gibt es Rechnungen – bitte Status „storniert“ verwenden.")
            r = c.execute("SELECT ha_termin_uid FROM orders WHERE id=?", (rid,)).fetchone()
            termin_uid = r["ha_termin_uid"] if r else None
        files = []
        if table in ("orders", "customers"):
            col = "order_id" if table == "orders" else "customer_id"
            files = [r["datei"] for r in c.execute(f"SELECT datei FROM images WHERE {col}=?", (rid,))]
        if table == "images":
            files = [r["datei"] for r in c.execute("SELECT datei FROM images WHERE id=?", (rid,))]
        c.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
    for f in files:
        images.delete_files(f)
    if termin_uid:
        ha.termin_soon(remove_uid=termin_uid)
    return {"ok": True}


@app.post("/api/wear_parts/{pid}/gewechselt")
def wear_changed(pid: int):
    data = _load_all()
    for p in data["wear_parts"]:
        if p["id"] == pid:
            m = next(x for x in data["machines"] if x["id"] == p["machine_id"])
            with db.conn() as c:
                c.execute("UPDATE wear_parts SET gewechselt_bei_h=?, notizen=TRIM(COALESCE(notizen,'') || ?) WHERE id=?",
                          (m["stunden_gesamt"], f"\nGewechselt am {date.today():%d.%m.%Y} bei {m['stunden_gesamt']} h",
                           pid))
            return {"ok": True}
    raise HTTPException(404)


# ---------- Alles laden ----------

def _load_all():
    with db.conn() as c:
        d = {t: db.rows(c.execute(f"SELECT * FROM {t} ORDER BY id")) for t in TABLES}
        d["prints"] = db.rows(c.execute("SELECT * FROM prints ORDER BY datum DESC, uhrzeit DESC, id DESC"))
        d["documents"] = db.rows(c.execute(
            "SELECT id, typ, nr, order_id, customer_id, datum, leistungsdatum, faellig, netto, ust_satz, ust, brutto,"
            " kleinunternehmer, anzahlung, status, bezahlt_am, pdf, notizen, kunde_json, einleitung, schluss, positionen_json,"
            " ablage"
            " FROM documents ORDER BY datum DESC, id DESC"))
    for doc in d["documents"]:
        doc["kunde"] = json.loads(doc.pop("kunde_json") or "{}")
        doc["positionen"] = json.loads(doc.pop("positionen_json") or "[]")
    return calc.enrich(d)


@app.get("/api/data")
def get_data():
    d = _load_all()
    d["settings"] = settings.public()
    d["version"] = VERSION
    d["status_list"] = STATUS
    d["storage_ok"] = _storage_configured()
    return d


# ---------- Einstellungen ----------

@app.put("/api/settings")
def put_settings(body: dict):
    settings.update_from_ui(body)
    return settings.public()


class PwIn(BaseModel):
    password: str = ""


@app.post("/api/password")
def set_pw(body: PwIn, request: Request):
    settings.set_password(body.password)
    resp = JSONResponse({"ok": True, "password_set": bool(body.password)})
    if body.password:
        _session_cookie(resp, request)
    return resp


@app.post("/api/vorlage/logo")
async def upload_logo(file: UploadFile = File(...)):
    data = await file.read()
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise HTTPException(400, "Kein lesbares Bild")
    old = settings.get("logo")
    name = f"logo-{datetime.now():%Y%m%d%H%M%S}.png"
    im.thumbnail((1200, 600))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    im.save(os.path.join(db.VORLAGE_DIR, name), "PNG")
    settings.set_many({"logo": name})
    if old:
        try:
            os.remove(os.path.join(db.VORLAGE_DIR, old))
        except OSError:
            pass
    return {"logo": name}


@app.delete("/api/vorlage/logo")
def delete_logo():
    old = settings.get("logo")
    settings.set_many({"logo": ""})
    if old:
        try:
            os.remove(os.path.join(db.VORLAGE_DIR, os.path.basename(old)))
        except OSError:
            pass
    return {"ok": True}


@app.get("/vorlage/{name}")
def vorlage_file(name: str):
    p = os.path.join(db.VORLAGE_DIR, os.path.basename(name))
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/vorlage/muster.pdf")
def muster_pdf():
    return Response(pdf.sample(), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="Musterrechnung.pdf"', "Cache-Control": "no-store"})


# ---------- Netzlaufwerk ----------

def _storage_configured():
    if settings.get("lokal_auftraege").strip():
        return True
    return bool(settings.get("smb_host").strip() and settings.get("smb_auftraege_share").strip())


def _order_ctx(c, oid):
    o = db.one(c.execute("SELECT * FROM orders WHERE id=?", (oid,)))
    if not o:
        raise HTTPException(404, "Auftrag nicht gefunden")
    k = db.one(c.execute("SELECT * FROM customers WHERE id=?", (o["customer_id"],))) if o["customer_id"] else None
    return o, k


def _ensure_folder(oid):
    with db.conn() as c:
        o, k = _order_ctx(c, oid)
    rel = o["ordner"] or storage.order_folder_name(o, k)
    fs = storage.FS("auftraege")
    fs.makedirs(rel)
    if rel != o["ordner"]:
        with db.conn() as c:
            c.execute("UPDATE orders SET ordner=? WHERE id=?", (rel, oid))
    return rel


class AreaIn(BaseModel):
    area: str = "auftraege"


@app.post("/api/storage/test")
def storage_test(body: AreaIn):
    def _t():
        fs = storage.FS(body.area)
        fs.makedirs()
        entries = fs.listdir()
        return {"ok": True, "pfad": fs.unc(), "eintraege": len(entries)}
    try:
        return _t()
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


@app.post("/api/orders/{oid}/folder")
def create_folder(oid: int):
    try:
        rel = _ensure_folder(oid)
        return {"ordner": rel, "pfad": storage.FS("auftraege").unc(rel)}
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


class AbschlussIn(BaseModel):
    abgeschlossen: bool


@app.post("/api/orders/{oid}/folder/abschluss")
def folder_abschluss(oid: int, body: AbschlussIn):
    """Sonderfall: Ordner von Hand nach „Abgeschlossen“ verschieben bzw. zurückholen."""
    if not _storage_configured():
        raise HTTPException(400, "Netzlaufwerk ist nicht eingerichtet")
    with db.conn() as c:
        o, _ = _order_ctx(c, oid)
        if not o["ordner"]:
            raise HTTPException(400, "Dieser Auftrag hat noch keinen Ordner")
        c.execute("UPDATE orders SET ordner_fix=? WHERE id=?", (1 if body.abgeschlossen else 0, oid))
    warn = archiv.sync_order(oid, force=True)
    with db.conn() as c:
        o = db.one(c.execute("SELECT ordner FROM orders WHERE id=?", (oid,)))
    return {"ordner": o["ordner"], "warning": warn}


@app.post("/api/ablage/sync")
def ablage_sync():
    if not _storage_configured():
        raise HTTPException(400, "Netzlaufwerk ist nicht eingerichtet")
    return ablage.sync_all()


@app.post("/api/archiv/sync")
def archiv_sync():
    if not _storage_configured():
        raise HTTPException(400, "Netzlaufwerk ist nicht eingerichtet")
    return archiv.sync_all()


@app.get("/api/orders/{oid}/files")
def list_files(oid: int, sub: str = ""):
    with db.conn() as c:
        o, _ = _order_ctx(c, oid)
    if not o["ordner"]:
        return {"ordner": None, "files": []}
    try:
        fs = storage.FS("auftraege")
        rel = "/".join(storage.clean_rel(o["ordner"]) + storage.clean_rel(sub))
        if not fs.exists(rel):
            return {"ordner": o["ordner"], "pfad": fs.unc(rel), "fehlt": True, "files": []}
        return {"ordner": o["ordner"], "pfad": fs.unc(rel), "files": fs.listdir(rel)}
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


@app.get("/api/orders/{oid}/file")
def get_file(oid: int, path: str, download: int = 0):
    with db.conn() as c:
        o, _ = _order_ctx(c, oid)
    if not o["ordner"]:
        raise HTTPException(404)
    try:
        fs = storage.FS("auftraege")
        rel = "/".join(storage.clean_rel(o["ordner"]) + storage.clean_rel(path))
        fh = fs.open(rel, "rb")
    except storage.StorageError as e:
        raise HTTPException(400, str(e))
    name = storage.clean_rel(path)[-1]
    mt = mimetypes.guess_type(name)[0] or "application/octet-stream"
    inline = not download and (mt.startswith("image/") or mt in ("application/pdf", "text/plain"))

    def it():
        try:
            while True:
                chunk = fh.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            fh.close()
    from urllib.parse import quote
    disp = ("inline" if inline else "attachment") + f"; filename*=UTF-8''{quote(name)}"
    return StreamingResponse(it(), media_type=mt, headers={"Content-Disposition": disp})


@app.post("/api/orders/{oid}/files")
async def upload_files(oid: int, files: List[UploadFile] = File(...), sub: str = Form("")):
    with db.conn() as c:
        o, _ = _order_ctx(c, oid)
    try:
        rel0 = o["ordner"] or await run_in_threadpool(_ensure_folder, oid)
        fs = storage.FS("auftraege")
        n = 0
        for f in files:
            data = await f.read()
            name = storage.safe_name(os.path.basename(f.filename or "datei"), 150)
            rel = "/".join(storage.clean_rel(rel0) + storage.clean_rel(sub) + [name])
            await run_in_threadpool(fs.write_bytes, rel, data)
            n += 1
        return {"ok": True, "anzahl": n}
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


# ---------- Bilder ----------

@app.post("/api/orders/{oid}/images")
async def upload_images(oid: int, files: List[UploadFile] = File(...)):
    out, errors = [], []
    for f in files:
        data = await f.read()
        try:
            name = await run_in_threadpool(images.save_upload, data)
        except ValueError as e:
            errors.append(f"{f.filename}: {e}")
            continue
        with db.conn() as c:
            cur = c.execute("INSERT INTO images(order_id, datei, original) VALUES(?,?,?)", (oid, name, f.filename))
            out.append(db.one(c.execute("SELECT * FROM images WHERE id=?", (cur.lastrowid,))))
    return {"rows": out, "errors": errors}


@app.get("/bilder/{name}")
def bild(name: str):
    p = os.path.join(db.BILDER_DIR, os.path.basename(name))
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.post("/api/images/{iid}/to-folder")
def image_to_folder(iid: int):
    with db.conn() as c:
        im = db.one(c.execute("SELECT * FROM images WHERE id=?", (iid,)))
    if not im or not im["order_id"]:
        raise HTTPException(404)
    try:
        rel0 = _ensure_folder(im["order_id"])
        name = storage.safe_name(os.path.splitext(im["original"] or im["datei"])[0], 100) + ".jpg"
        storage.FS("auftraege").copy_from_local(os.path.join(db.BILDER_DIR, im["datei"]),
                                                "/".join(storage.clean_rel(rel0) + ["Bilder", name]))
        return {"ok": True}
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


# ---------- Rechnungspositionen aus Kalkulation ----------

class GenIn(BaseModel):
    modus: str = "pauschal"  # pauschal | detail
    ersetzen: bool = True
    stueck: Optional[float] = None


@app.post("/api/orders/{oid}/items/generate")
def generate_items(oid: int, body: GenIn):
    d = _load_all()
    o = next((x for x in d["orders"] if x["id"] == oid), None)
    if not o:
        raise HTTPException(404)
    k = o["kosten"]
    auf = 1 + k["aufschlag_pct"] / 100
    machines = {m["id"]: m for m in d["machines"]}
    mats = {m["id"]: m for m in d["materials"]}
    persons = {p["id"]: p for p in d["persons"]}
    items = []
    if body.modus == "detail":
        for j in (x for x in d["order_jobs"] if x["order_id"] == oid):
            m = machines.get(j["machine_id"])
            art = "Lasern" if m and m["typ"] == "laser" else "3D-Druck"
            mat = mats.get(j["material_id"])
            besch = ", ".join(x for x in (mat["name"] if mat else "", j["notizen"] or "") if x)
            st = calc.f(j["stueck"]) or 1
            preis = (j["kosten_maschine"] + j["kosten_material"]) * auf
            items.append({"bezeichnung": f"{art}: {j['bezeichnung'] or o['titel']}", "beschreibung": besch,
                          "menge": st, "einheit": "Stk", "einzelpreis": calc.round_price(preis / st)})
        hours = {}
        for t in (x for x in d["order_times"] if x["order_id"] == oid):
            key = (t["taetigkeit"] or "Arbeitszeit").strip() or "Arbeitszeit"
            p = persons.get(t["person_id"])
            hours.setdefault(key, [0.0, 0.0])
            hours[key][0] += calc.f(t["stunden"])
            hours[key][1] += calc.f(t["stunden"]) * (calc.f(p["verrechnungssatz"]) if p else 0)
        for name, (h, val) in hours.items():
            if h > 0:
                items.append({"bezeichnung": name, "beschreibung": "", "menge": round(h, 2), "einheit": "Std",
                              "einzelpreis": round(val / h, 2)})
        for x in (x for x in d["order_costs"] if x["order_id"] == oid):
            items.append({"bezeichnung": x["bezeichnung"] or "Material / Zubehör", "beschreibung": "",
                          "menge": 1, "einheit": "pausch.", "einzelpreis": calc.round_price(calc.f(x["betrag"]) * auf)})
    else:
        st = body.stueck or k["stueck"] or 1
        items.append({"bezeichnung": o["titel"], "beschreibung": o["beschreibung"] or "", "menge": st,
                      "einheit": "Stk", "einzelpreis": calc.round_price(k["empfohlen"] / st)})
    with db.conn() as c:
        if body.ersetzen:
            c.execute("DELETE FROM order_items WHERE order_id=?", (oid,))
        start = c.execute("SELECT COALESCE(MAX(sort),0) FROM order_items WHERE order_id=?", (oid,)).fetchone()[0]
        for i, it in enumerate(items, 1):
            c.execute("INSERT INTO order_items(order_id, sort, bezeichnung, beschreibung, menge, einheit, einzelpreis)"
                      " VALUES(?,?,?,?,?,?,?)", (oid, start + i, it["bezeichnung"], it["beschreibung"], it["menge"],
                                                 it["einheit"], it["einzelpreis"]))
    return {"ok": True, "anzahl": len(items)}


# ---------- Rechnungen / Angebote ----------

class DocIn(BaseModel):
    typ: str = "rechnung"
    datum: Optional[str] = None
    leistungsdatum: Optional[str] = None
    faellig: Optional[str] = None
    einleitung: Optional[str] = None
    schluss: Optional[str] = None
    positionen: Optional[list] = None
    notizen: Optional[str] = None
    anzahlung: Optional[float] = None


def _doc_full(c, did):
    d = db.one(c.execute("SELECT * FROM documents WHERE id=?", (did,)))
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    d["kunde"] = json.loads(d.pop("kunde_json") or "{}")
    d["positionen"] = json.loads(d.pop("positionen_json") or "[]")
    if d["order_id"]:
        o = db.one(c.execute("SELECT nr, titel, ordner FROM orders WHERE id=?", (d["order_id"],)))
        if o:
            d["auftrag_nr"], d["auftrag_titel"], d["ordner"] = o["nr"], o["titel"], o["ordner"]
    return d


def _totals(pos):
    ku = settings.flag("kleinunternehmer")
    ust_satz = 0.0 if ku else settings.num("ust_satz", 20)
    netto = round(sum(calc.f(p.get("menge")) * calc.f(p.get("einzelpreis")) for p in pos), 2)
    ust = round(netto * ust_satz / 100, 2)
    return {"netto": netto, "ust_satz": ust_satz, "ust": ust, "brutto": round(netto + ust, 2),
            "kleinunternehmer": 1 if ku else 0}


def _clean_pos(pos):
    out = []
    for p in pos or []:
        if not (p.get("bezeichnung") or "").strip():
            continue
        item = {"bezeichnung": p["bezeichnung"].strip(), "beschreibung": (p.get("beschreibung") or "").strip(),
                    "farbe_material": (p.get("farbe_material") or "").strip(),
                    "personalisierung": (p.get("personalisierung") or "").strip(),
                    "menge": calc.f(str(p.get("menge") or 0).replace(",", ".")), "einheit": p.get("einheit") or "",
                    "einzelpreis": calc.f(str(p.get("einzelpreis") or 0).replace(",", "."))}
        try:
            pid = int(p.get("product_id") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid:
            item["product_id"] = pid
        out.append(item)
    return out


def _stock_active(typ, status):
    """Nur gültige Rechnungen buchen Produkte aus dem Lager ab (keine Angebote, keine Stornos)."""
    return typ == "rechnung" and status != "storniert"


def _product_stock(c, pos, sign):
    """Produkt-Lagerbestand anpassen: sign=-1 verkauft, +1 zurückbuchen."""
    for p in pos or []:
        pid, menge = p.get("product_id"), calc.f(p.get("menge"))
        if pid and menge:
            c.execute("UPDATE products SET bestand = ROUND(bestand + ?, 4) WHERE id=? AND bestand IS NOT NULL",
                      (sign * menge, pid))


def _render_doc(did, copy_smb=True):
    with db.conn() as c:
        d = _doc_full(c, did)
    fname = storage.safe_name(d["nr"], 40) + ".pdf"
    path = os.path.join(db.DOKU_DIR, fname)
    pdf.render(d, path)
    with db.conn() as c:
        c.execute("UPDATE documents SET pdf=? WHERE id=?", (fname, did))
    warn = None
    if copy_smb and d.get("ordner") and settings.flag("smb_pdf_kopieren") and _storage_configured():
        try:
            label = "Rechnung" if d["typ"] == "rechnung" else "Angebot"
            storage.FS("auftraege").copy_from_local(
                path, "/".join(storage.clean_rel(d["ordner"]) + [f"{label} {fname}"]))
        except storage.StorageError as e:
            warn = f"PDF nicht ins Auftragsverzeichnis kopiert: {e}"
    if copy_smb and d["typ"] == "rechnung":
        warn = " ".join(x for x in (warn, ablage.sync_doc(did, force=True)) if x) or None
    return warn


def _kunde_json(k):
    return {kk: k.get(kk) for kk in ("nr", "firma", "anrede", "vorname", "nachname", "strasse", "plz", "ort", "land",
                                     "uid", "email")} if k else {}


def _insert_doc(c, body, pos, o, k, bezahlt_am=None):
    """Legt Rechnung/Angebot an (mit oder ohne Auftrag) und bucht Produkte aus dem Lager ab."""
    datum = body.datum or date.today().isoformat()
    tage = settings.num("zahlungsziel_tage" if body.typ == "rechnung" else "angebot_gueltig_tage", 14)
    faellig = body.faellig or (date.fromisoformat(datum) + timedelta(days=int(tage))).isoformat()
    prefix = settings.get("prefix_rechnung" if body.typ == "rechnung" else "prefix_angebot")
    nr = db.next_nr(c, "documents", prefix, typ=body.typ, year=datum[:4])
    einl = body.einleitung if body.einleitung is not None else settings.get(f"{body.typ}_einleitung")
    schl = body.schluss if body.schluss is not None else settings.get(
        "rechnung_schluss_bezahlt" if bezahlt_am else f"{body.typ}_schluss")
    t = _totals(pos)
    anz = None
    if body.typ == "rechnung":
        anz = body.anzahlung if body.anzahlung is not None else calc.f((o or {}).get("anzahlung")) or None
    status = "bezahlt" if bezahlt_am and body.typ == "rechnung" else "offen"
    cur = c.execute(
        "INSERT INTO documents(typ, nr, order_id, customer_id, datum, leistungsdatum, faellig, kunde_json,"
        " positionen_json, einleitung, schluss, netto, ust_satz, ust, brutto, kleinunternehmer, notizen,"
        " anzahlung, status, bezahlt_am) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.typ, nr, o["id"] if o else None, k["id"] if k else None, datum,
         body.leistungsdatum or (datum if body.typ == "rechnung" else None), faellig,
         json.dumps(_kunde_json(k), ensure_ascii=False), json.dumps(pos, ensure_ascii=False), einl, schl,
         t["netto"], t["ust_satz"], t["ust"], t["brutto"], t["kleinunternehmer"], body.notizen, anz,
         status, bezahlt_am if status == "bezahlt" else None))
    if _stock_active(body.typ, status):
        _product_stock(c, pos, -1)
    return cur.lastrowid, nr


@app.post("/api/orders/{oid}/documents")
def create_doc(oid: int, body: DocIn):
    if body.typ not in ("rechnung", "angebot"):
        raise HTTPException(400, "Typ muss rechnung oder angebot sein")
    with db.conn() as c:
        o, k = _order_ctx(c, oid)
        pos = body.positionen
        if pos is None:
            pos = db.rows(c.execute("SELECT bezeichnung, beschreibung, farbe_material, personalisierung, menge,"
                                    " einheit, einzelpreis FROM order_items WHERE order_id=? ORDER BY sort, id",
                                    (oid,)))
            if calc.f(o.get("versand")) > 0:
                pos.append({"bezeichnung": "Versand", "menge": 1, "einheit": "pausch.",
                            "einzelpreis": calc.f(o["versand"])})
        pos = _clean_pos(pos)
        if not pos:
            raise HTTPException(400, "Keine Positionen – bitte zuerst Rechnungspositionen anlegen.")
        if not k:
            raise HTTPException(400, "Dem Auftrag ist noch kein Kunde zugeordnet.")
        did, nr = _insert_doc(c, body, pos, o, k)
        new_status = "abgerechnet" if body.typ == "rechnung" else "angebot"
        order_rank = STATUS.index(o["status"]) if o["status"] in STATUS else 0
        if STATUS.index(new_status) > order_rank and o["status"] != "storniert":
            c.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, oid))
    ha.termin_soon(oid)
    warn = _render_doc(did)
    return {"id": did, "nr": nr, "warning": warn}


class DocFrei(DocIn):
    customer_id: Optional[int] = None
    bezahlt: bool = False
    bezahlt_am: Optional[str] = None


@app.post("/api/documents")
def create_doc_frei(body: DocFrei):
    """Rechnung/Angebot ohne Auftrag – z. B. Verkauf fertiger Produkte aus dem Lager."""
    if body.typ not in ("rechnung", "angebot"):
        raise HTTPException(400, "Typ muss rechnung oder angebot sein")
    with db.conn() as c:
        k = None
        if body.customer_id:
            k = db.one(c.execute("SELECT * FROM customers WHERE id=?", (body.customer_id,)))
            if not k:
                raise HTTPException(400, "Kunde nicht gefunden")
        pos = _clean_pos(body.positionen)
        if not pos:
            raise HTTPException(400, "Bitte mindestens eine Position eintragen.")
        bezahlt_am = (body.bezahlt_am or body.datum or date.today().isoformat()) if body.bezahlt else None
        did, nr = _insert_doc(c, body, pos, None, k, bezahlt_am)
    warn = _render_doc(did)
    return {"id": did, "nr": nr, "warning": warn}


class DocUpd(BaseModel):
    status: Optional[str] = None
    bezahlt_am: Optional[str] = None
    notizen: Optional[str] = None
    datum: Optional[str] = None
    leistungsdatum: Optional[str] = None
    faellig: Optional[str] = None
    einleitung: Optional[str] = None
    schluss: Optional[str] = None
    positionen: Optional[list] = None
    anzahlung: Optional[float] = None
    kunde_aktualisieren: bool = False
    customer_id: Optional[int] = None       # nur bei Rechnungen ohne Auftrag; 0 = ohne Kunde


@app.put("/api/documents/{did}")
def update_doc(did: int, body: DocUpd):
    rerender = False
    with db.conn() as c:
        d = _doc_full(c, did)
        sets = {}
        if body.status is not None:
            if body.status not in ("offen", "bezahlt", "storniert", "angenommen", "abgelehnt"):
                raise HTTPException(400, "Unbekannter Status")
            sets["status"] = body.status
            if body.status == "bezahlt":
                sets["bezahlt_am"] = body.bezahlt_am or d.get("bezahlt_am") or date.today().isoformat()
                if d["order_id"] and d["typ"] == "rechnung":
                    c.execute("UPDATE orders SET status='bezahlt', zahlungsstatus='bezahlt', zahlungsdatum=?,"
                              " ordner_fix=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status!='storniert'",
                              (sets["bezahlt_am"], d["order_id"]))
            elif body.status == "offen":
                sets["bezahlt_am"] = None
            if body.status == "angenommen" and d["order_id"]:
                c.execute("UPDATE orders SET status='in_arbeit', updated_at=CURRENT_TIMESTAMP WHERE id=? "
                          "AND status IN ('anfrage','angebot')", (d["order_id"],))
        if body.bezahlt_am is not None and body.status is None:
            sets["bezahlt_am"] = body.bezahlt_am or None
        if body.notizen is not None:
            sets["notizen"] = body.notizen
        for f in ("datum", "leistungsdatum", "faellig", "einleitung", "schluss"):
            v = getattr(body, f)
            if v is not None and v != d.get(f):
                sets[f] = v
                rerender = True
        if body.anzahlung is not None and body.anzahlung != d.get("anzahlung"):
            sets["anzahlung"] = body.anzahlung or None
            rerender = True
        if body.positionen is not None:
            pos = _clean_pos(body.positionen)
            if not pos:
                raise HTTPException(400, "Mindestens eine Position nötig")
            sets["positionen_json"] = json.dumps(pos, ensure_ascii=False)
            sets.update(_totals(pos))
            rerender = True
        if body.customer_id is not None and not d["order_id"] and (body.customer_id or None) != d["customer_id"]:
            k = db.one(c.execute("SELECT * FROM customers WHERE id=?", (body.customer_id,))) if body.customer_id else None
            if body.customer_id and not k:
                raise HTTPException(400, "Kunde nicht gefunden")
            sets["customer_id"] = k["id"] if k else None
            sets["kunde_json"] = json.dumps(_kunde_json(k), ensure_ascii=False)
            rerender = True
        elif body.kunde_aktualisieren and d["customer_id"]:
            k = db.one(c.execute("SELECT * FROM customers WHERE id=?", (d["customer_id"],)))
            if k:
                sets["kunde_json"] = json.dumps(_kunde_json(k), ensure_ascii=False)
                rerender = True
        # Lager: alten Stand zurückbuchen, neuen abbuchen (Storno / Positionen geändert)
        if _stock_active(d["typ"], d["status"]):
            _product_stock(c, d["positionen"], +1)
        new_pos = json.loads(sets["positionen_json"]) if "positionen_json" in sets else d["positionen"]
        if _stock_active(d["typ"], sets.get("status", d["status"])):
            _product_stock(c, new_pos, -1)
        if sets:
            c.execute(f"UPDATE documents SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", [*sets.values(), did])
    warn = _render_doc(did) if rerender else None
    if body.status == "bezahlt" and d["order_id"] and d["typ"] == "rechnung":
        warn = " ".join(x for x in (warn, archiv.sync_order_soon(d["order_id"])) if x) or None
    if d["order_id"] and body.status is not None:
        ha.termin_soon(d["order_id"])
    if body.status is not None and not rerender and d["typ"] == "rechnung":
        warn = " ".join(x for x in (warn, ablage.sync_doc(did)) if x) or None  # z. B. Storno → Dateiname
    return {"ok": True, "warning": warn}


@app.post("/api/documents/{did}/render")
def rerender_doc(did: int):
    return {"ok": True, "warning": _render_doc(did)}


@app.delete("/api/documents/{did}")
def delete_doc(did: int):
    with db.conn() as c:
        d = db.one(c.execute("SELECT * FROM documents WHERE id=?", (did,)))
        if not d:
            raise HTTPException(404)
        if d["typ"] == "rechnung":
            prefix = settings.get("prefix_rechnung")
            nxt = db.next_nr(c, "documents", prefix, typ="rechnung", year=(d["datum"] or "")[:4] or None)
            if nxt != _bump(d["nr"]):
                raise HTTPException(400, "Nur die letzte Rechnung kann gelöscht werden (lückenlose Nummern). "
                                         "Ältere Rechnungen bitte auf „storniert“ setzen.")
        if _stock_active(d["typ"], d["status"]):
            _product_stock(c, json.loads(d["positionen_json"] or "[]"), +1)
        c.execute("DELETE FROM documents WHERE id=?", (did,))
    ablage.remove(d.get("ablage"))
    if d.get("pdf"):
        try:
            os.remove(os.path.join(db.DOKU_DIR, d["pdf"]))
        except OSError:
            pass
    return {"ok": True}


def _bump(nr):
    m = re.match(r"^(.*?)(\d+)$", nr or "")
    if not m:
        return None
    return f"{m.group(1)}{int(m.group(2)) + 1:0{len(m.group(2))}d}"


@app.get("/api/documents/{did}/pdf")
def doc_pdf(did: int, download: int = 0):
    with db.conn() as c:
        d = db.one(c.execute("SELECT nr, pdf, typ FROM documents WHERE id=?", (did,)))
    if not d:
        raise HTTPException(404)
    p = os.path.join(db.DOKU_DIR, d["pdf"] or "")
    if not d["pdf"] or not os.path.exists(p):
        _render_doc(did, copy_smb=False)
        with db.conn() as c:
            d = db.one(c.execute("SELECT nr, pdf, typ FROM documents WHERE id=?", (did,)))
        p = os.path.join(db.DOKU_DIR, d["pdf"])
    label = "Rechnung" if d["typ"] == "rechnung" else "Angebot"
    return FileResponse(p, media_type="application/pdf", filename=f"{label} {d['nr']}.pdf",
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "no-store"})


# ---------- Schnellrechner ----------

@app.post("/api/rechner")
def rechner(body: dict):
    with db.conn() as c:
        ms = db.rows(c.execute("SELECT * FROM machines"))
        ps = db.rows(c.execute("SELECT * FROM wear_parts"))
        mats = db.rows(c.execute("SELECT * FROM materials"))
        pers = db.rows(c.execute("SELECT * FROM persons"))
    def norm(d):
        d = dict(d or {})
        for k in ("machine_id", "material_id", "person_id"):
            try:
                d[k] = int(d[k]) if d.get(k) not in (None, "") else None
            except (TypeError, ValueError):
                d[k] = None
        for k in ("dauer_h", "menge", "arbeit_h", "stunden", "extra", "betrag", "stueck", "aufschlag_pct"):
            if isinstance(d.get(k), str):
                d[k] = d[k].replace(",", ".") or None
        return d

    inp = norm(body)
    for k in ("jobs", "arbeit", "extras"):
        if isinstance(body.get(k), list):
            inp[k] = [norm(x) for x in body[k] if isinstance(x, dict)]
    return calc.quick(inp, ms, ps, mats, pers)


# ---------- Auswertung ----------

@app.get("/api/auswertung")
def auswertung(jahr: int = 0):
    jahr = jahr or date.today().year
    d = _load_all()
    ys = str(jahr)
    months = [{"monat": i, "umsatz": 0.0, "bezahlt": 0.0, "maschine": 0.0, "material": 0.0, "arbeit": 0.0,
               "fremd": 0.0, "stunden": {}, "maschinen_h": {}} for i in range(1, 13)]
    orders = {o["id"]: o for o in d["orders"]}

    def mon(datum, oid=None):
        ds = datum or (orders.get(oid) or {}).get("eingang") or ""
        if ds[:4] != ys:
            return None
        try:
            return months[int(ds[5:7]) - 1]
        except (ValueError, IndexError):
            return None

    kunden_umsatz = {}
    for doc in d["documents"]:
        if doc["typ"] != "rechnung" or doc["status"] == "storniert":
            continue
        m = mon(doc["datum"])
        if m:
            m["umsatz"] += doc["netto"] or 0
            if doc["status"] == "bezahlt":
                m["bezahlt"] += doc["netto"] or 0
            if doc["customer_id"]:
                kunden_umsatz[doc["customer_id"]] = kunden_umsatz.get(doc["customer_id"], 0) + (doc["netto"] or 0)
    for j in d["order_jobs"]:
        m = mon(j["datum"], j["order_id"])
        if m:
            m["maschine"] += j.get("kosten_maschine", 0)
            m["material"] += j.get("kosten_material", 0)
            m["maschinen_h"][j["machine_id"]] = m["maschinen_h"].get(j["machine_id"], 0) + calc.f(j["dauer_h"])
    for t in d["order_times"]:
        m = mon(t["datum"], t["order_id"])
        if m:
            m["arbeit"] += t.get("kosten", 0)
            m["stunden"][t["person_id"]] = m["stunden"].get(t["person_id"], 0) + calc.f(t["stunden"])
    for x in d["order_costs"]:
        m = mon(x["datum"], x["order_id"])
        if m:
            m["fremd"] += calc.f(x["betrag"])
    for m in months:
        m["kosten"] = m["maschine"] + m["material"] + m["arbeit"] + m["fremd"]
        m["gewinn"] = m["umsatz"] - m["kosten"]
        for k in ("umsatz", "bezahlt", "maschine", "material", "arbeit", "fremd", "kosten", "gewinn"):
            m[k] = calc.r2(m[k])
        m["stunden"] = {str(k): round(v, 2) for k, v in m["stunden"].items()}
        m["maschinen_h"] = {str(k): round(v, 2) for k, v in m["maschinen_h"].items()}

    tot = {k: calc.r2(sum(m[k] for m in months)) for k in
           ("umsatz", "bezahlt", "maschine", "material", "arbeit", "fremd", "kosten", "gewinn")}
    offen = [x for x in d["documents"] if x["typ"] == "rechnung" and x["status"] == "offen"]
    custs = {k["id"]: k for k in d["customers"]}
    top = sorted(kunden_umsatz.items(), key=lambda kv: -kv[1])[:10]
    jahre = sorted({int(x["datum"][:4]) for x in d["documents"] if x.get("datum")} |
                   {int(o["eingang"][:4]) for o in d["orders"] if o.get("eingang")} | {date.today().year},
                   reverse=True)
    auftraege = []
    for o in d["orders"]:
        if (o.get("eingang") or "")[:4] == ys:
            k = custs.get(o["customer_id"])
            auftraege.append({"id": o["id"], "nr": o["nr"], "titel": o["titel"], "status": o["status"],
                              "kunde": _kname(k), **o["kosten"]})
    return {
        "jahr": jahr, "jahre": jahre, "monate": months, "summe": tot,
        "offen_anzahl": len(offen), "offen_summe": calc.r2(sum(x["brutto"] or 0 for x in offen)),
        "ueberfaellig": [x["id"] for x in offen if x.get("faellig") and x["faellig"] < date.today().isoformat()],
        "top_kunden": [{"id": cid, "name": _kname(custs.get(cid)), "umsatz": calc.r2(v)} for cid, v in top],
        "auftraege": auftraege,
    }


def _kname(k):
    if not k:
        return "–"
    return k.get("firma") or " ".join(x for x in (k.get("vorname"), k.get("nachname")) if x) or k.get("nr") or "–"


# ---------- Export ----------

@app.get("/api/export/{what}.csv")
def export_csv(what: str, jahr: int = 0):
    d = _load_all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    if what == "rechnungen":
        w.writerow(["Nummer", "Datum", "Leistungsdatum", "Kunde", "Kundennr", "Netto", "USt-Satz", "USt", "Brutto",
                    "Status", "Bezahlt am"])
        for x in sorted(d["documents"], key=lambda x: x["nr"]):
            if x["typ"] != "rechnung" or (jahr and (x["datum"] or "")[:4] != str(jahr)):
                continue
            k = x["kunde"]
            w.writerow([x["nr"], x["datum"], x["leistungsdatum"], _kname(k), k.get("nr"), _de(x["netto"]),
                        _de(x["ust_satz"]), _de(x["ust"]), _de(x["brutto"]), x["status"], x["bezahlt_am"] or ""])
    elif what == "kunden":
        cols = ["nr", "firma", "anrede", "vorname", "nachname", "strasse", "plz", "ort", "land", "email", "telefon",
                "uid", "notizen"]
        w.writerow(cols)
        for k in d["customers"]:
            w.writerow([k.get(c) or "" for c in cols])
    elif what == "auftraege":
        w.writerow(["Nummer", "Eingang", "Titel", "Kunde", "Status", "Selbstkosten", "Umsatz", "Gewinn",
                    "Arbeitsstunden", "Maschinenstunden"])
        custs = {k["id"]: k for k in d["customers"]}
        for o in d["orders"]:
            if jahr and (o["eingang"] or "")[:4] != str(jahr):
                continue
            k = o["kosten"]
            w.writerow([o["nr"], o["eingang"], o["titel"], _kname(custs.get(o["customer_id"])), o["status"],
                        _de(k["selbstkosten"]), _de(k["umsatz"]), _de(k["gewinn"]), _de(k["stunden_arbeit"]),
                        _de(k["stunden_maschine"])])
    else:
        raise HTTPException(404)
    data = "﻿" + buf.getvalue()
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{what}{"-" + str(jahr) if jahr else ""}.csv"'})


def _de(x):
    return f"{float(x or 0):.2f}".replace(".", ",")


# ---------- Backup ----------

@app.post("/api/backup/run")
def backup_run():
    ok, text = backup.run(manual=True)
    return {"ok": ok, "text": text, "settings": settings.public()}


@app.get("/api/backup/list")
def backup_list():
    return backup.list_local()


@app.get("/api/backup/download/{name}")
def backup_download(name: str):
    p = os.path.join(db.BACKUP_DIR, os.path.basename(name))
    if not os.path.exists(p) or not name.endswith(".zip"):
        raise HTTPException(404)
    return FileResponse(p, filename=os.path.basename(p), media_type="application/zip")


@app.post("/api/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    fd, tmp = tempfile.mkstemp(suffix=".upload", dir=db.DATA_DIR)
    with os.fdopen(fd, "wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    try:
        await run_in_threadpool(backup.restore, tmp)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    settings._load()
    settings.init()
    return {"ok": True}


# ---------- Kundenbestellung (Bestellformular) ----------

def _bestellung_pdf(oid):
    with db.conn() as c:
        o, k = _order_ctx(c, oid)
        items = db.rows(c.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY sort, id", (oid,)))
        r = c.execute("SELECT nr FROM documents WHERE order_id=? AND typ='rechnung' AND status!='storniert'"
                      " ORDER BY id DESC LIMIT 1", (oid,)).fetchone()
    return o, bestellung.render(o, k, items, r["nr"] if r else None)


@app.get("/api/orders/{oid}/bestellung.pdf")
def bestellung_pdf(oid: int, download: int = 0):
    o, data = _bestellung_pdf(oid)
    name = f"Kundenbestellung {storage.safe_name(o['nr'], 40)}.pdf"
    from urllib.parse import quote
    disp = ("attachment" if download else "inline") + f"; filename*=UTF-8''{quote(name)}"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": disp,
                                                                 "Cache-Control": "no-store"})


@app.post("/api/orders/{oid}/bestellung/to-folder")
def bestellung_to_folder(oid: int):
    o, data = _bestellung_pdf(oid)
    try:
        rel0 = _ensure_folder(oid)
        name = f"Kundenbestellung {storage.safe_name(o['nr'], 40)}.pdf"
        storage.FS("auftraege").write_bytes("/".join(storage.clean_rel(rel0) + [name]), data)
        return {"ok": True, "name": name}
    except storage.StorageError as e:
        raise HTTPException(400, str(e))


@app.get("/api/vorlage/bestellformular.pdf")
def bestellformular_leer():
    return Response(bestellung.render(), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="Bestellformular.pdf"', "Cache-Control": "no-store"})


# ---------- Home Assistant: Druck-Eingang ----------

@app.post("/api/ha/sync")
def ha_sync():
    try:
        ha._cfg()
    except ha.HAError as e:
        raise HTTPException(400, str(e))
    r = ha.sync()
    return {**r, "settings": settings.public()}


@app.post("/api/ha/termine")
def ha_termine():
    try:
        ha._cfg()
    except ha.HAError as e:
        raise HTTPException(400, str(e))
    if not ha.termine_aktiv():
        raise HTTPException(400, "Termin-Übertragung ist ausgeschaltet oder keine Liste (todo.…) eingetragen.")
    r = ha.sync_termine()
    return {**r, "settings": settings.public()}


@app.post("/api/ha/test")
def ha_test():
    out = []
    try:
        for liste in ha.listen():
            out.append({"liste": liste, "eintraege": len(ha.get_items(liste))})
    except ha.HAError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "listen": out}


class ArtIn(BaseModel):
    ids: List[int]
    art: str


def _job_note(p, art):
    return ("Müll / Ausschuss – " if art == "muell" else "") + ("Fehldruck – " if not p["erfolg"] else "") \
        + "aus Home Assistant"


@app.post("/api/prints/art")
def prints_art(body: ArtIn):
    warn = None
    for pid in body.ids:
        with db.conn() as c:
            p = db.one(c.execute("SELECT job_id, erfolg FROM prints WHERE id=?", (pid,)))
            if p and p["job_id"]:
                if body.art not in ("gewerbe", "muell"):
                    raise HTTPException(400, "Ein Druck ist einem Auftrag zugeordnet – erst die Zuordnung lösen.")
                # Müll ↔ Gewerbe: Vermerk in der Auftragszeile mitziehen
                c.execute("UPDATE order_jobs SET notizen=? WHERE id=?", (_job_note(p, body.art), p["job_id"]))
        try:
            w = ha.set_art(pid, body.art, push=not warn)
        except ValueError as e:
            raise HTTPException(400, str(e))
        warn = warn or w
    return {"ok": True, "warning": f"Rückmeldung an Home Assistant folgt später: {warn}" if warn else None}


class AssignIn(BaseModel):
    ids: List[int]
    order_id: int
    material_id: Optional[int] = None
    stueck: Optional[float] = None
    bezeichnung: Optional[str] = None


@app.post("/api/prints/assign")
def prints_assign(body: AssignIn):
    warn = None
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM orders WHERE id=?", (body.order_id,)).fetchone():
            raise HTTPException(404, "Auftrag nicht gefunden")
        mat = db.one(c.execute("SELECT * FROM materials WHERE id=?", (body.material_id,))) if body.material_id else None
    single = len(body.ids) == 1
    for pid in body.ids:
        with db.conn() as c:
            p = db.one(c.execute("SELECT * FROM prints WHERE id=?", (pid,)))
            if not p:
                continue
            if p["job_id"]:
                raise HTTPException(400, "Ein Druck ist schon einem Auftrag zugeordnet: " + (p["name"] or ""))
            menge = 0
            if mat:
                menge = (p["gramm"] or 0) if mat["einheit"] == "kg" else 1
            job = {"order_id": body.order_id, "machine_id": p["machine_id"], "material_id": body.material_id,
                   "bezeichnung": body.bezeichnung if single and body.bezeichnung else p["name"],
                   "datum": p["datum"], "dauer_h": p["dauer_h"] or 0, "menge": menge,
                   "stueck": body.stueck if single else None, "kwh": p["kwh"],
                   "notizen": _job_note(p, p["art"])}
            cols = list(job)
            cur = c.execute(f"INSERT INTO order_jobs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                            [job[k] for k in cols])
            _stock(c, job, -1)
            c.execute("UPDATE prints SET order_id=?, job_id=? WHERE id=?", (body.order_id, cur.lastrowid, pid))
        if p["art"] not in ("gewerbe", "muell"):  # Müll bleibt Müll, wird aber dem Auftrag angerechnet
            warn = ha.set_art(pid, "gewerbe", push=not warn) or warn
    return {"ok": True, "warning": f"Rückmeldung an Home Assistant folgt später: {warn}" if warn else None}


@app.post("/api/prints/{pid}/unassign")
def prints_unassign(pid: int):
    with db.conn() as c:
        p = db.one(c.execute("SELECT * FROM prints WHERE id=?", (pid,)))
        if not p:
            raise HTTPException(404)
        if p["job_id"]:
            job = db.one(c.execute("SELECT * FROM order_jobs WHERE id=?", (p["job_id"],)))
            if job:
                _stock(c, job, +1)
                c.execute("DELETE FROM order_jobs WHERE id=?", (p["job_id"],))
        c.execute("UPDATE prints SET order_id=NULL, job_id=NULL WHERE id=?", (pid,))
    return {"ok": True}
