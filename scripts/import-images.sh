#!/bin/sh
set -eu

bundle_dir=${1:-.}
found=0
for archive in "$bundle_dir"/images/*.tar; do
  [ -f "$archive" ] || continue
  found=1
  docker load --input "$archive"
done
[ "$found" -eq 1 ] || { echo "no image archive found" >&2; exit 1; }
echo "images imported; compare RepoDigests with manifest.json before startup"
