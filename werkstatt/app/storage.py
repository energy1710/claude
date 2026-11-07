"""Zugriff auf das Netzlaufwerk (SMB) oder einen lokalen/gemounteten Ordner.

Zwei Bereiche: 'auftraege' (Auftragsordner) und 'backup' (Datenbank-Sicherungen).
"""
import os
import re
import shutil
import threading

from . import settings

_lock = threading.Lock()
_registered = {}


class StorageError(Exception):
    pass


def clean_rel(path):
    """Relativen Pfad säubern, '..' und Laufwerksangaben verhindern."""
    parts = []
    for p in re.split(r"[\\/]+", path or ""):
        p = p.strip()
        if not p or p == ".":
            continue
        if p == ".." or ":" in p:
            raise StorageError("Ungültiger Pfad")
        parts.append(p)
    return parts


def safe_name(s, maxlen=60):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s or "").strip().rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return s[:maxlen].strip() or "ohne Name"


class FS:
    """Einheitliche Schnittstelle für SMB und lokale Ordner."""

    def __init__(self, area):
        self.area = area
        lokal = settings.get("lokal_auftraege").strip() if area == "auftraege" else ""
        if lokal:
            self.kind = "lokal"
            self.root_parts = []
            self.base = lokal
            self.sep = os.sep
            self.mod = os
            return
        host = settings.get("smb_host").strip().strip("\\/")
        share = settings.get("smb_auftraege_share" if area == "auftraege" else "backup_share").strip().strip("\\/")
        sub = settings.get("smb_auftraege_pfad" if area == "auftraege" else "backup_pfad")
        if not host or not share:
            raise StorageError("Netzlaufwerk ist nicht eingerichtet (Einstellungen → Netzlaufwerk & Backup).")
        try:
            import smbclient  # erst bei Bedarf laden
        except ImportError as e:  # pragma: no cover
            raise StorageError("Python-Paket smbprotocol fehlt") from e
        self.kind = "smb"
        self.mod = smbclient
        self.sep = "\\"
        user, pw = settings.get("smb_user") or None, settings.get("smb_password") or None
        key = (host, user, pw)
        with _lock:
            if _registered.get(host) != key:
                try:
                    smbclient.reset_connection_cache()
                except Exception:
                    pass
                _registered.clear()
                try:
                    smbclient.register_session(host, username=user, password=pw, connection_timeout=10)
                except Exception as e:
                    raise StorageError(f"Verbindung zu {host} fehlgeschlagen: {_msg(e)}") from e
                _registered[host] = key
        self.base = "\\\\" + host + "\\" + share
        self.root_parts = clean_rel(sub)

    # ----- Pfade -----
    def path(self, rel=""):
        parts = self.root_parts + clean_rel(rel)
        return self.sep.join([self.base.rstrip("\\/")] + parts) if parts else self.base

    def unc(self, rel=""):
        """Pfad, wie man ihn am Windows-PC in den Explorer eingibt."""
        rp = clean_rel(rel)
        disp = settings.get("smb_unc_anzeige").strip().rstrip("\\/") if self.area == "auftraege" else ""
        if disp:
            return "\\".join([disp] + rp)
        if self.kind == "lokal":
            return os.path.join(self.base, *rp)
        return "\\".join([self.base] + self.root_parts + rp)

    # ----- Operationen -----
    def _call(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except StorageError:
            raise
        except FileNotFoundError as e:
            raise StorageError("Ordner/Datei nicht gefunden") from e
        except PermissionError as e:
            raise StorageError("Keine Berechtigung") from e
        except Exception as e:
            raise StorageError(_msg(e)) from e

    def makedirs(self, rel=""):
        self._call(self.mod.makedirs, self.path(rel), exist_ok=True)

    def exists(self, rel=""):
        try:
            self.mod.stat(self.path(rel))
            return True
        except Exception:
            return False

    def listdir(self, rel=""):
        def _do():
            out = []
            for e in self.mod.scandir(self.path(rel)):
                if e.name.startswith((".", "~$")) or e.name in ("Thumbs.db", "desktop.ini", "@eaDir", "#recycle"):
                    continue
                try:
                    st = e.stat()
                    is_dir = e.is_dir()
                except Exception:
                    continue
                out.append({"name": e.name, "dir": is_dir, "size": 0 if is_dir else st.st_size,
                            "mtime": int(st.st_mtime)})
            out.sort(key=lambda x: (not x["dir"], x["name"].lower()))
            return out
        return self._call(_do)

    def open(self, rel, mode="rb"):
        if self.kind == "smb":
            return self._call(self.mod.open_file, self.path(rel), mode=mode)
        return self._call(open, self.path(rel), mode)

    def write_bytes(self, rel, data):
        parent = self.sep.join(clean_rel(rel)[:-1])
        self.makedirs(parent)
        with self.open(rel, "wb") as fh:
            fh.write(data)

    def copy_from_local(self, local_path, rel):
        parent = self.sep.join(clean_rel(rel)[:-1])
        self.makedirs(parent)
        with open(local_path, "rb") as src, self.open(rel, "wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)

    def remove(self, rel):
        self._call(self.mod.remove, self.path(rel))

    def rename(self, old, new):
        self._call(self.mod.rename, self.path(old), self.path(new))


def _msg(e):
    s = str(e) or e.__class__.__name__
    if "STATUS_LOGON_FAILURE" in s or "Failed to authenticate" in s:
        return "Benutzername oder Passwort falsch"
    if "STATUS_BAD_NETWORK_NAME" in s:
        return "Freigabe nicht gefunden"
    if "STATUS_ACCESS_DENIED" in s:
        return "Zugriff verweigert"
    if "STATUS_OBJECT_NAME_NOT_FOUND" in s or "STATUS_OBJECT_PATH_NOT_FOUND" in s:
        return "Ordner/Datei nicht gefunden"
    if "timed out" in s.lower() or "Errno 110" in s or "Errno 113" in s:
        return "Netzlaufwerk nicht erreichbar"
    return s[:200]


def order_folder_name(order, customer):
    kunde = ""
    if customer:
        kunde = customer.get("firma") or " ".join(x for x in (customer.get("vorname"), customer.get("nachname")) if x)
    jahr = (order.get("eingang") or order.get("created_at") or "")[:4] or ""
    schema = settings.get("smb_ordner_schema") or "{nr} {kunde} - {titel}"
    parts = []
    for seg in re.split(r"[\\/]+", schema):
        val = seg.format(nr=order.get("nr") or "", kunde=kunde or "ohne Kunde", titel=order.get("titel") or "",
                         jahr=jahr)
        val = re.sub(r"\s*-\s*$", "", val.strip())
        parts.append(safe_name(val, 80))
    return "/".join(p for p in parts if p)
