#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/../.." && pwd)"
frontend_dist="$project_root/source/frontend-react/dist"
deployment_root="$project_root/deployment"
rollback_root="$project_root/rollback"
release_tmp="$(mktemp -d "${TMPDIR:-/tmp}/home-energy-v061.XXXXXX")"

cleanup() {
  find "$release_tmp" -depth -mindepth 1 -delete
  rmdir "$release_tmp"
}
trap cleanup EXIT

required_frontend=(index.html daily.html shared.js shared.css assets)
for item in "${required_frontend[@]}"; do
  if [[ ! -e "$frontend_dist/$item" ]]; then
    echo "Missing frontend build output: $frontend_dist/$item" >&2
    echo "Run: cd source/frontend-react && npm ci && npm test && npm run build" >&2
    exit 1
  fi
done

rollback_zip="$rollback_root/home-energy-frontend-v0.6.0.zip"
if [[ ! -f "$rollback_zip" ]]; then
  echo "Missing v0.6.0 rollback baseline: $rollback_zip" >&2
  exit 1
fi

mkdir -p "$deployment_root" "$release_tmp/frontend"
cp -a "$frontend_dist/." "$release_tmp/frontend/"

# Fixed archive timestamps and stripped extra fields make repeated builds stable.
TZ=UTC find "$release_tmp/frontend" -exec touch -t 202610010000 {} +

frontend_zip="$deployment_root/home-energy-frontend-v0.6.1.zip"
frontend_zip_tmp="$release_tmp/home-energy-frontend-v0.6.1.zip"
(
  cd "$release_tmp/frontend"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$frontend_zip_tmp" -@
)

unzip -tq "$frontend_zip_tmp"
mv "$frontend_zip_tmp" "$frontend_zip"

(
  cd "$project_root"
  sha256sum \
    deployment/home-energy-frontend-v0.6.1.zip \
    rollback/home-energy-frontend-v0.6.0.zip \
    > SHA256SUMS-v0.6.1.txt
)

echo "Built:"
echo "  $frontend_zip"
echo "  $project_root/SHA256SUMS-v0.6.1.txt"
