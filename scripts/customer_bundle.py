"""Portable customer model and private configuration; no business or license state."""

import hashlib
import json
import os
import shlex
import shutil
import stat
from pathlib import Path
from urllib.parse import quote

CREDENTIAL_KEYS = (
    "MYSQL_ROOT_PASSWORD", "AI_DB_PASSWORD", "METOR_DB_PASSWORD",
    "METOR_PLATFORM_SECURITY_JWT_SECRET",
)
CREDENTIAL_PATH = "deployment/config/customer.env"
MODEL_PATH = "models/embedding"
COMPOSE_PATH = "deployment/bin/docker-compose-v2"
COMPOSE_VERSION = "v2.33.0"
COMPOSE_SHA256 = "6395dbb256db6ea28d5c6695bc9bc33866c07ad1c93792f8d85857f1c21c34ee"
ENV_HEADER = "# ICP literal environment v1"
EMBEDDING_CATALOG = {"models": [{
    "id": "bge-small-zh-v1.5", "name": "BGE Small 中文 v1.5",
    "modelPath": "/models/embedding", "enabled": True, "normalize": True, "batchSize": 16,
}]}


def read_env(path):
    result = {}
    lines = Path(path).read_text().splitlines()
    literal = bool(lines and lines[0] == ENV_HEADER)
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        if literal and value.lstrip().startswith('"'):
            result[key.strip()] = json.loads(value).replace("$$", "$")
        else:
            values = shlex.split(value, comments=True)
            result[key.strip()] = values[0] if values else ""
    return result


def credentials(path):
    values = read_env(path)
    if any(not values.get(key) or any(c in values[key] for c in "\r\n\x00")
           for key in CREDENTIAL_KEYS):
        raise ValueError("source env must contain all three database passwords and the JWT secret")
    if len(values[CREDENTIAL_KEYS[-1]].encode()) < 32:
        raise ValueError("source JWT secret must contain at least 32 bytes")
    return {key: values[key] for key in CREDENTIAL_KEYS}


def package_compose(source, target):
    """Copy the reviewed standalone AMD64 tool without changing host tools."""
    if digest(source) != COMPOSE_SHA256:
        raise ValueError("Compose binary must match the official v2.33.0 Linux x86_64 checksum")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)
    return {"version": COMPOSE_VERSION, "path": COMPOSE_PATH,
            "sha256": COMPOSE_SHA256, "architecture": "amd64", "os": "linux"}


def verify_compose(bundle, record):
    expected = {"version": COMPOSE_VERSION, "path": COMPOSE_PATH,
                "sha256": COMPOSE_SHA256, "architecture": "amd64", "os": "linux"}
    if record != expected:
        raise ValueError("unsupported bundled Compose metadata")
    target = Path(bundle) / COMPOSE_PATH
    no_link_path(target)
    if not target.is_file() or digest(target) != COMPOSE_SHA256 or not os.access(target, os.X_OK):
        raise ValueError("bundled Compose missing, changed or not executable; re-extract the release")
    return target


def write_env(path, values):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(ENV_HEADER + "\n")
        for key, value in values.items():
            # Compose interpolates dotenv values; $$ preserves literal dollar signs.
            output.write(key + "=" + json.dumps(str(value), ensure_ascii=False).replace("$", "$$") + "\n")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def no_link_path(path):
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("customer payload paths must not pass through symbolic links")
    return path


def model_files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("complete model directory required")
    files = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("model files must be regular, self-contained files")
        if path.name != "SHA256SUMS":
            files.append(path)
    return files


def validate_model(root):
    root = Path(root)
    files = model_files(root)
    required = {"config.json", "modules.json", "tokenizer_config.json", "model-manifest.json"}
    names = {p.relative_to(root).as_posix() for p in files}
    if not required <= names or not ({"tokenizer.json", "vocab.txt"} & names):
        raise ValueError("complete embedding configuration, tokenizer and model manifest required")
    weights = [p for p in files if p.suffix == ".safetensors" or p.name == "pytorch_model.bin"]
    if not weights:
        raise ValueError("real embedding weights required, not missing files or LFS pointers")
    for path in weights:
        with path.open("rb") as source:
            head = source.read(128)
        if not head or head.startswith(b"version https://git-lfs.github.com"):
            raise ValueError("real embedding weights required, not missing files or LFS pointers")
    metadata = json.loads((root / "model-manifest.json").read_text())
    if metadata.get("artifactName") != "bge-small-zh-v1.5":
        raise ValueError("this customer stack requires bge-small-zh-v1.5")
    expected = metadata.get("modelSafetensorsSha256")
    if expected and digest(root / "model.safetensors") != expected:
        raise ValueError("embedding weight differs from its reviewed model manifest")
    return files


MODEL_PROBE = '''
import json
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('/models/embedding', device='cpu', local_files_only=True)
vectors = model.encode(['客户交付模型验证'], normalize_embeddings=True)
assert vectors.shape[0] == 1 and vectors.shape[1] > 0
print(json.dumps({'dimension': int(vectors.shape[1])}))
'''


def package_model(root, target, image, run):
    root = Path(root).resolve()
    validate_model(root)
    shutil.copytree(root, target)
    for path in [target, *target.rglob("*")]:
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    # The actual packaged bytes, not the source directory, must load without network.
    probe = run([
        "docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
        "--tmpfs", "/tmp", "--env", "HF_HOME=/tmp/huggingface",
        "--env", "HF_HUB_OFFLINE=1", "--env", "TRANSFORMERS_OFFLINE=1",
        "--mount", f"type=bind,src={target},dst=/models/embedding,readonly",
        "--entrypoint", "python", image, "-c", MODEL_PROBE,
    ], capture_output=True, text=True)
    dimension = json.loads(probe.stdout)["dimension"]
    metadata = json.loads((target / "model-manifest.json").read_text())
    if not isinstance(dimension, int) or dimension <= 0 or metadata.get("dimension") != dimension:
        raise ValueError("loaded embedding dimension differs from the model manifest")
    return {"id": "bge-small-zh-v1.5", "path": MODEL_PATH, "dimension": dimension,
            "manifestSha256": digest(target / "model-manifest.json"),
            "offlineLoadVerified": True}


def runtime_config(bundle, manifest):
    bundle = Path(bundle)
    private = credentials(bundle / CREDENTIAL_PATH)
    runtime = bundle / "runtime"
    values = dict(private)
    values.update(dict(zip(
        ("MYSQL_IMAGE", "AI_RUNTIME_IMAGE", "METOR_IMAGE", "FRONTEND_IMAGE"),
        [entry["reference"] for entry in manifest["images"]],
    )))
    values.update({
        "TZ": "Asia/Shanghai",
        "METOR_PLATFORM": "linux/" + manifest["images"][0]["architecture"],
        "METOR_DATABASE": "metor_service", "METOR_DB_USER": "metor_user",
        "AI_DB_URL": "mysql+pymysql://ai_user:" + quote(private["AI_DB_PASSWORD"], safe="")
                     + "@mysql:3306/metor_ai?charset=utf8mb4",
        "WORKSPACE_RUNTIME_DIR": str(runtime),
        "LICENSE_ROOT": str(runtime / "license"),
        "LICENSE_MACHINE_ID_PATH": "/etc/machine-id",
        "AI_EMBEDDING_MODEL_HOST_PATH": str(bundle / MODEL_PATH),
        "AI_EMBEDDING_MODELS_CONFIG_HOST_PATH": str(runtime / "config/embedding/docker.json"),
        "AI_RUNTIME_BIND_ADDRESS": "127.0.0.1", "AI_RUNTIME_EXPOSED_PORT": "18092",
        "METOR_BIND_ADDRESS": "127.0.0.1", "APP_EXPOSED_PORT": "18080",
        "FRONTEND_EXPOSED_PORT": "18180",
        "METOR_AEROSPACE_DECRYPTION_ENABLED": "true"
            if manifest["images"][0]["architecture"] == "amd64" else "false",
        "METOR_AEROSPACE_DECLARATION_MAX_LOG_FILES": "20", "METOR_AEROSPACE_AI_ENABLED": "true",
    })
    return values


def verify_contents(bundle, manifest):
    if manifest.get("formatVersion") != 2:
        raise ValueError("customer preparation requires the complete format 2 bundle")
    if manifest.get("includesCredentials") is not True or manifest.get("includesModelWeights") is not True:
        raise ValueError("customer bundle must include approved credentials and embedding weights")
    private = no_link_path(bundle / CREDENTIAL_PATH)
    if (not private.is_file() or private.stat().st_nlink != 1
            or set(read_env(private)) != set(CREDENTIAL_KEYS)):
        raise ValueError("customer credential file must contain only the approved four values")
    credentials(private)
    model = manifest.get("embeddingModel", {})
    if (model.get("path") != MODEL_PATH or model.get("id") != "bge-small-zh-v1.5"
            or model.get("offlineLoadVerified") is not True
            or digest(bundle / MODEL_PATH / "model-manifest.json") != model.get("manifestSha256")):
        raise ValueError("customer bundle embedding manifest mismatch")
    no_link_path(bundle / MODEL_PATH)
    validate_model(bundle / MODEL_PATH)
    expected = {CREDENTIAL_PATH, *(
        p.relative_to(bundle).as_posix() for p in model_files(bundle / MODEL_PATH)
    )}
    if manifest.get("compose") is not None:
        verify_compose(bundle, manifest["compose"])
        expected.update((COMPOSE_PATH, "deployment/bin/docker-compose-LICENSE"))
    entries = {}
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        checksum, _, name = line.partition("  ")
        if name in expected:
            if name in entries:
                raise ValueError("duplicate customer payload checksum")
            entries[name] = checksum
    if set(entries) != expected:
        raise ValueError("bundle checksums must cover credentials and every embedding file")
    for name, checksum in entries.items():
        if digest(bundle / name) != checksum:
            raise ValueError("customer payload checksum mismatch")
