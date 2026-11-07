"""Einstellungen in der Datenbank (änderbar in der Weboberfläche)."""
import hashlib
import hmac
import secrets
import threading

from . import db

KU_TEXT = {
    "AT": "Umsatzsteuerfrei aufgrund der Kleinunternehmerregelung gemäß § 6 Abs. 1 Z 27 UStG.",
    "DE": "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet (Kleinunternehmerregelung).",
}

DEFAULTS = {
    # Firma / Rechnungsvorlage
    "firma_name": "TK Dekowerkstatt",
    "firma_slogan": "Ideen – Design – mit Liebe zum Detail",
    "firma_inhaber": "",
    "firma_strasse": "",
    "firma_plz_ort": "",
    "firma_land": "AT",
    "firma_tel": "",
    "firma_email": "",
    "firma_web": "",
    "firma_uid": "",
    "firma_steuernr": "",
    "bank_name": "",
    "bank_iban": "",
    "bank_bic": "",
    "kleinunternehmer": "1",
    "kleinunternehmer_text": KU_TEXT["AT"],
    "ust_satz": "20",
    "zahlungsziel_tage": "14",
    "angebot_gueltig_tage": "30",
    "akzentfarbe": "#7d3c98",
    "logo": "",
    "rechnung_einleitung": "Vielen Dank für Ihren Auftrag! Wir erlauben uns, folgende Leistungen in Rechnung zu stellen:",
    "rechnung_schluss": "Bitte überweisen Sie den Betrag von {zahlbetrag} bis {faellig} unter Angabe der Rechnungsnummer {nr} auf das unten angeführte Konto.\n\nVielen Dank und liebe Grüße!",
    "rechnung_schluss_bezahlt": "Der Betrag von {gesamt} wurde dankend erhalten.\n\nVielen Dank für Ihren Einkauf!",
    "angebot_einleitung": "Vielen Dank für Ihre Anfrage! Gerne bieten wir Ihnen folgende Leistungen an:",
    "angebot_schluss": "Dieses Angebot ist gültig bis {gueltig}. Wir freuen uns auf Ihren Auftrag!",
    "fusszeile": "",
    # Kundenbestellung (Bestellformular)
    "bestellung_bestaetigung": "Ich bestätige, dass die oben eingetragenen Angaben, insbesondere Schreibweise, "
                               "Personalisierung, Farbe, Material, Größe und Menge, korrekt sind. Mir ist bekannt, "
                               "dass sich handgefertigte bzw. 3D-gedruckte Produkte geringfügig von Musterbildern "
                               "unterscheiden können.",
    "bestellung_hinweis": "Hinweis: Dieses Formular dokumentiert die Bestellung, ersetzt aber keine vollständige "
                          "Rechnung und keine gesetzlich erforderlichen Verbraucherinformationen. Ein gesetzliches "
                          "Widerrufsrecht kann bestehen, Ausnahmen für individuell angefertigte Waren gelten nur, "
                          "wenn die gesetzlichen Voraussetzungen erfüllt sind.",
    "vertrieb_optionen": "Kreativabend, Online, Markt, Direkt",
    "zahlungsarten": "Bar, Überweisung, PayPal, Sonstiges",
    # Nummernkreise
    "prefix_rechnung": "RE-",
    "prefix_angebot": "AN-",
    "prefix_auftrag": "A-",
    "prefix_kunde": "K-",
    # Kalkulation
    "strompreis": "0.30",
    "aufschlag_pct": "30",
    "ausschuss_pct": "5",
    "rundung": "0.50",
    # Netzlaufwerk (SMB)
    "smb_host": "192.168.178.41",
    "smb_user": "",
    "smb_password": "",
    "smb_auftraege_share": "",
    "smb_auftraege_pfad": "Werkstatt/Auftraege",
    "smb_ordner_auto": "1",
    "smb_ordner_schema": "{jahr}/{nr} {kunde} - {titel}",
    "smb_pdf_kopieren": "1",
    "smb_unc_anzeige": "",
    "lokal_auftraege": "",             # alternativ: lokaler/gemounteter Ordner
    # Backup
    "backup_aktiv": "0",
    "backup_share": "backups",
    "backup_pfad": "Werkstatt",
    "backup_uhrzeit": "02:30",
    "backup_behalten": "30",
    "backup_mit_bildern": "1",
    "backup_letzt": "",
    "backup_letzt_status": "",
    "backup_letzt_datei": "",
    # Home Assistant (Druckprotokolle abholen)
    "ha_aktiv": "0",
    "ha_url": "",
    "ha_token": "",
    "ha_listen": "todo.a1_druckprotokoll, todo.p1s_druckprotokoll, todo.a2l_druckprotokoll, todo.x2d_druckprotokoll",
    "ha_import_ab": "",
    "ha_intervall_min": "3",
    "ha_letzt": "",
    "ha_letzt_status": "",
    # Sonstiges
    "currency": "€",
    "app_password": "",
    "secret": "",
}
HIDDEN = {"secret", "app_password", "smb_password", "ha_token"}
READONLY = {"backup_letzt", "backup_letzt_status", "backup_letzt_datei", "logo", "ha_letzt", "ha_letzt_status"}

_cache = None
_lock = threading.Lock()


def _load():
    global _cache
    with db.conn() as c:
        _cache = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings")}


def get(key):
    if _cache is None:
        _load()
    v = _cache.get(key)
    return v if v is not None else DEFAULTS.get(key, "")


def num(key, default=0.0):
    try:
        return float(str(get(key)).replace(",", "."))
    except (TypeError, ValueError):
        return default


def flag(key):
    return str(get(key)) in ("1", "true", "True", "on")


def set_many(values: dict):
    with _lock, db.conn() as c:
        for k, v in values.items():
            if k in DEFAULTS:
                c.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, "" if v is None else str(v)))
    _load()


def init():
    if not get("secret"):
        set_many({"secret": secrets.token_hex(32)})


def public():
    out = {k: get(k) for k in DEFAULTS if k not in HIDDEN}
    out["password_set"] = bool(get("app_password"))
    out["smb_password_set"] = bool(get("smb_password"))
    out["ha_token_set"] = bool(get("ha_token"))
    return out


def update_from_ui(values: dict):
    upd = {}
    for k, v in values.items():
        if k not in DEFAULTS or k in ("secret", "app_password") or k in READONLY:
            continue
        if k in ("smb_password", "ha_token") and not v:
            continue  # leer = unverändert lassen
        if isinstance(v, bool):
            v = "1" if v else "0"
        upd[k] = v.strip() if isinstance(v, str) and k != "smb_password" else v
    if upd:
        set_many(upd)


# ---------- Passwort ----------

def set_password(pw):
    if not pw:
        set_many({"app_password": ""})
        return
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    set_many({"app_password": f"{salt}${h}"})


def check_password(pw):
    stored = get("app_password")
    if not stored or "$" not in stored:
        return False
    salt, h = stored.split("$", 1)
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex(), h)


def session_token():
    stored = get("app_password")
    return hmac.new(get("secret").encode(), ("session:" + stored).encode(), "sha256").hexdigest()
