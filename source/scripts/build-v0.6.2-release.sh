#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/../.." && pwd)"
source_root="$project_root/source"
frontend_dist="$source_root/frontend-react/dist"
deployment_root="$project_root/deployment"
rollback_root="$project_root/rollback"
release_tmp="$(mktemp -d "${TMPDIR:-/tmp}/home-energy-v062.XXXXXX")"

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

rollback_files=(
  home-energy-web-v0.6.0.zip
  home-energy-frontend-v0.6.1.zip
)
for file in "${rollback_files[@]}"; do
  if [[ ! -f "$rollback_root/$file" ]]; then
    echo "Missing rollback baseline: $rollback_root/$file" >&2
    exit 1
  fi
done

mkdir -p "$deployment_root" "$release_tmp/web" "$release_tmp/frontend"
web_files=(
  lambda_function.py
  range_analytics.py
  history_service.py
  telemetry_storage.py
  analytics.py
  common.py
  storage.py
)
for file in "${web_files[@]}"; do
  cp "$source_root/$file" "$release_tmp/web/$file"
done
cp "$source_root/web_index.py" "$release_tmp/web/index.py"
cp -a "$frontend_dist/." "$release_tmp/frontend/"

# Fixed timestamps and stripped ZIP extra fields make rebuilds byte-stable.
TZ=UTC find "$release_tmp/web" "$release_tmp/frontend" -exec touch -t 202610020000 {} +

web_zip="$deployment_root/home-energy-web-v0.6.2.zip"
frontend_zip="$deployment_root/home-energy-frontend-v0.6.2.zip"
web_tmp="$release_tmp/home-energy-web-v0.6.2.zip"
frontend_tmp="$release_tmp/home-energy-frontend-v0.6.2.zip"

(
  cd "$release_tmp/web"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$web_tmp" -@
)
(
  cd "$release_tmp/frontend"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$frontend_tmp" -@
)

unzip -tq "$web_tmp"
unzip -tq "$frontend_tmp"
mv "$web_tmp" "$web_zip"
mv "$frontend_tmp" "$frontend_zip"

(
  cd "$project_root"
  sha256sum \
    deployment/home-energy-web-v0.6.2.zip \
    deployment/home-energy-frontend-v0.6.2.zip \
    rollback/home-energy-web-v0.6.0.zip \
    rollback/home-energy-frontend-v0.6.1.zip \
    > SHA256SUMS-v0.6.2.txt
)

echo "Built:"
echo "  $web_zip"
echo "  $frontend_zip"
echo "  $project_root/SHA256SUMS-v0.6.2.txt"
