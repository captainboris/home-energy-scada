#!/usr/bin/env bash
set -euo pipefail

VERSION="0.5.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/release-v${VERSION}"
STAGE="${OUT}/home-energy-scada-v${VERSION}-fast-telemetry"

# Keep the cleanup target fixed and reviewable; this script intentionally does
# not accept an arbitrary output directory.
if [[ "${OUT}" != "${ROOT}/release-v${VERSION}" ]]; then
  echo "Refusing unexpected release output path" >&2
  exit 2
fi
rm -rf -- "${OUT}"
mkdir -p "${STAGE}/source" "${STAGE}/deployment" \
  "${STAGE}/infrastructure" "${STAGE}/docs" "${STAGE}/tests"

cp "${ROOT}/README-v${VERSION}.md" "${STAGE}/README.md"
cp "${ROOT}/SOURCE-NOTES-v${VERSION}.md" "${STAGE}/source/README.md"
cp "${ROOT}/docs/"*.md "${STAGE}/docs/"
cp "${ROOT}/infrastructure-fast-telemetry/template.yaml" \
  "${STAGE}/infrastructure/template.yaml"

for file in index.py web_index.py lambda_function.py telemetry_storage.py analytics.py \
  storage.py common.py collector.py index.html app.js daily.html daily.js \
  shared.js shared.css infrastructure.yaml; do
  cp "${ROOT}/${file}" "${STAGE}/source/${file}"
done
cp -a "${ROOT}/lightsail-collector" "${STAGE}/source/"
cp -a "${ROOT}/infrastructure-fast-telemetry" "${STAGE}/source/"
cp -a "${ROOT}/scripts" "${STAGE}/source/"
find "${STAGE}/source" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}/source" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

cp "${ROOT}/test_backend.py" "${ROOT}/test_fast_telemetry.py" \
  "${STAGE}/tests/"
cp "${ROOT}/TEST-RESULTS-v${VERSION}.md" "${STAGE}/tests/TEST-RESULTS.md"
mkdir -p "${STAGE}/tests/collector"
cp -a "${ROOT}/lightsail-collector/tests/." "${STAGE}/tests/collector/"
find "${STAGE}/tests" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}/tests" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

api_stage="$(mktemp -d)"
front_stage="$(mktemp -d)"
collector_stage="$(mktemp -d)"
trap 'rm -rf -- "${api_stage}" "${front_stage}" "${collector_stage}"' EXIT

cp "${ROOT}/web_index.py" "${api_stage}/index.py"
cp "${ROOT}/lambda_function.py" "${ROOT}/telemetry_storage.py" "${ROOT}/analytics.py" \
  "${ROOT}/storage.py" "${ROOT}/common.py" "${api_stage}/"
cp "${ROOT}/index.html" "${ROOT}/app.js" "${ROOT}/daily.html" \
  "${ROOT}/daily.js" "${ROOT}/shared.js" "${ROOT}/shared.css" \
  "${front_stage}/"
cp -a "${ROOT}/lightsail-collector/app" \
  "${ROOT}/lightsail-collector/scripts" \
  "${ROOT}/lightsail-collector/systemd" "${collector_stage}/"
cp "${ROOT}/lightsail-collector/README.md" \
  "${ROOT}/lightsail-collector/requirements.txt" \
  "${ROOT}/lightsail-collector/.env.example" "${collector_stage}/"
find "${collector_stage}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${collector_stage}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

(cd "${api_stage}" && zip -q -X -r \
  "${STAGE}/deployment/home-energy-web-v${VERSION}.zip" .)
(cd "${front_stage}" && zip -q -X -r \
  "${STAGE}/deployment/home-energy-frontend-v${VERSION}.zip" .)
(cd "${collector_stage}" && zip -q -X -r \
  "${STAGE}/deployment/home-energy-ws-collector-v${VERSION}.zip" .)

(
  cd "${STAGE}"
  find deployment infrastructure -type f -print0 | sort -z | \
    xargs -0 sha256sum > "SHA256SUMS-v${VERSION}.txt"
)

(cd "${OUT}" && zip -q -X -r \
  "${OUT}/home-energy-scada-v${VERSION}-fast-telemetry.zip" \
  "$(basename "${STAGE}")")

echo "${OUT}/home-energy-scada-v${VERSION}-fast-telemetry.zip"
