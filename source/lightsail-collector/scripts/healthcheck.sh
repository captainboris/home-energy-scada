#!/usr/bin/env bash
set -euo pipefail

SERVICE="home-energy-ws-collector"
systemctl is-active --quiet "${SERVICE}.service"
set -a
# This file is root-owned and contains only deployment configuration.
source "/etc/${SERVICE}/environment"
set +a
cd "/opt/${SERVICE}/current"
exec "/opt/${SERVICE}/current/venv/bin/python" -m app.healthcheck
