#!/bin/sh
set -eu

[ "$#" -eq 2 ] || { echo "usage: $0 VERSION MODEL_ARCHIVE" >&2; exit 2; }
version=$1
model_archive=$2
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ai_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
repo_root=$(dirname "$ai_root")
[ -f "$ai_root/pyproject.toml" ] || { echo "source checkout required; use docker load for exported bundles" >&2; exit 1; }
out=${BUNDLE_OUTPUT_DIR:-$repo_root/dist/ai-offline-bundle-$version}
ai_image=${AI_RUNTIME_IMAGE:-ai-runtime-service:$version}
metor_image=${METOR_IMAGE:-metor-service:$version}
mysql_image=${MYSQL_IMAGE:-mysql:8.4}
[ -f "$model_archive" ] || { echo "model archive not found: $model_archive" >&2; exit 1; }
[ -d "$ai_root/wheelhouse" ] || { echo "prepare wheelhouse first" >&2; exit 1; }

mkdir -p "$out/images" "$out/models" "$out/docs/operations" "$out/docs/architecture" "$out/deployment/mysql-init" \
  "$out/wheelhouse/linux-amd64-python312-cpu"
cp "$ai_root/deployment/compose.ai.yaml" "$ai_root/deployment/compose.metor.yaml" \
  "$ai_root/deployment/compose.embedding-models.yaml" \
  "$ai_root/deployment/.env.example" "$ai_root/deployment/README.md" "$out/deployment/"
cp -R "$ai_root/deployment/mysql-init/." "$out/deployment/mysql-init/"
mkdir -p "$out/scripts"
cp "$ai_root/deployment/scripts/"*.sh "$ai_root/deployment/scripts/inspect-docker-archive.py" "$out/scripts/"
cp -R "$ai_root/docs/operations/offline-deployment.md" \
  "$ai_root/docs/operations/backup-restore.md" \
  "$ai_root/docs/operations/troubleshooting.md" \
  "$ai_root/docs/operations/embedding-models.md" "$out/docs/operations/"
mkdir -p "$out/config"
cp "$ai_root/config/embedding-models.example.json" "$out/config/"
cp "$ai_root/docs/architecture/m6-buildx-amd64-build.md" "$out/docs/architecture/"
cp -R "$ai_root/wheelhouse/." "$out/wheelhouse/linux-amd64-python312-cpu/"
cp "$model_archive" "$out/models/"

docker image inspect "$ai_image" "$metor_image" "$mysql_image" >/dev/null
docker save --output "$out/images/ai-runtime_$version.oci.tar" "$ai_image"
docker save --output "$out/images/metor-service_$version.oci.tar" "$metor_image"
docker save --output "$out/images/mysql_8.4.oci.tar" "$mysql_image"

ai_digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$ai_image")
metor_digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$metor_image")
mysql_digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$mysql_image")
lock_sha=$(sha256sum "$ai_root/uv.lock" | awk '{print $1}')
cat > "$out/manifest.json" <<JSON
{"formatVersion":1,"bundleVersion":"$version","createdAt":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","architecture":"linux-amd64","python":"3.12","embeddingRuntime":"pytorch-cpu","uvLockSha256":"$lock_sha","images":{"aiRuntime":"$ai_digest","metor":"$metor_digest","mysql":"$mysql_digest"}}
JSON
(cd "$out" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "offline bundle created: $out"
