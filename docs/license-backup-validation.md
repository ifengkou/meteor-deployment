# Phase 5.5：隔离验证授权资料备份与恢复

本指南对应 Phase 5.5 的授权资料隔离验证，检查结果由程序断言和命令退出码判定，可由研发代理自行执行，不要求用户重复人工验收。Mac 上的 Docker 也可执行，不要求先准备独立 Linux 主机。

演练调用整栈备份/恢复使用的同一个 `license_backup` 模块。全程只挂载只读脚本和公开测试许可，所有身份、密钥、归档和恢复目录均在临时容器内生成，退出即删除。不启动业务服务或数据库，不修改真实系统时间，不使用商业签发私钥。本指南验证授权资料的一致性和权限；实际服务请求放行、整栈恢复及客户 Linux 验收分别按后续阶段和[整栈备份恢复](backup-restore.md)执行。

## 1. 进入独立、断网的 Linux 容器

在宿主机终端执行。镜像须已存在于本机；`--pull=never` 防止临时联网拉取。若本机没有该镜像，先从制作环境取得与本机架构匹配的镜像并 `docker load`。

```sh
cd /Users/sloong/Workspace/github/icp_diag
docker run --rm -it --pull=never --network none \
  --mount "type=bind,src=$PWD/deployment/scripts,dst=/scripts,readonly" \
  --mount "type=bind,src=$PWD/license-sdk/protocol/test-fixtures/commercial-v1-test-vectors.json,dst=/fixture.json,readonly" \
  --workdir /work python:3.12.14-slim-bookworm sh
```

**后续所有命令都在这个容器终端内执行**，不要切回宿主机执行。容器默认 root，用于验证真实数值 UID/GID；没有挂载宿主运行目录或 Docker socket。

```sh
export PYTHONPATH=/scripts
id -u
```

预期输出 `0`。

## 2. 创建临时安装与摘要基线

创建 `/work/license-check/source`。使用仓库公开的 `TERM-UNBOUND` 签名测试许可作为待备份文件；它的测试公钥不能用于客户发行。备份演练不依赖该许可当前是否 ACTIVE，不向产品导入测试信任。

```sh
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import license_init as init
import license_backup as backup

base = Path('/work/license-check')
base.mkdir(mode=0o700)
source = base / 'source'
result = init.initialize_license(source)
fixture = json.loads(Path('/fixture.json').read_text())
sample = next(item['envelope'] for item in fixture['cases'] if item['case'] == 'TERM-UNBOUND')
license_file = source / 'shared/active.license.json'
license_file.write_bytes(init.canonical(sample))
os.chown(license_file, 21001, 21000)
os.chmod(license_file, 0o640)
# 合成宿主标识只用于本演练的同宿主恢复前校验，不是 SDK 机器绑定输入。
(base / 'machine-id').write_text('00112233445566778899aabbccddeeff\n')
contents, installation = backup.read_installation(source)
baseline = {
    'installationId': installation,
    'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()},
}
(base / 'baseline.json').write_text(json.dumps(baseline, indent=2))
print('PASS 初始化:', result['state'], installation)
for name, digest in sorted(baseline['files'].items()):
    print(digest, name)
PY
```

预期为 `INITIALIZED`，并列出五个文件的摘要：安装身份、安装服务密钥、测试商业许可、Metor clock、AI clock。这里只输出密钥摘要，不输出密钥内容。

## 3. 备份并查看归档

```sh
python - <<'PY'
import hashlib
import json
import stat
import tarfile
from pathlib import Path
import license_backup as backup

base = Path('/work/license-check')
directory = base / 'backup'
directory.mkdir(mode=0o700)
config = {'LICENSE_MACHINE_ID_PATH': str(base / 'machine-id')}
fingerprint = backup.host_fingerprint(config, base)
assert fingerprint is not None
archive = directory / backup.ARCHIVE
metadata = backup.backup(base / 'source', archive, fingerprint)
manifest = directory / 'license-manifest.json'
manifest.write_text(json.dumps(metadata, indent=2))
manifest.chmod(0o600)
checksums = directory / 'SHA256SUMS'
checksums.write_text(''.join(
    f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
    for path in (archive, manifest)
))
checksums.chmod(0o600)
assert stat.S_IMODE(directory.stat().st_mode) == 0o700
for path in (archive, manifest, checksums):
    assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.name
with tarfile.open(archive) as contents:
    names = {item.name for item in contents}
assert set(backup.DIRECTORIES).issubset(names)
assert 'identity/installation.json' in names
assert 'shared/active.license.json' in names
assert 'state/metor/clock.json' in names and 'state/ai/clock.json' in names
assert not any(Path(name).name.endswith('.lock') for name in names)
print('PASS 备份目录/文件权限及归档范围')
print('PASS 备份:', archive)
print(manifest.read_text())
PY
(cd /work/license-check/backup && sha256sum -c SHA256SUMS)
tar --numeric-owner -tvzf /work/license-check/backup/license-state.tar.gz
```

预期两项摘要均为 `OK`。归档包含 `identity`、`shared` 和两端 `state`；不包含 `.init.lock`。归档文件为 0600，备份目录为 0700。此处 `license-manifest.json` 是专项演练清单；正式整栈命令将同一元数据保存到 `backup-manifest.json` 的 `licenseState` 字段。

## 4. 恢复到空目标，逐项对照

**不要对 target 执行 license-init。** 恢复应保留原安装身份，target 在本步骤开始前必须不存在或为空。

```sh
python - <<'PY'
import hashlib
import json
from pathlib import Path
import license_backup as backup

base = Path('/work/license-check')
baseline = json.loads((base / 'baseline.json').read_text())
metadata = json.loads((base / 'backup/license-manifest.json').read_text())
config = {'LICENSE_MACHINE_ID_PATH': str(base / 'machine-id')}
fingerprint = backup.host_fingerprint(config, base)
target = base / 'target'
stage = backup.prepare_restore(target, base / 'backup' / backup.ARCHIVE, metadata, fingerprint)
backup.publish_restore(target, stage)
contents, installation = backup.read_installation(target)
assert installation == baseline['installationId']
assert set(contents) == set(baseline['files'])
print('PASS 安装 UUID 保持:', installation)
for name, raw in sorted(contents.items()):
    assert hashlib.sha256(raw).hexdigest() == baseline['files'][name], name
    print('PASS 字节一致:', name)
for name, expected in {**backup.DIRECTORIES, **backup.FILES}.items():
    path = target / name
    if path.exists():
        info = path.stat()
        actual = (info.st_uid, info.st_gid, info.st_mode & 0o7777)
        assert actual == expected, (name, actual, expected)
print('PASS 恢复后的数值 UID/GID/权限全部一致')
# 恢复只写 target，原 source 的两端 clock、身份、密钥和许可仍保持原字节。
for name, digest in baseline['files'].items():
    assert hashlib.sha256((base / 'source' / name).read_bytes()).hexdigest() == digest, name
print('PASS 原安装的两端状态和共享资料均未改变')
assert not list(base.glob('.license-restore-*'))
print('PASS 恢复暂存目录已清理')
PY
```

对照的数值权限：

| 项目 | UID:GID | mode |
| --- | --- | --- |
| 根目录、identity、state | 0:21000 | 0750 |
| shared | 21001:21000 | 0750 |
| 安装身份、service.key | 0:21000 | 0640 |
| 商业许可 | 21001:21000 | 0640 |
| Metor 状态目录 / clock | 21001:21001 | 0700 / 0600 |
| AI 状态目录 / clock | 21002:21002 | 0700 / 0600 |

## 5. 验证非空目标与不同宿主均拒绝

```sh
python - <<'PY'
import json
from pathlib import Path
import license_backup as backup

base = Path('/work/license-check')
metadata = json.loads((base / 'backup/license-manifest.json').read_text())
archive = base / 'backup' / backup.ARCHIVE
cases = (
    ('非空目标', base / 'target', metadata['machineIdSha256'], 'nonempty'),
    ('不同宿主', base / 'different-host-target', '0' * 64, 'same readable host'),
)
for label, target, fingerprint, expected in cases:
    try:
        backup.prepare_restore(target, archive, metadata, fingerprint)
    except ValueError as error:
        assert expected in str(error), str(error)
        print('PASS 正确拒绝:', label, str(error))
    else:
        raise AssertionError(f'应拒绝但被接受: {label}')
assert not (base / 'different-host-target').exists()
assert not list(base.glob('.license-restore-*'))
print('PASS 拒绝后没有新目标或遗留暂存目录')
PY
```

## 6. 记录结果并退出

程序已自动断言：

- UUID 完全相同，五个文件均显示“字节一致”。
- 数值 UID/GID/mode 检查通过，原安装两端状态未变。
- 非空目标和不同宿主各自明确拒绝。
- 所有命令均在上述独立容器执行，未挂载真实运行资料。

保存终端的 PASS 输出后执行 `exit`；`--rm` 会删除容器和内部演练资料。记录镜像 tag、执行日期和结果即可，不复制生成的 `service.key` 内容。

全部命令成功退出且输出上述 PASS/OK，即可记录 Phase 5.5 的授权目录自动验收通过，无需人工复签。它没有启动两端服务，另一服务停机或运行中的 API 行为仍由 Phase 8 实机用例验收。本指南保留逐步命令，便于复现及排错。
