#!/usr/bin/env bash
# Source from the active builders. Dependencies go only into the Web ZIP.
web_arch="${WEB_ARCH:-aarch64}"
case "$web_arch" in
  aarch64|x86_64) ;;
  *) echo 'WEB_ARCH must be aarch64 (production template) or x86_64 (local/CI)' >&2; exit 1 ;;
esac
"${PYTHON:-python3}" -m pip install --disable-pip-version-check --no-compile --only-binary=:all: \
  --platform "manylinux_2_34_$web_arch" --platform "manylinux_2_28_$web_arch" --platform "manylinux2014_$web_arch" \
  --implementation cp --python-version 3.12 --abi cp312 --abi abi3 \
  --target "$release_tmp/web" -r "$source_root/requirements-web.txt"
# Fail closed: inspect ELF machine type, not the filename/wheel label.
if [[ "$web_arch" == aarch64 ]]; then expected_machine='ARM aarch64'; else expected_machine='x86-64'; fi
while IFS= read -r native; do
  if ! file -b "$native" | grep -qF "$expected_machine"; then
    echo "Native dependency architecture mismatch: $native" >&2; exit 1
  fi
done < <(find "$release_tmp/web" -name '*.so' -print)
