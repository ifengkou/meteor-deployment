#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
ai_root="$repo_root/ai-runtime-service"
[ -f "$ai_root/pyproject.toml" ] || { echo "source checkout required; use docker load for exported bundles" >&2; exit 1; }
python_image=${PYTHON_IMAGE:-python:3.12.14-slim-bookworm}
target=${1:-$ai_root/wheelhouse}
mkdir -p "$target"
target=$(CDPATH= cd -- "$target" && pwd -P)

uv --directory "$ai_root" export --locked --no-dev --no-emit-project \
  --format requirements.txt --output-file "$target/requirements-linux.txt"
docker run --rm \
  --mount "type=bind,src=$target,dst=/wheelhouse" \
  --workdir /wheelhouse "$python_image" \
  python -m pip download --require-hashes --only-binary=:all: \
  --find-links /wheelhouse --extra-index-url https://download.pytorch.org/whl/cpu \
  --dest /wheelhouse --requirement /wheelhouse/requirements-linux.txt
if find "$target" -type f | grep -Eiq '/(nvidia|cuda|triton)[^/]*\.(whl|tar\.gz)$'; then
  echo "GPU/CUDA dependency detected in wheelhouse" >&2; exit 1
fi
echo "CPU-only Linux wheelhouse prepared: $target"
