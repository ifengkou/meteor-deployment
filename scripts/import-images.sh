#!/bin/sh
set -eu

bundle_dir=${1:-.}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
sh "$script_dir/verify-bundle.sh" "$bundle_dir"
# Current export has one reviewed archive; never load unlisted leftovers.
docker load --input "$bundle_dir/images/full-stack.tar"
python3 "$script_dir/license_artifacts.py" --verify-imported "$bundle_dir"
echo "images imported; immutable IDs and platform match manifest.json"
