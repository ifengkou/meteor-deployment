#!/bin/sh
set -eu

bundle_dir=${1:-.}
cd "$bundle_dir"
for required in manifest.json SHA256SUMS deployment/compose.ai.yaml deployment/scripts/local-stack.py; do
  [ -e "$required" ] || { echo "missing bundle file: $required" >&2; exit 1; }
done
sha256sum -c SHA256SUMS
if find wheelhouse -type f 2>/dev/null | grep -Eiq '/(nvidia|cuda|triton)[^/]*\.(whl|tar\.gz)$'; then
  echo "GPU/CUDA package found in CPU-only wheelhouse" >&2
  exit 1
fi
echo "bundle verification passed"
