# 阶段一：构建与统一交付包

执行方：我方制作人员。命令从包含四仓的 `icp_diag/` 根目录执行。制作与组包使用独立环境，避免覆盖日常镜像。制作方需 Docker／Buildx、Bash 和 Python 3.9+；客户宿主工具要求见[首次部署](02-deploy.md)。本文版本号是示例，每次制作使用唯一新版本。

## 范围与配置

本文只负责 **Linux AMD64 客户镜像及统一交付包**。Apple Silicon 本机 ARM64 更新使用 [本机 build](../local-release/01-build.md) → [本机 deploy](../local-release/02-deploy.md)，不按本文启动服务。

制作统一显式指定私有 build.env，参数放在 build／export 子命令之前；它只对本条命令有效，不合并或覆盖 runtime/config/docker.env。省略 --env-file 时脚本会读取后者，所以正式制作不省略。运行版本、目录、授权初始化及更新在 [客户 deploy](02-deploy.md) 维护。

| 命令 | 产物 | 后续 |
| --- | --- | --- |
| 原生 AMD64 local-stack.py build | 当前 Docker 镜像库；不生成 dist 文件 | 不需 load；核验后 export |
| Apple Silicon 隔离 Buildx | dist/ 镜像 tar | 在独立组包环境 load 后 export |
| local-stack.py export ...tar.gz | 四镜像、完整 Embedding、配置、五份客户指南、manifest 和校验清单 | 客户按 deploy 校验、导入、准备、初始化、启动 |

Compose YAML 的 tag 是 env 缺失时的兜底，发行不修改它们。正式镜像选择写入 build.env，目标运行版本写入客户完整 docker.env；两份文件各有用途。普通 build 从文件读镜像名；直接 Compose 还会接受 Shell 同名变量覆盖，制作前清除残留 export 的镜像／平台变量。

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
| AMD64 专用 Compose | 工作区 `sdk-download/docker-compose-linux-x86_64`，官方 v2.33.0；导出器校验固定 SHA256，复制至包内 `deployment/bin/docker-compose-v2`，随附许可证 |

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

## 2. 选择目标架构并构建

### 2.1 AMD64 构建入口

客户目标固定 linux/amd64。原生 AMD64 制作机使用下节普通 build；Apple Silicon 使用[隔离 AMD64 构建](../amd64-build.md)，该脚本固定 AMD64，不读取 build.env。镜像平台以实际 inspect 为准，METOR_PLATFORM 不会转换已有镜像架构。

本机 ARM64 制作和部署已移至 [local-release/](../local-release/README.md)。如果另有 ARM64 交付需求，应准备完整同架构四镜像并单独验收，不能替代本次 AMD64 客户发行。

### 2.2 原生 AMD64：完整应用镜像

保存为 `runtime/release/release-20261028-1-amd64/build.env`：

```dotenv
MYSQL_IMAGE=icp-diag-mysql:8.4-amd64-20261028-1
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261028-1-amd64
METOR_IMAGE=metor-service:release-20261028-1-amd64
FRONTEND_IMAGE=metor-platform-frontend:release-20261028-1-amd64
METOR_PLATFORM=linux/amd64
```

制作期可联网，在原生 AMD64 制作机执行：

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

该镜像仍使用 MySQL 8.4，只用独立 tag 区分本次归档。已有环境仅更新应用时保留原 MYSQL_IMAGE，不把 MySQL 重制或升级混入应用更新。

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

## 3. 只制作单个服务镜像

使用本节 AMD64 build.env，只把要重制的服务改为新 tag，其余项保留实际存在的 AMD64 基线镜像。原生 AMD64 命令任选所需项，不必全部执行：

```bash
# 仅前端
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build --service frontend

# 仅 Java 后端
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build --service metor

# 仅 AI Runtime；其产物同时供运行服务与 ai-migrate 使用
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build --service ai

# 同时制作两个后端
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-amd64/build.env build --service ai --service metor
```

| 选择参数 | 镜像变量 | 使用该镜像的 Compose 服务 |
| --- | --- | --- |
| --service frontend | FRONTEND_IMAGE | frontend |
| --service metor | METOR_IMAGE | metor |
| --service ai | AI_RUNTIME_IMAGE | ai-runtime、ai-migrate |

MySQL 不在 --service 可选项中；需单独制作时使用第 2.2 节的方法。Apple Silicon 制作单个 AMD64 镜像时，AI／Metor／MySQL 用[隔离构建说明](../amd64-build.md)中的 M6_BUILD_COMPONENTS，前端用该文档的独立 Buildx 命令；它们不会因修改 build.env 自动改变输出 tag，需与制作配置逐项对齐。

SDK、公开配置或两端契约变化时，要制作全部受影响服务，不能把“单镜像构建成功”当作整栈兼容通过。单服务制作也不自动修改运行 env、停止／启动容器或执行迁移；部署操作统一按[客户 deploy 的已有环境更新](02-deploy.md#7-已有环境更新)执行。

## 4. 验证实际镜像并导出

本节只组装本次 AMD64 客户包，四镜像不能混用架构。本机 ARM64 直接更新不执行 export，按[本机 deploy](../local-release/02-deploy.md)操作。

原生构建的镜像已经在制作镜像库中。隔离 AMD64 构建得到的是四个 tar，需在**独立组包环境**的 Docker 镜像库加载后才能 export。以下是制作阶段的归档加载，不是客户安装步骤，也不在日常 ARM64 开发镜像库执行：

```bash
docker load --input dist/m6-amd64-images-release-20261028-1-amd64/mysql_8.4_linux-amd64.tar
docker load --input dist/m6-amd64-images-release-20261028-1-amd64/ai-runtime-service_release-20261028-1-amd64_linux-amd64.tar
docker load --input dist/m6-amd64-images-release-20261028-1-amd64/metor-service_release-20261028-1-amd64_linux-amd64.tar
docker load --input dist/m6-amd64-images-release-20261028-1-amd64/frontend_release-20261028-1-amd64_linux-amd64.tar
```

```bash
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  icp-diag-mysql:8.4-amd64-20261028-1 ai-runtime-service:release-20261028-1-amd64 \
  metor-service:release-20261028-1-amd64 metor-platform-frontend:release-20261028-1-amd64
```

四个实际平台必须一致。将 AI 完整 ID `sha256:<64位十六进制>` 添加到上面的私有 build.env：

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

将同一包放到原生目标 Linux，按[首次部署](02-deploy.md)和[授权导入验收](04-license-import.md)完成验收，保存包 SHA、manifest 与验收结果。脚本或文档变化后重新冻结、导出、核验；不手工修改已核验包后沿用旧摘要。完整模型与获准凭据随包；Chat、场景及客户业务资料按[准备清单](business-materials.md)落实。

客户包文档只导出 customer-docs/ 的五份使用指南，本目录供制作方实施使用。
