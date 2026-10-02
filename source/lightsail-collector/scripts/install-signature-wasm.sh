#!/usr/bin/env bash
set -euo pipefail

SERVICE="home-energy-ws-collector"
DEST="/etc/${SERVICE}/signature.wasm"
PINNED_URL="https://raw.githubusercontent.com/albuslee/foxess-ws-bridge/293331d60fd6db9c95d1f42214cce493ae67d1f4/custom_components/foxess_ws/wasm/signature.wasm"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 2
fi
install -d -m 0750 -o root -g home-energy-ws "/etc/${SERVICE}"
tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT
if [[ -n "${1:-}" ]]; then
  cp -- "${1}" "${tmp_file}"
else
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "${tmp_file}" "${PINNED_URL}"
fi
python3 - "${tmp_file}" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = p.read_bytes()
if len(data) < 1024 or data[:4] != b"\x00asm":
    raise SystemExit("Refusing file: not a plausible WebAssembly module")
print(f"Validated WebAssembly module ({len(data)} bytes)")
PY
install -m 0640 -o root -g home-energy-ws "${tmp_file}" "${DEST}"
echo "Installed ${DEST}. The download URL is pinned to an immutable commit."
