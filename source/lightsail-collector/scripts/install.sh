#!/usr/bin/env bash
set -euo pipefail

VERSION="0.5.0"
SERVICE="home-energy-ws-collector"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="/opt/${SERVICE}"
RELEASE="${BASE}/releases/${VERSION}"
CONFIG_DIR="/etc/${SERVICE}"
START=false

if [[ "${1:-}" == "--start" ]]; then
  START=true
fi
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo $0 [--start]" >&2
  exit 2
fi

if ! id -u home-energy-ws >/dev/null 2>&1; then
  useradd --system --home-dir "/var/lib/${SERVICE}" --create-home \
    --shell /usr/sbin/nologin home-energy-ws
fi
install -d -m 0755 "${BASE}/releases" "${RELEASE}"
# The service account must be able to traverse this directory to read the
# group-readable WASM module and AWS credentials. Individual secrets remain
# 0640 or 0600.
install -d -m 0750 -o root -g home-energy-ws "${CONFIG_DIR}"
cp -a "${SOURCE_DIR}/app" "${SOURCE_DIR}/requirements.txt" "${RELEASE}/"
install -m 0755 "${SOURCE_DIR}/scripts/healthcheck.sh" \
  "${RELEASE}/healthcheck.sh"
python3 -m venv "${RELEASE}/venv"
"${RELEASE}/venv/bin/pip" install --disable-pip-version-check --no-cache-dir \
  -r "${RELEASE}/requirements.txt"
chown -R root:root "${RELEASE}"
chmod -R go-w "${RELEASE}"
ln -sfn "${RELEASE}" "${BASE}/current"

if [[ ! -e "${CONFIG_DIR}/environment" ]]; then
  install -m 0600 -o root -g root "${SOURCE_DIR}/.env.example" \
    "${CONFIG_DIR}/environment"
  echo "Created ${CONFIG_DIR}/environment; replace all placeholders before start."
fi
install -m 0644 "${SOURCE_DIR}/systemd/${SERVICE}.service" \
  "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "${SERVICE}.service"

if [[ ! -r "${CONFIG_DIR}/signature.wasm" ]]; then
  echo "signature.wasm is still required; run scripts/install-signature-wasm.sh."
fi
if ${START}; then
  systemctl restart "${SERVICE}.service"
  systemctl --no-pager --full status "${SERVICE}.service"
else
  echo "Installed ${SERVICE} ${VERSION} without starting it."
  echo "After configuring credentials, run: sudo systemctl start ${SERVICE}"
fi
