# 阶段一：构建与导出客户制品

执行方为我方制作人员。命令从包含四仓的 `icp_diag/` 根目录执行。制作方需 Docker／Buildx、Bash 和 Python 3.9+。每次制作使用唯一新版本号，示例中的 tag 按本次 `build.env` 替换。

## 范围与配置

本文的产物目标为 `linux/amd64`。按本次需要交付的文件选择流程。

| 本次任务 | 制作步骤 | 交付文件 |
| --- | --- | --- |
| 只发布部分镜像，例如 Frontend 和 Metor | [第 1 节](#1-冻结源码及外部输入) → [第 3 节](#3-制作并导出部分服务镜像)，校验 tar 后结束 | 本次变更的镜像 tar 和 `SHA256SUMS` |
| 制作完整客户包 | [第 1 节](#1-冻结源码及外部输入) → [第 2 节](#2-构建完整包所需镜像) → [第 4 节](#4-导出并核验完整客户包) | 包含四镜像的 `tar.gz` 和 `.sha256` |

`local-stack.py build` 将镜像写入当前 Docker context 的镜像库。`docker image save` 将本机镜像导出成 tar。专用 Buildx builder 可以直接输出 tar。客户主机上的操作见[客户部署](02-deploy.md)，Apple Silicon 本机 ARM64 制作见[本机 build](../local-release/01-build.md)。

构建和组包统一使用私有 `build.env`。将 `--env-file` 放在 `build` 或 `export` 子命令之前。脚本按这份文件读取本次配置，省略时会读取 `runtime/config/docker.env`。

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

新检出或 CI 按构建范围准备输入。仅制作前端时准备前端依赖和基础镜像。用普通 `build` 制作 AI 或 Metor 时，脚本会校验两端 SDK 制品和公开配置，因此要准备下表的两端输入。

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

保存本次公开配置 SHA，并按[发布检查清单](readiness.md)核对输入。配置须来自匹配的正式 Issuer；已有客户升级时同时核对既有信任和协议参数。

### license-product.json 放在哪里、如何指定

默认值 `license-build/license-product.json` 是分别相对于两个业务工程的路径，并不是相对于 deployment/ 或工作区根目录：

```text
icp_diag/
├── ai-runtime-service/license-build/license-product.json
└── metor-service/license-build/license-product.json
```

两份文件由 Issuer 的“SDK 接入配置”导出同一原始文件后分别放置，必须逐字节一致；它是公开产品／服务／公钥配置，不是客户的商业许可。两文件已经准备好且使用默认名称时，不用额外指定。可用本节前面的 cmp 与 license_artifacts.py 命令检查。

需要选另一份配置时，在**制作进程环境变量**指定同一个相对路径。例如先在两个工程都准备好 license-build/customer-product.json，再执行：

```bash
LICENSE_PRODUCT_CONFIG=license-build/customer-product.json \
  python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build
```

路径必须在各自 license-build/ 内，不能是绝对路径或含 ..。脚本检查两份配置一致后，将该值作为 Docker --build-arg LICENSE_PRODUCT_CONFIG 传给 AI／Metor。**当前代码不会从 build.env 或 docker.env 读取 LICENSE_PRODUCT_CONFIG**；只在这些文件添加该键不能选择另一份配置，需使用上面的进程环境变量。切回默认输入前也要清除之前 export 的同名变量。

配置和授权模式在构建时进入镜像；修改运行 env 或重启不会替换它们。修改公开配置／SDK 后要重建受影响的两个后端镜像，发行和既有安装信任兼容仍按前面的输入检查执行。

## 2. 构建完整包所需镜像

### 2.1 AMD64 构建入口

客户目标固定为 `linux/amd64`。普通 build 按 `build.env` 的 `METOR_PLATFORM` 构建，制作机需支持目标平台。Apple Silicon 上如需用专用 builder 隔离镜像，按[隔离 AMD64 构建](../amd64-build.md)直接生成归档。该脚本固定为 AMD64，参数按隔离构建说明配置。已有镜像的平台以 `docker image inspect` 为准。

本机 ARM64 制作和部署已移至 [local-release/](../local-release/README.md)。如果另有 ARM64 交付需求，应准备完整同架构四镜像并单独验收，不能替代本次 AMD64 客户发行。

### 2.2 普通 build：完整 AMD64 应用镜像

保存为 `runtime/release/release-20261028-1-amd64/build.env`：

```dotenv
MYSQL_IMAGE=icp-diag-mysql:8.4-amd64-20261028-1
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261028-1-amd64
METOR_IMAGE=metor-service:release-20261028-1-amd64
FRONTEND_IMAGE=metor-platform-frontend:release-20261028-1-amd64
METOR_PLATFORM=linux/amd64
```

制作期可联网，在支持 AMD64 构建的制作环境执行：

```bash
chmod 600 runtime/release/release-20261028-1-amd64/build.env
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build
```

`build` 制作 AI、Metor、前端三个应用镜像，不负责制作 MySQL。新交付需要上述专用 MySQL tag 时，在独立制作环境补齐：

```bash
docker build --platform linux/amd64 \
  --tag icp-diag-mysql:8.4-amd64-20261028-1 - <<'DOCKERFILE'
FROM mysql:8.4
DOCKERFILE
```

该镜像仍使用 MySQL 8.4，独立 tag 用于标识本次归档。已有符合要求的 AMD64 基线时，也可在完整包的 `build.env` 中填入实际复用的 MySQL tag。

Apple Silicon 制作 AMD64 时，使用[隔离构建说明](../amd64-build.md)生成四个归档，采用上面相同的 tag。该流程不会将 AMD64 基础镜像或归档加载到本机开发镜像库；完成后在独立组包环境继续第 4 节。

### 2.3 AI 离线源码构建

先在联网制作环境准备完整 AMD64 wheelhouse：

```bash
TARGET_PLATFORM=linux/amd64 deployment/scripts/prepare-wheelhouse.sh
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env \
  build --service ai --offline
```

这只制作 AI 镜像。Java／前端的无网源码重建不由该 --offline 入口承诺；隔离 AMD64 构建的 Gradle 缓存预热见[构建细节](../amd64-build.md)。客户使用预制镜像无需源码构建，普通 IDE JAR 或默认 bootJar 不能交付。

## 3. 制作并导出部分服务镜像

### 3.1 构建本次要发布的服务

在 `build.env` 中填写本次要构建的镜像引用和 `METOR_PLATFORM=linux/amd64`。普通 `build` 只读取选中服务的镜像引用。例如同时发布 Frontend 和 Metor 时，准备 `runtime/release/release-20261116-1-amd64/build.env`：

```dotenv
METOR_PLATFORM=linux/amd64
METOR_IMAGE=metor-service:release-20261116-1-amd64
FRONTEND_IMAGE=metor-platform-frontend:release-20261116-1-amd64
```

构建这两个服务：

```bash
BUILD_ENV=runtime/release/release-20261116-1-amd64/build.env
chmod 600 "$BUILD_ENV"
python3 deployment/scripts/local-stack.py \
  --env-file "$BUILD_ENV" build --service frontend --service metor
```

其他发布范围按下表调整 `--service`，可以重复传入。

| 选择参数 | 镜像变量 | 使用该镜像的 Compose 服务 |
| --- | --- | --- |
| --service frontend | FRONTEND_IMAGE | frontend |
| --service metor | METOR_IMAGE | metor |
| --service ai | AI_RUNTIME_IMAGE | ai-runtime、ai-migrate |

MySQL 不在 --service 可选项中；需单独制作时使用第 2.2 节的方法。Apple Silicon 制作单个 AMD64 镜像时，AI／Metor／MySQL 用[隔离构建说明](../amd64-build.md)中的 M6_BUILD_COMPONENTS，前端用该文档的独立 Buildx 命令；它们不会因修改 build.env 自动改变输出 tag，需与制作配置逐项对齐。

SDK、公开配置或两端契约变化时，制作全部受影响的服务，并按目标环境核对兼容性。

### 3.2 导出并校验本次镜像

下面以 Frontend 和 Metor 为例，其他发布范围替换为实际镜像引用。普通 `build` 完成后，在原 Docker context 中检查镜像，确认输出的每一行都是 `linux/amd64`。隔离 Buildx 已输出 tar 时，使用实际归档路径直接进行下方归档校验。

```bash
RELEASE=release-20261116-1-amd64
OUT="dist/$RELEASE"
METOR="metor-service:$RELEASE"
FRONTEND="metor-platform-frontend:$RELEASE"
METOR_TAR="metor-service_${RELEASE}_linux-amd64.tar"
FRONTEND_TAR="frontend_${RELEASE}_linux-amd64.tar"

docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$METOR" "$FRONTEND"
```

首次导出时执行以下命令。已有本次 tar，或用隔离 Buildx 直接生成了归档时，转到下面的归档校验，路径按实际产物填写。

```bash
mkdir -p "$OUT"
docker image save --output "$OUT/$METOR_TAR" "$METOR"
docker image save --output "$OUT/$FRONTEND_TAR" "$FRONTEND"
```

从工作区根目录运行归档检查，确认归档内的架构、tag 和层文件。随后对实际交付的 tar 生成校验清单。macOS 上没有 `sha256sum` 时，用 `shasum -a 256` 替换该命令。

```bash
python3 deployment/scripts/inspect-docker-archive.py "$OUT/$METOR_TAR"
python3 deployment/scripts/inspect-docker-archive.py "$OUT/$FRONTEND_TAR"
(cd "$OUT" && sha256sum "$METOR_TAR" "$FRONTEND_TAR" > SHA256SUMS)
```

交付本次的两个 tar 与 `SHA256SUMS`，制作到此结束。客户运维从[已有环境的镜像更新](02-deploy.md#74-用镜像归档更新已有环境)接续。

## 4. 导出并核验完整客户包

本节适用于明确需要交付四镜像、Embedding 和部署资产的版本。普通 `build` 结束后，在同一组包 context 直接检查镜像。隔离 Buildx 生成的 tar 按[隔离归档移交组包](../amd64-build.md#5-制作结果与移交组包)导入制作方的组包环境。

准备工作区的 `sdk-download/docker-compose-linux-x86_64`（官方 v2.33.0）。导出器校验固定 SHA256，并随包复制为 `deployment/bin/docker-compose-v2`。

把下例的四个镜像引用换成本次 `build.env` 中的实际值。只重制部分服务时，在 `build.env` 中写明其余服务复用的 AMD64 基线 tag。

```bash
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  icp-diag-mysql:8.4-amd64-20261028-1 ai-runtime-service:release-20261028-1-amd64 \
  metor-service:release-20261028-1-amd64 metor-platform-frontend:release-20261028-1-amd64
```

四个镜像都必须为 `linux/amd64`。将 `AI_RUNTIME_IMAGE` 对应的完整镜像 ID 添加到同一份私有 `build.env`。导出器用这个 ID 固定授权检查使用的 AI 镜像，并核对它与包内 AI 镜像一致。

```dotenv
LICENSE_TOOLS_IMAGE=sha256:<本次AI镜像的完整ID>
```

组包环境必须可执行该平台 AI 镜像的断网探测与 Embedding 实际编码，不需启动业务。默认凭据及完整模型路径从工作区 `runtime/config/docker.env` 读取；只提取三项数据库密码与 JWT，不复制源 env 的其他配置。需要选择其他获准输入时使用 `--credentials-env` 和 `--model-path`。

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env \
  export /absolute/dist/icp-diag-release-20261028-1-amd64.tar.gz \
  --credentials-env runtime/config/docker.env
cd /absolute/dist
sha256sum -c icp-diag-release-20261028-1-amd64.tar.gz.sha256
mkdir -p /absolute/inspection
tar -xzf icp-diag-release-20261028-1-amd64.tar.gz -C /absolute/inspection
sh /absolute/inspection/icp-diag-release-20261028-1-amd64/deployment/scripts/verify-bundle.sh \
  /absolute/inspection/icp-diag-release-20261028-1-amd64
```

归档及 `.sha256` 必须不存在；归档权限 0600。仍支持目录输出（目录权限 0700），推荐交付单个 tar.gz 加其摘要。失败不留下可误认成功的压缩包。

formatVersion 2 的 manifest 保存四仓 HEAD／工作区变更、四镜像 ID／平台、SDK／公开配置摘要、固定工具镜像及 Embedding manifest 摘要与离线加载结果，并明确 includesCredentials／includesModelWeights 为 true。所有模型文件和包内私有配置均被 SHA256SUMS 覆盖。

export 核对实际 SDK 载荷、客户模式、API 清单、两镜像公开配置一致性；模型会从实际归档暂存副本在本次 AI 镜像中断网加载并编码，缺少 tokenizer、真实权重、模型 manifest、维数不符或加载失败均不出包。包内不会包含业务数据、备份、安装主密钥、商业许可或签发私钥。

**还要把镜像内摘要与本次预期输入对照**：两镜像相互一致不代表选中了正式配置；旧演示镜像也可能彼此一致。切回源码根目录执行（参数为解压后的包目录）：

```bash
python3 - /absolute/inspection/icp-diag-release-20261028-1-amd64 <<'PY'
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

交付通过核验的 `tar.gz` 和 `.sha256`，留存包摘要及 manifest。脚本或随包文档变化后重新冻结、导出并核验。客户包的使用指南来自 `customer-docs/`，目标主机上的操作见[客户部署](02-deploy.md)。
