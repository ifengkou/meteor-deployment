# 阶段一：构建与统一交付包

执行方：我方制作人员。命令从包含四仓的 `icp_diag/` 根目录执行。制作与组包使用独立环境，避免覆盖日常镜像。版本号示例 `release-20261026-1` 必须换成实际唯一版本。

## 1. 冻结源码及外部输入

分别审查 `ai-runtime-service`、`metor-service`、`frontend`、`deployment` 的 diff 和未跟踪文件，按仓库分别提交、推送，保存四个完整 SHA。不将 SDK 包、真实配置、runtime 或客户资料强制加入 Git。提交后、开始构建前执行：

```bash
python3 - <<'PY'
import subprocess
for repo in ('ai-runtime-service', 'metor-service', 'frontend', 'deployment'):
    dirty = subprocess.check_output(['git', '-C', repo, 'status', '--porcelain'], text=True)
    if dirty:
        raise SystemExit(f'{repo} 有未提交变更，停止正式发布')
    sha = subprocess.check_output(['git', '-C', repo, 'rev-parse', 'HEAD'], text=True).strip()
    print(repo, sha)
PY
```

检查对应远端已包含这些提交。构建期间不切分支、不继续编辑源码；发布记录中的 SHA 要与最终 manifest 一致。导出器会记录脏工作区，**不会自动拒绝**脏发布。

每次新检出或 CI 都需另外准备：

| 输入 | 位置／要求 |
| --- | --- |
| 正式 Java Maven 制品 | `metor-service/vendor/license-maven/`，SDK 0.7.1，保留发行元数据并校验 Release SHA256SUMS |
| 正式 Python core wheel | `ai-runtime-service/wheelhouse/metor_license_core-0.7.1-py3-none-any.whl`，匹配 uv.lock 摘要 |
| Issuer 公开配置 | 两端 `license-build/license-product.json`，同一原字节文件；来源为本次正式 Issuer |
| 完整业务构建依赖 | Gradle／前端依赖、基础镜像；AI 离线构建还需匹配目标 Linux 架构与 Python 3.12 的完整 wheelhouse |

制作方按[Java 输入](../../../metor-service/license-build/README.md)、[AI 输入](../../../ai-runtime-service/license-build/README.md)准备后检查：

```bash
cmp ai-runtime-service/license-build/license-product.json metor-service/license-build/license-product.json
python3 deployment/scripts/license_artifacts.py --workspace .
```

保存输出的公开配置 SHA。本次核查值见[收口记录](readiness.md)。不使用 `deployment-20261025` 演示信任，不重新生成一套密钥替代正式 Issuer。已有客户升级还须核对全部旧信任和协议参数。

## 2. 按已确认的 AMD64 架构构建

本次客户已确认 Linux x86_64／AMD64，统一使用 `linux/amd64`。现有 DAT JNI 是 x86-64；ARM64 镜像会移除该库，不能作为本次交付制品。

在一个新私有文件中保存制作输入，例如 `runtime/release/release-20261026-1/build.env`，权限 0600；它不用于启动业务，也不复制现有生产 env：

```dotenv
MYSQL_IMAGE=mysql:8.4
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261026-1
METOR_IMAGE=metor-service:release-20261026-1
FRONTEND_IMAGE=metor-platform-frontend:release-20261026-1
METOR_PLATFORM=linux/amd64
```

原生目标架构、制作期可联网的标准构建：

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261026-1/build.env build
docker pull --platform linux/amd64 mysql:8.4
```

`build` 制作三个应用镜像，不负责拉取 MySQL。本次四个镜像均需 AMD64，不混入本机 ARM64 MySQL。镜像 tag 一经记录和验收不得覆盖。

Apple Silicon 制作 AMD64 时，改走[AMD64 手册第 2～3 节](../amd64.md)：`build-amd64-images.sh` 制作 AI、Metor、MySQL 归档，前端单独 Buildx，再将四个归档导入独立组包镜像库。不要在同次发行中混用两条流程的不同制品。

AI 无网源码构建需要先在联网制作环境执行：

```bash
TARGET_PLATFORM=linux/amd64 deployment/scripts/prepare-wheelhouse.sh
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261026-1/build.env build --service ai --offline
```

这只重建 AI，不等于三个应用全部完成。Java／前端的无网源码重建不由该 `--offline` 入口承诺；客户运行预制镜像不需要源码构建。普通 IDE JAR、默认 `bootJar` 或开发镜像不能交付。

## 3. 验证实际镜像并导出

```bash
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  mysql:8.4 ai-runtime-service:release-20261026-1 \
  metor-service:release-20261026-1 metor-platform-frontend:release-20261026-1
```

四个实际平台必须一致。将 AI 完整 ID `sha256:<64位十六进制>` 添加到上面的私有 build.env：

```dotenv
LICENSE_TOOLS_IMAGE=sha256:<本次AI镜像的完整ID>
```

组包环境必须可执行该平台 AI 镜像的断网探测，不需启动业务：

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261026-1/build.env \
  export /absolute/dist/icp-diag-release-20261026-1-amd64
sh /absolute/dist/icp-diag-release-20261026-1-amd64/deployment/scripts/verify-bundle.sh \
  /absolute/dist/icp-diag-release-20261026-1-amd64
```

输出目录必须不存在。export 核对实际 SDK 载荷、客户模式、API 清单和两镜像公开配置一致性；manifest 保存四仓 HEAD／工作区变更、四镜像 ID／平台、SDK／配置摘要和固定工具镜像。

**还要把镜像内摘要与本次预期输入对照**：两镜像相互一致不代表选中了正式配置；旧演示镜像也可能彼此一致。在源码根目录执行（参数为包目录）：

```bash
python3 - /absolute/dist/icp-diag-release-20261026-1-amd64 <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
m = json.loads((Path(sys.argv[1]) / 'manifest.json').read_text())
expected = hashlib.sha256(Path('ai-runtime-service/license-build/license-product.json').read_bytes()).hexdigest()
if m['licensing']['productConfigSha256'] != expected:
    raise SystemExit('镜像内公开配置与本次正式输入不一致，重新构建')
for repo in ('ai-runtime-service', 'metor-service', 'frontend', 'deployment'):
    entry = m['repos'][repo]
    head = subprocess.check_output(['git', '-C', repo, 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', repo, 'status', '--porcelain'], text=True)
    if entry['head'] != head or entry['workingTree'] or dirty:
        raise SystemExit(f'{repo} 发布基线不一致或工作区不干净')
print('正式公开配置及四仓基线核对通过')
PY
```

将同一包放到原生目标 Linux，按后续阶段完成验收，保存包 SHA、manifest 与验收结果。脚本或文档变化后重新冻结、导出、核验；不手工修改已核验包后沿用旧摘要。完整模型、业务配置和凭据按[独立清单](business-materials.md)准备。
