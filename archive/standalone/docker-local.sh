#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
config_file=${AI_DOCKER_ENV_FILE:-}
[ -n "$config_file" ] || { echo 'Shared workspace: use tools/dev docker. Standalone AI: explicitly set AI_DOCKER_ENV_FILE.' >&2; exit 1; }
[ -f "$config_file" ] || { echo 'AI_DOCKER_ENV_FILE must point to an existing private standalone configuration.' >&2; exit 1; }
exec docker compose --env-file "$config_file" -f "$project_dir/compose.yaml" "$@"
