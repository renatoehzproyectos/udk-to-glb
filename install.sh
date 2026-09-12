#!/usr/bin/env bash
set -euo pipefail
if command -v pkg >/dev/null 2>&1; then
  pkg install -y python
fi
echo "Ready. $(python3 --version 2>/dev/null || echo 'python3 missing')"
echo "Run: ./extract.sh /path/to/TJBrotherAirDribble.udk"
