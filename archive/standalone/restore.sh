#!/bin/sh
set -eu

[ "$#" -ge 2 ] && [ "$1" = --confirm ] || {
  echo "usage: $0 --confirm BACKUP_DIRECTORY [ai|metor]" >&2; exit 2;
}
backup_dir=$2
mode=${3:-ai}
(cd "$backup_dir" && sha256sum -c SHA256SUMS)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
deployment_dir=$(dirname "$script_dir")
# Legacy offline bundles keep scripts/ next to deployment/.
[ -f "$deployment_dir/compose.ai.yaml" ] || deployment_dir="$deployment_dir/deployment"
env_file=${ENV_FILE:-$deployment_dir/.env}
compose="docker compose --env-file $env_file -f $deployment_dir/compose.ai.yaml"
[ -z "${AI_COMPOSE_OVERLAY:-}" ] || compose="$compose -f $AI_COMPOSE_OVERLAY"
[ "$mode" = metor ] && compose="$compose -f $deployment_dir/compose.metor.yaml"
set -a; . "$env_file"; set +a
$compose stop ai-runtime
[ "$mode" = metor ] && $compose stop metor || true
$compose run --rm --no-deps --entrypoint sh ai-runtime -c \
  'find /data/ai/documents -mindepth 1 -delete; find /data/ai/chroma -mindepth 1 -delete'
# Extract as the runtime user. docker cp would create root-owned SQLite/index files.
COPYFILE_DISABLE=1 tar --exclude='._*' -C "$backup_dir/documents" -cf - . | \
  $compose run --rm -T --no-deps --entrypoint tar ai-runtime \
    --no-same-owner -C /data/ai/documents -xf -
COPYFILE_DISABLE=1 tar --exclude='._*' -C "$backup_dir/chroma" -cf - . | \
  $compose run --rm -T --no-deps --entrypoint tar ai-runtime \
    --no-same-owner -C /data/ai/chroma -xf -
$compose exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql mysql -uroot metor_ai < "$backup_dir/metor_ai.sql"
$compose up -d ai-migrate
$compose up -d ai-runtime
[ "$mode" = metor ] && $compose up -d metor || true
echo "restore completed; verify readiness and retrieval before reopening traffic"
