#!/usr/bin/env bash
set -euo pipefail

if command -v pipx >/dev/null 2>&1; then
  pipx install skillos
else
  python3 -m pip install --user skillos
fi

echo "Installed. Try: skillos --help"
