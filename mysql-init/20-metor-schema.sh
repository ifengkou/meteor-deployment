#!/bin/sh
set -eu

[ -n "${METOR_DATABASE:-}" ] || exit 0
[ -n "${METOR_DB_USER:-}" ] || { echo "METOR_DB_USER is required" >&2; exit 1; }
[ -n "${METOR_DB_PASSWORD:-}" ] || { echo "METOR_DB_PASSWORD is required" >&2; exit 1; }

case "$METOR_DATABASE" in
  *[!A-Za-z0-9_]* ) echo "database and user names may contain only letters, numbers, and underscore" >&2; exit 1 ;;
esac
case "$METOR_DB_USER" in
  *[!A-Za-z0-9_]* ) echo "user name may contain only letters, numbers, and underscore" >&2; exit 1 ;;
esac

escaped_password=$(printf '%s' "$METOR_DB_PASSWORD" | sed "s/'/''/g")
mysql --protocol=socket -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS \`$METOR_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS '$METOR_DB_USER'@'%' IDENTIFIED BY '$escaped_password';
ALTER USER '$METOR_DB_USER'@'%' IDENTIFIED BY '$escaped_password';
GRANT ALL PRIVILEGES ON \`$METOR_DATABASE\`.* TO '$METOR_DB_USER'@'%';
FLUSH PRIVILEGES;
SQL
