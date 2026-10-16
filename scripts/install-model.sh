#!/bin/sh
set -eu

[ "$#" -eq 2 ] || { echo "usage: $0 MODEL_ARCHIVE TARGET_DIRECTORY" >&2; exit 2; }
archive=$1
target=$2
[ -f "$archive" ] || { echo "model archive not found: $archive" >&2; exit 1; }
[ ! -e "$target" ] || { echo "target already exists: $target" >&2; exit 1; }

parent=$(dirname "$target")
mkdir -p "$parent"
stage=$(mktemp -d "$parent/.embedding-stage.XXXXXX")
trap 'rm -rf "$stage"' EXIT INT TERM
case "$archive" in
  *.tar.zst) tar --zstd -xf "$archive" -C "$stage" ;;
  *.tar.gz|*.tgz) tar -xzf "$archive" -C "$stage" ;;
  *.tar) tar -xf "$archive" -C "$stage" ;;
  *) echo "unsupported model archive: $archive" >&2; exit 1 ;;
esac
manifest_path=$(find "$stage" -name model-manifest.json -type f -print -quit)
[ -n "$manifest_path" ] || { echo "model-manifest.json missing" >&2; exit 1; }
model_root=$(dirname "$manifest_path")
[ -f "$model_root/SHA256SUMS" ] || {
  echo "model-manifest.json or SHA256SUMS missing" >&2; exit 1;
}
(cd "$model_root" && sha256sum -c SHA256SUMS)
mv "$model_root" "$target"
chmod -R a-w "$target"
trap - EXIT INT TERM
rm -rf "$stage"
echo "model installed at $target"
