#!/bin/sh
set -eu
[ "$#" -eq 2 ] || { echo "usage: $0 GRADLE_8_14_WRAPPER_DIRECTORY MODULES_2_DIRECTORY" >&2; exit 2; }
wrapper_dir=$1
modules_dir=$2
[ -f "$wrapper_dir/gradle-8.14/bin/gradle" ] && [ -f "$wrapper_dir/gradle-8.14-bin.zip.ok" ] || {
  echo "expected a previously validated Gradle 8.14 wrapper distribution" >&2; exit 1;
}
[ -d "$modules_dir/files-2.1" ] || { echo "expected a modules-2 dependency directory" >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
deployment_dir=$(dirname "$script_dir")
builder=${GRADLE_CACHE_BUILDER:-${M6_BUILDER_NAME:-m6-amd64-builder}}
docker buildx inspect "$builder" >/dev/null
seed_nonce=$(date +%s)
docker buildx build --builder "$builder" --platform linux/amd64 --progress=plain \
  --output type=cacheonly --build-arg "CACHE_SEED_NONCE=$seed_nonce" \
  --build-context "gradle-wrapper-cache=$wrapper_dir" \
  --build-context "gradle-module-cache=$modules_dir" \
  --file "$deployment_dir/buildkit/seed-gradle-cache.Dockerfile" "$deployment_dir/buildkit"
echo "Gradle distribution/dependency cache seeded; no image was loaded."
