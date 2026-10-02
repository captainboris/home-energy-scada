#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sudo "${SOURCE_DIR}/scripts/install.sh"
sudo systemctl restart home-energy-ws-collector.service
sudo systemctl --no-pager --full status home-energy-ws-collector.service

