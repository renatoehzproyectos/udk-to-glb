#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ $# -lt 1 ]; then
  echo "Usage: ./extract.sh <file.udk> [--all]"
  exit 1
fi
UDK="$1"
shift || true
if [ "${1:-}" = "--all" ]; then
  exec python3 "$DIR/tools/extract_map.py" "$UDK"
else
  exec python3 "$DIR/tools/extract_one_mesh.py" "$UDK"
fi
