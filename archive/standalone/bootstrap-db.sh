#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
deployment_dir=$(dirname "$script_dir")
# Legacy offline bundles keep scripts/ next to deployment/.
[ -f "$deployment_dir/compose.ai.yaml" ] || deployment_dir="$deployment_dir/deployment"
env_file=${ENV_FILE:-$deployment_dir/.env}
mode=${1:-ai}
[ -f "$env_file" ] || { echo "missing environment file: $env_file" >&2; exit 1; }
set -a
. "$env_file"
set +a

case "$mode" in ai|metor) ;; *) echo "usage: $0 [ai|metor]" >&2; exit 2 ;; esac
case "${METOR_DATABASE:-}:${METOR_DB_USER:-}" in
  *[!A-Za-z0-9_:]* ) echo "database/user names contain unsupported characters" >&2; exit 1 ;;
esac

compose="docker compose --env-file $env_file -f $deployment_dir/compose.ai.yaml"
[ -z "${AI_COMPOSE_OVERLAY:-}" ] || compose="$compose -f $AI_COMPOSE_OVERLAY"
[ "$mode" = metor ] && compose="$compose -f $deployment_dir/compose.metor.yaml"
# shellcheck disable=SC2086
$compose up -d mysql
attempt=0
until [ "$(docker inspect --format '{{.State.Health.Status}}' "$($compose ps -q mysql)")" = healthy ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 60 ] || { echo "mysql did not become healthy" >&2; exit 1; }
  sleep 2
done

ai_password=$(printf '%s' "$AI_DB_PASSWORD" | sed "s/'/''/g")
sql="CREATE DATABASE IF NOT EXISTS metor_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'ai_user'@'%' IDENTIFIED BY '$ai_password';
ALTER USER 'ai_user'@'%' IDENTIFIED BY '$ai_password';
GRANT ALL PRIVILEGES ON metor_ai.* TO 'ai_user'@'%';"
if [ "$mode" = metor ]; then
  metor_password=$(printf '%s' "$METOR_DB_PASSWORD" | sed "s/'/''/g")
  sql="$sql
CREATE DATABASE IF NOT EXISTS \`$METOR_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '$METOR_DB_USER'@'%' IDENTIFIED BY '$metor_password';
ALTER USER '$METOR_DB_USER'@'%' IDENTIFIED BY '$metor_password';
GRANT ALL PRIVILEGES ON \`$METOR_DATABASE\`.* TO '$METOR_DB_USER'@'%';"
fi
printf '%s\nFLUSH PRIVILEGES;\n' "$sql" | $compose exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql mysql -uroot
echo "database bootstrap completed for mode: $mode"
