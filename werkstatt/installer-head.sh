#!/usr/bin/env bash
# =====================================================================
#  Werkstatt (TK Dekowerkstatt) – Installer für Proxmox VE
#  Aufruf in der Proxmox-Shell:   bash werkstatt-installer.sh
#  Legt einen eigenen Container (LXC) an und installiert alles darin.
#  Erneut ausführen = Update (Daten bleiben erhalten).
# =====================================================================
set -Eeuo pipefail

APP_VERSION="1.4.0"
APP_PORT=8099
LOG=/tmp/werkstatt-install.log
SELF="$(readlink -f "$0")"
TAG="werkstatt"
: > "$LOG"

if [ -t 1 ]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[1m'; N=$'\e[0m'; else G=; Y=; R=; B=; N=; fi
step() { echo -e "${Y}➜${N} $*"; echo "== $*" >>"$LOG"; }
ok()   { echo -e "  ${G}✔${N} $*"; }
fail() {
  echo -e "\n${R}${B}✖ Fehler:${N} $*"
  echo -e "  Details stehen in ${B}$LOG${N} (letzte Zeilen):"
  tail -n 15 "$LOG" | sed 's/^/    /'
  exit 1
}
trap 'fail "Abbruch in Zeile $LINENO (Befehl: $BASH_COMMAND)"' ERR
run() { "$@" >>"$LOG" 2>&1; }

TITLE="Werkstatt $APP_VERSION – Installer"
WT_BTN=(--ok-button "OK" --cancel-button "Abbrechen")
ask_yesno() { whiptail --title "$TITLE" --yes-button "Ja" --no-button "Nein" --yesno "$1" "${2:-12}" 72; }
ask_input() { whiptail --title "$TITLE" "${WT_BTN[@]}" --inputbox "$1" 10 72 "$2" 3>&1 1>&2 2>&3; }
info()      { whiptail --title "$TITLE" --ok-button "OK" --msgbox "$1" "${2:-12}" 72; }

# ---------- Voraussetzungen ----------
[ "$(id -u)" -eq 0 ] || fail "Bitte als root in der Proxmox-Shell ausführen."
command -v pct >/dev/null || fail "Das hier ist kein Proxmox-Host (Befehl 'pct' fehlt). Bitte in der Shell des Proxmox-Servers ausführen."
command -v whiptail >/dev/null || { apt-get install -y whiptail >>"$LOG" 2>&1 || fail "whiptail fehlt"; }
grep -q '^__PAYLOAD_BELOW__$' "$SELF" || fail "Installer-Datei ist unvollständig – bitte neu herunterladen."

extract_payload() {
  local out=$1
  sed -n '/^__PAYLOAD_BELOW__$/,$p' "$SELF" | tail -n +2 | tr -d '\r' | base64 -d > "$out" \
    || fail "Installer-Datei ist beschädigt – bitte neu herunterladen (Datei nicht in einem Editor öffnen/speichern)."
  tar tzf "$out" >/dev/null 2>&1 || fail "Installer-Datei ist beschädigt – bitte neu herunterladen."
}

ct_ip() { pct exec "$1" -- hostname -I 2>/dev/null | awk '{print $1}'; }

wait_network() {
  local id=$1
  for _ in $(seq 1 60); do
    if pct exec "$id" -- getent hosts deb.debian.org >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  fail "Der Container bekommt keine Internetverbindung (DHCP/DNS prüfen)."
}

wait_app() {
  local id=$1
  for _ in $(seq 1 45); do
    if pct exec "$id" -- curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/login" 2>/dev/null; then return 0; fi
    sleep 2
  done
  pct exec "$id" -- journalctl -u werkstatt -n 30 --no-pager >>"$LOG" 2>&1 || true
  fail "Die App startet nicht."
}

install_app() {
  local id=$1 payload
  payload=$(mktemp /tmp/werkstatt-XXXX.tgz)
  extract_payload "$payload"
  step "Kopiere Programm in den Container"
  run pct push "$id" "$payload" /tmp/werkstatt.tgz
  rm -f "$payload"
  run pct exec "$id" -- bash -c '
    set -e
    mkdir -p /opt/werkstatt /var/lib/werkstatt
    rm -rf /opt/werkstatt/app.new && mkdir /opt/werkstatt/app.new
    tar xzf /tmp/werkstatt.tgz -C /opt/werkstatt/app.new && rm /tmp/werkstatt.tgz
    rm -rf /opt/werkstatt/app && mv /opt/werkstatt/app.new/app /opt/werkstatt/app
    mv /opt/werkstatt/app.new/requirements.txt /opt/werkstatt/ && rm -rf /opt/werkstatt/app.new'
  ok "Programm kopiert"

  run pct exec "$id" -- bash -c 'dpkg -s fonts-dejavu-core >/dev/null 2>&1 || { export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq fonts-dejavu-core >/dev/null; }'
  step "Installiere Python-Pakete (dauert 1–3 Minuten)"
  run pct exec "$id" -- bash -c '
    set -e
    [ -x /opt/werkstatt/venv/bin/python ] || python3 -m venv /opt/werkstatt/venv
    /opt/werkstatt/venv/bin/pip install -q --upgrade pip
    /opt/werkstatt/venv/bin/pip install -q -r /opt/werkstatt/requirements.txt'
  ok "Pakete installiert"

  step "Richte Dienst ein"
  run pct exec "$id" -- bash -c "cat > /etc/systemd/system/werkstatt.service <<EOF
[Unit]
Description=Werkstatt (Auftragsverwaltung)
After=network-online.target
Wants=network-online.target

[Service]
Environment=DATA_DIR=/var/lib/werkstatt
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/opt/werkstatt
ExecStart=/opt/werkstatt/venv/bin/hypercorn app.main:app --bind 0.0.0.0:$APP_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable werkstatt >/dev/null 2>&1
systemctl restart werkstatt"
  wait_app "$id"
  ok "Werkstatt läuft"
}

finish() {
  local id=$1 ip
  ip=$(ct_ip "$id")
  info "Fertig! 🛠

Öffne im Browser (PC, Tablet oder Handy):
   http://$ip:$APP_PORT

Container-Nummer: $id
Ein erneuter Start dieses Installers aktualisiert die App –
deine Daten bleiben dabei erhalten." 15
  echo
  echo -e "${G}${B}Fertig!${N}  Öffne ${B}http://$ip:$APP_PORT${N}"
  echo
}

# ---------- Vorhandene Installation? ----------
EXISTING=""
for conf in /etc/pve/lxc/*.conf; do
  [ -e "$conf" ] || continue
  if grep -qE "^tags:.*\b$TAG\b" "$conf"; then EXISTING=$(basename "$conf" .conf); break; fi
done

if [ -n "$EXISTING" ]; then
  CHOICE=$(whiptail --title "$TITLE" "${WT_BTN[@]}" --menu "Es gibt schon eine Installation (Container $EXISTING).\nWas möchtest du tun?" 15 72 3 \
    "update" "Auf Version $APP_VERSION aktualisieren (Daten bleiben)" \
    "neu"    "Zusätzlich eine neue Installation anlegen" \
    "ende"   "Abbrechen" 3>&1 1>&2 2>&3) || exit 0
  case "$CHOICE" in
    update)
      step "Aktualisiere Container $EXISTING"
      [ "$(pct status "$EXISTING" | awk '{print $2}')" = "running" ] || run pct start "$EXISTING"
      wait_network "$EXISTING"
      run pct exec "$EXISTING" -- systemctl stop werkstatt || true
      step "Sichere Datenbank"
      run pct exec "$EXISTING" -- bash -c 'f=/var/lib/werkstatt/werkstatt.db; [ -f "$f" ] && cp -a "$f" "$f.vor-update-$(date +%Y%m%d-%H%M%S)" || true'
      ok "Sicherung liegt im Container unter /var/lib/werkstatt/"
      install_app "$EXISTING"
      finish "$EXISTING"
      exit 0 ;;
    ende) exit 0 ;;
  esac
fi

# ---------- Neue Installation ----------
info "Willkommen! 🛠

Dieser Installer legt auf deinem Proxmox einen eigenen
Container für die Werkstatt-Verwaltung an (Kunden, Aufträge,
Kalkulation, Rechnungen, Maschinen) und richtet alles
automatisch ein.

Firmendaten, Netzlaufwerk und Backup stellst du danach
bequem im Browser unter ⚙ Einstellungen ein." 16

CTID=$(pvesh get /cluster/nextid)
HOSTNAME="werkstatt"
CORES=1
RAM=1024
DISK=10
BRIDGE="vmbr0"
NET="dhcp"
GW=""

# Speicher für den Container: bevorzugt local-lvm, sonst erster passender
mapfile -t STORES < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')
[ ${#STORES[@]} -gt 0 ] || fail "Kein Speicher für Container gefunden."
STORAGE="${STORES[0]}"
for s in "${STORES[@]}"; do [ "$s" = "local-lvm" ] && STORAGE="local-lvm"; done
if [ ! -d /sys/class/net/vmbr0 ]; then
  for b in /sys/class/net/vmbr*; do [ -e "$b" ] && { BRIDGE=$(basename "$b"); break; }; done
fi

if ! ask_yesno "Mit Standard-Einstellungen installieren?

  Container-Nummer:  $CTID
  Name:              $HOSTNAME
  Speicherort:       $STORAGE  ($DISK GB)
  CPU / RAM:         $CORES Kern / $RAM MB
  Netzwerk:          $BRIDGE, IP automatisch (DHCP)

„Ja“ empfohlen. „Nein“ = selbst einstellen." 17; then
  CTID=$(ask_input "Container-Nummer:" "$CTID") || exit 0
  HOSTNAME=$(ask_input "Name des Containers:" "$HOSTNAME") || exit 0
  if [ ${#STORES[@]} -gt 1 ]; then
    MENU=(); for s in "${STORES[@]}"; do MENU+=("$s" ""); done
    STORAGE=$(whiptail --title "$TITLE" "${WT_BTN[@]}" --menu "Speicherort für den Container:" 15 72 6 "${MENU[@]}" 3>&1 1>&2 2>&3) || exit 0
  fi
  DISK=$(ask_input "Festplattengröße in GB:" "$DISK") || exit 0
  CORES=$(ask_input "CPU-Kerne:" "$CORES") || exit 0
  RAM=$(ask_input "Arbeitsspeicher in MB:" "$RAM") || exit 0
  BRIDGE=$(ask_input "Netzwerk-Bridge:" "$BRIDGE") || exit 0
  if ask_yesno "IP-Adresse automatisch per DHCP beziehen?

(„Nein“ = feste IP eingeben)" 10; then
    NET="dhcp"
  else
    NET=$(ask_input "Feste IP mit Präfix, z. B. 192.168.178.61/24:" "") || exit 0
    GW=$(ask_input "Gateway (Router), z. B. 192.168.178.1:" "") || exit 0
  fi
fi
pct status "$CTID" >/dev/null 2>&1 && fail "Container-Nummer $CTID ist schon vergeben."

# ---------- Vorlage ----------
step "Lade Debian-Vorlage"
TSTORE=$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')
[ -n "$TSTORE" ] || fail "Kein Speicher für Vorlagen (vztmpl) gefunden – in Proxmox unter Datacenter → Storage bei 'local' den Inhalt 'Container template' aktivieren."
TEMPLATE=$(pveam list "$TSTORE" 2>/dev/null | awk '/debian-12-standard/ {print $1}' | sort -V | tail -n1)
if [ -z "$TEMPLATE" ]; then
  run pveam update || true
  TNAME=$(pveam available --section system 2>/dev/null | awk '/debian-12-standard/ {print $2}' | sort -V | tail -n1)
  [ -n "$TNAME" ] || fail "Debian-12-Vorlage nicht gefunden (Internet am Proxmox-Host?)."
  run pveam download "$TSTORE" "$TNAME"
  TEMPLATE="$TSTORE:vztmpl/$TNAME"
fi
ok "Vorlage: ${TEMPLATE##*/}"

# ---------- Container ----------
step "Lege Container $CTID an"
NETCFG="name=eth0,bridge=$BRIDGE,ip=$NET"
[ -n "$GW" ] && NETCFG="$NETCFG,gw=$GW"
run pct create "$CTID" "$TEMPLATE" \
  --hostname "$HOSTNAME" --cores "$CORES" --memory "$RAM" --swap 256 \
  --rootfs "$STORAGE:$DISK" --net0 "$NETCFG" \
  --unprivileged 1 --features nesting=1 --onboot 1 --tags "$TAG" \
  --description "Werkstatt – Kunden, Aufträge, Kalkulation und Rechnungen. Weboberfläche: Port $APP_PORT."
run pct start "$CTID"
ok "Container läuft"

step "Warte auf Netzwerk"
wait_network "$CTID"
ok "Internet ok"

step "Installiere Grundpakete (dauert 1–3 Minuten)"
run pct exec "$CTID" -- bash -c 'export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
  apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip ca-certificates curl fonts-dejavu-core >/dev/null
  timedatectl set-timezone Europe/Vienna 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Vienna /etc/localtime'
ok "Grundpakete installiert"

install_app "$CTID"
finish "$CTID"
exit 0
__PAYLOAD_BELOW__
