#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_path="$project_root/web/public/vendor/live2dcubismcore.min.js"
download_url="https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
temporary_path="$(mktemp)"
trap 'rm -f "$temporary_path"' EXIT

mkdir -p "$(dirname "$output_path")"
if ! curl --fail --location --silent --show-error --connect-timeout 10 --max-time 120 \
  "$download_url" --output "$temporary_path"; then
  curl --fail --location --silent --show-error --connect-timeout 10 --max-time 120 \
    --proxy http://127.0.0.1:7897 "$download_url" --output "$temporary_path"
fi

if ! grep -q 'Cubism Core' "$temporary_path"; then
  printf 'Downloaded file does not look like the Live2D Cubism Core runtime.\n' >&2
  exit 1
fi

mv "$temporary_path" "$output_path"
printf 'Cubism Core installed at %s\n' "$output_path"
