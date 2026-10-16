#!/usr/bin/env bash
set -euo pipefail

version=${1:-0.1.0}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
ai_root="$repo_root/ai-runtime-service"
[ -f "$ai_root/pyproject.toml" ] || { echo "source checkout required; import prebuilt images for exported bundles" >&2; exit 1; }
builder=${M6_BUILDER_NAME:-m6-amd64-builder}
output_dir=${M6_IMAGE_OUTPUT_DIR:-$repo_root/dist/m6-amd64-images-$version}
dockerhub_mirror=${M6_DOCKERHUB_MIRROR:-}
mkdir -p "$output_dir"
components=${M6_BUILD_COMPONENTS:-"ai metor mysql"}
config=""
mysql_context=""
cleanup() {
  [ -z "$config" ] || rm -f "$config"
  [ -z "$mysql_context" ] || rm -f "$mysql_context/Dockerfile"
  [ -z "$mysql_context" ] || rmdir "$mysql_context" 2>/dev/null || true
}
trap cleanup EXIT

build_archive() {
  local component=$1 archive=$2 tag=$3 context=$4
  docker buildx build --builder "$builder" --platform linux/amd64 --pull \
    --progress=plain --provenance=false \
    --metadata-file "$output_dir/$component.build-metadata.json" \
    --output "type=docker,dest=$archive.partial" \
    --build-arg "GRADLE_OFFLINE=${M6_GRADLE_OFFLINE:-0}" \
    --tag "$tag" "$context" 2>&1 | tee "$output_dir/$component.build.log"
  python3 "$script_dir/inspect-docker-archive.py" "$archive.partial"
  mv "$archive.partial" "$archive"
}

if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
  if [ -z "$dockerhub_mirror" ]; then
    dockerhub_mirror=$(docker info --format '{{json .RegistryConfig.Mirrors}}' | \
      python3 -c 'import json,sys; mirrors=json.load(sys.stdin) or []; print(mirrors[0] if mirrors else "")')
  fi
  config=$(mktemp)
  if [ -n "$dockerhub_mirror" ]; then
    mirror_json=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$dockerhub_mirror")
  cat > "$config" <<EOF
[registry."docker.io"]
  mirrors = [$mirror_json]
EOF
  fi
  docker buildx create --name "$builder" --driver docker-container \
    --buildkitd-config "$config"
fi
docker buildx inspect "$builder" --bootstrap

ai_archive="$output_dir/ai-runtime-service_${version}_linux-amd64.tar"
metor_archive="$output_dir/metor-service_${version}_linux-amd64.tar"
mysql_archive="$output_dir/mysql_8.4_linux-amd64.tar"

for component in $components; do
  case "$component" in
    ai) build_archive ai "$ai_archive" "ai-runtime-service:$version" "$repo_root/ai-runtime-service" ;;
    metor) build_archive metor "$metor_archive" "metor-service:$version" "$repo_root/metor-service" ;;
    mysql)
      mysql_context=$(mktemp -d)
      printf 'FROM mysql:8.4\n' > "$mysql_context/Dockerfile"
      build_archive mysql "$mysql_archive" mysql:8.4 "$mysql_context"
      rm -f "$mysql_context/Dockerfile"
      ;;
    *) echo "unsupported component: $component" >&2; exit 2 ;;
  esac
done

complete=1
for archive in "$ai_archive" "$metor_archive" "$mysql_archive"; do
  if [ -f "$archive" ]; then
    python3 "$script_dir/inspect-docker-archive.py" "$archive" \
      --expect-os linux --expect-architecture amd64 | tee "$archive.inspection.json"
  else
    complete=0
  fi
done

if [ "$complete" = 1 ]; then
  (cd "$output_dir" && shasum -a 256 \
    "ai-runtime-service_${version}_linux-amd64.tar" \
    "metor-service_${version}_linux-amd64.tar" "mysql_8.4_linux-amd64.tar" > SHA256SUMS)
  echo "All three AMD64 archives are present and verified: $output_dir"
else
  echo "Selected components completed; other archives are still missing: $output_dir"
fi
echo "Runtime validation is intentionally deferred until an AMD64 Linux host is available."
