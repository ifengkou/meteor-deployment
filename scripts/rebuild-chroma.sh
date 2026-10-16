#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
deployment_dir=$(dirname "$script_dir")
exec python3 "$deployment_dir/scripts/local-stack.py" compose \
  exec -T ai-runtime python /app/tools/rebuild_chroma.py "$@"
