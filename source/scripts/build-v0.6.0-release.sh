#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/../.." && pwd)"
source_root="$project_root/source"
frontend_dist="$source_root/frontend-react/dist"
deployment_root="$project_root/deployment"
release_tmp="$(mktemp -d "${TMPDIR:-/tmp}/home-energy-v060.XXXXXX")"

cleanup() {
  find "$release_tmp" -depth -mindepth 1 -delete
  rmdir "$release_tmp"
}
trap cleanup EXIT

required_frontend=(index.html daily.html shared.js shared.css assets)
for item in "${required_frontend[@]}"; do
  if [[ ! -e "$frontend_dist/$item" ]]; then
    echo "Missing frontend build output: $frontend_dist/$item" >&2
    echo "Run: cd source/frontend-react && npm ci && npm run build" >&2
    exit 1
  fi
done

mkdir -p "$deployment_root" "$release_tmp/web" "$release_tmp/frontend"

web_files=(
  lambda_function.py
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

# Fixed archive timestamps and stripped extra fields make repeated builds stable.
TZ=UTC find "$release_tmp/web" "$release_tmp/frontend" -exec touch -t 202610010000 {} +

web_zip="$deployment_root/home-energy-web-v0.6.0.zip"
frontend_zip="$deployment_root/home-energy-frontend-v0.6.0.zip"
web_zip_tmp="$release_tmp/home-energy-web-v0.6.0.zip"
frontend_zip_tmp="$release_tmp/home-energy-frontend-v0.6.0.zip"

(
  cd "$release_tmp/web"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$web_zip_tmp" -@
)
(
  cd "$release_tmp/frontend"
  find . -type f -print | LC_ALL=C sort | zip -X -q "$frontend_zip_tmp" -@
)

unzip -tq "$web_zip_tmp"
unzip -tq "$frontend_zip_tmp"
mv "$web_zip_tmp" "$web_zip"
mv "$frontend_zip_tmp" "$frontend_zip"

(
  cd "$project_root"
  sha256sum \
    deployment/home-energy-web-v0.6.0.zip \
    deployment/home-energy-frontend-v0.6.0.zip \
    rollback/home-energy-web-v0.5.0.zip \
    rollback/home-energy-frontend-v0.5.0.zip \
    > SHA256SUMS-v0.6.0.txt
)

echo "Built:"
echo "  $web_zip"
echo "  $frontend_zip"
echo "  $project_root/SHA256SUMS-v0.6.0.txt"
