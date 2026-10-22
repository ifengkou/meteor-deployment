#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
ai_root="$repo_root/ai-runtime-service"
[ -f "$ai_root/pyproject.toml" ] || { echo "source checkout required; use docker load for exported bundles" >&2; exit 1; }
python_image=${PYTHON_IMAGE:-python:3.12.14-slim-bookworm}
platform=${TARGET_PLATFORM:?set TARGET_PLATFORM to linux/amd64 or linux/arm64}
case "$platform" in linux/amd64|linux/arm64) ;; *) echo "unsupported target platform: $platform" >&2; exit 1 ;; esac
python_version=${TARGET_PYTHON_VERSION:-3.12}
[ "$python_version" = 3.12 ] || { echo "AI lock requires Python 3.12" >&2; exit 1; }
target=${1:-$ai_root/wheelhouse}
mkdir -p "$target"
target=$(CDPATH= cd -- "$target" && pwd -P)

uv --directory "$ai_root" export --locked --no-dev --no-emit-project \
  --format requirements.txt --output-file "$target/requirements-linux.txt"
# uv exports local SDK paths relative to /app, even with a custom output directory.
python3 "$script_dir/prepare-wheelhouse.py" "$ai_root" "$target"
docker run --rm --platform "$platform" \
  --mount "type=bind,src=$target,dst=/app/wheelhouse" \
  --workdir /app "$python_image" \
  sh -eu -c '
    python -c "import sys; assert sys.version_info[:2] == (3, 12)"
    python -m pip download --require-hashes --only-binary=:all: \
      --find-links /app/wheelhouse --extra-index-url https://download.pytorch.org/whl/cpu \
      --dest /app/wheelhouse --requirement /app/wheelhouse/requirements-linux.txt
    python -m pip install --ignore-installed --dry-run --require-hashes --only-binary=:all: \
      --no-index --no-cache-dir --find-links /app/wheelhouse \
      --requirement /app/wheelhouse/requirements-linux.txt
  '
if find "$target" -type f | grep -Eiq '/(nvidia|cuda|triton)[^/]*\.(whl|tar\.gz)$'; then
  echo "GPU/CUDA dependency detected in wheelhouse" >&2; exit 1
fi
python3 "$script_dir/prepare-wheelhouse.py" "$ai_root" "$target" --checksums
echo "CPU-only $platform Python $python_version wheelhouse prepared: $target"
