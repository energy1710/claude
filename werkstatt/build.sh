#!/usr/bin/env bash
# Baut dist/werkstatt-installer.sh aus installer-head.sh + app/ + requirements.txt
set -euo pipefail
cd "$(dirname "$0")"
V_SH=$(sed -n 's/^APP_VERSION="\(.*\)"$/\1/p' installer-head.sh)
V_PY=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' app/main.py)
[ "$V_SH" = "$V_PY" ] || { echo "Version passt nicht: installer-head.sh=$V_SH, app/main.py=$V_PY" >&2; exit 1; }
mkdir -p dist
OUT=dist/werkstatt-installer.sh
{
  cat installer-head.sh
  tar --sort=name --owner=0 --group=0 --numeric-owner --exclude='__pycache__' --exclude='*.pyc' \
      -czf - app requirements.txt | base64 -w 76
} > "$OUT"
chmod +x "$OUT"
bash -n "$OUT"
echo "Fertig: $OUT (Version $V_SH, $(du -h "$OUT" | cut -f1))"
