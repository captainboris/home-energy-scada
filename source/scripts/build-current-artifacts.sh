#!/usr/bin/env bash
set -euo pipefail

version="0.6.2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/../.." && pwd)"
source_root="$project_root/source"
frontend_dist="$source_root/frontend-react/dist"
artifact_root="$project_root/artifacts/v$version"
release_tmp="$(mktemp -d "${TMPDIR:-/tmp}/home-energy-current.XXXXXX")"

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

mkdir -p "$artifact_root" "$release_tmp/web" "$release_tmp/frontend"

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

# Fixed timestamps plus stripped ZIP extra fields make rebuilds byte-stable.
TZ=UTC find "$release_tmp/web" "$release_tmp/frontend" \
  -exec touch -t 202610020000 {} +

web_zip="$artifact_root/home-energy-web-v$version.zip"
frontend_zip="$artifact_root/home-energy-frontend-v$version.zip"
web_tmp="$release_tmp/home-energy-web-v$version.zip"
frontend_tmp="$release_tmp/home-energy-frontend-v$version.zip"

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
  cd "$artifact_root"
  sha256sum \
    "$(basename "$web_zip")" \
    "$(basename "$frontend_zip")" \
    > "SHA256SUMS-v$version.txt"
)

echo "Built current artifacts in $artifact_root"
