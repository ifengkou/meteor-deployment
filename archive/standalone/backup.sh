#!/bin/sh
set -eu

[ "$#" -ge 1 ] || { echo "usage: $0 BACKUP_DIRECTORY [ai|metor]" >&2; exit 2; }
backup_dir=$1
mode=${2:-ai}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
deployment_dir=$(dirname "$script_dir")
# Legacy offline bundles keep scripts/ next to deployment/.
[ -f "$deployment_dir/compose.ai.yaml" ] || deployment_dir="$deployment_dir/deployment"
env_file=${ENV_FILE:-$deployment_dir/.env}
compose="docker compose --env-file $env_file -f $deployment_dir/compose.ai.yaml"
[ -z "${AI_COMPOSE_OVERLAY:-}" ] || compose="$compose -f $AI_COMPOSE_OVERLAY"
[ "$mode" = metor ] && compose="$compose -f $deployment_dir/compose.metor.yaml"
mkdir -p "$backup_dir/documents" "$backup_dir/chroma"
$compose exec -T ai-runtime python - <<'PYMODELS' > "$backup_dir/embedding-models-snapshot.json"
import json, os
from pathlib import Path
config_path = os.getenv("AI_EMBEDDING_MODELS_CONFIG")
catalog = json.loads(Path(config_path).read_text()) if config_path else {"models": [{
    "id": "bge-small-zh-v1.5", "modelPath": os.environ["AI_EMBEDDING_MODEL_PATH"],
    "normalize": os.getenv("AI_EMBEDDING_NORMALIZE", "true").lower() == "true"
}]}
manifests = {}
for model in catalog["models"]:
    manifest = Path(model["modelPath"]) / "model-manifest.json"
    manifests[model["id"]] = json.loads(manifest.read_text()) if manifest.is_file() else None
print(json.dumps({"catalog": catalog, "manifests": manifests}, ensure_ascii=False, indent=2))
PYMODELS

running_services=$($compose ps --status running --services)
was_ai_running=false
was_metor_running=false
printf '%s\n' "$running_services" | grep -qx ai-runtime && was_ai_running=true
printf '%s\n' "$running_services" | grep -qx metor && was_metor_running=true
resume_original() {
  if [ "$was_ai_running" = true ]; then $compose start ai-runtime; fi
  if [ "$mode" = metor ] && [ "$was_metor_running" = true ]; then $compose start metor; fi
  return 0
}
trap resume_original EXIT INT TERM
if [ "$mode" = metor ] && [ "$was_metor_running" = true ]; then $compose stop metor; fi
if [ "$was_ai_running" = true ]; then $compose stop ai-runtime; fi
set -a; . "$env_file"; set +a
$compose exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
  mysqldump -uroot --single-transaction --routines --triggers metor_ai > "$backup_dir/metor_ai.sql"
$compose cp ai-runtime:/data/ai/documents/. "$backup_dir/documents"
$compose cp ai-runtime:/data/ai/chroma/. "$backup_dir/chroma"
if [ -n "${AI_EMBEDDING_MODEL_HOST_PATH:-}" ] && [ -f "$AI_EMBEDDING_MODEL_HOST_PATH/model-manifest.json" ]; then
  cp "$AI_EMBEDDING_MODEL_HOST_PATH/model-manifest.json" "$backup_dir/model-manifest.json"
fi
printf '{"formatVersion":1,"createdAt":"%s","mode":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$mode" > "$backup_dir/backup-manifest.json"
(cd "$backup_dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
trap - EXIT INT TERM
resume_original
echo "backup completed: $backup_dir"
