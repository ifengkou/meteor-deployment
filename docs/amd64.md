# Linux AMD64 镜像制作、部署与更新

部署约定：宿主机使用 `/opt/icp-diag` 作为统一目录，MySQL 继续使用 Docker 命名卷。前端、Metor、AI Runtime 分别制作镜像，通过 Compose 组合部署，后续可单独更新。

本说明基于 2026-10-16 的部署脚本和 Dockerfile。命令是操作步骤，不代表目标 AMD64 主机已完成运行验收。首次发布仍需在原生 Linux x86_64 环境验证 JNI、真实样本、备份恢复和业务功能。

## 1. 环境与交付内容

### 制作机

制作机需要三个业务工程与部署工程同级：

```text
icp_diag/
├── deployment/
├── ai-runtime-service/
├── metor-service/
└── frontend/
```

需要 Docker、Buildx、Python 3.9+、Bash 和 `shasum`。Apple Silicon Mac 可通过专用 Buildx builder 制作 AMD64 归档，不加载到本机 ARM64 镜像库。原生 AMD64 Linux 也可构建，但不要直接导出当前 Mac 运行的 ARM64 镜像。

首次构建需访问基础镜像仓库、Gradle、Python 和前端依赖源。AI Dockerfile 的构建上下文必须有 `wheelhouse/` 目录，联网构建不要求其中备齐离线 wheel。离线源码重建另见[离线部署说明](offline-deployment.md)，ARM64 wheel 不能用于 AMD64。

### 目标 Linux 主机

| 工具 | 要求与用途 |
|---|---|
| CPU／系统 | Linux x86_64，`uname -m` 应为 `x86_64` |
| Docker Engine | 服务运行与镜像导入，操作者需具备 Docker 使用权限 |
| Compose 插件 | 2.24.4 或更新版，共享目录配置使用 `!override` |
| Python | 3.9+，建议 3.12，仅用于部署管理脚本 |
| 系统工具 | `tar`、`gzip`、`sha256sum`，健康检查示例另用 `curl` |

检查命令：

```bash
uname -m
docker version
docker compose version
python3 --version
tar --version
gzip --version
sha256sum --version
```

`deployment/scripts/local-stack.py` 只使用 Python 标准库，不需要虚拟环境或 `pip install`。没有 Python 时，提前安装发行版提供的 Python；离线机需准备对应发行版及架构的系统安装包和依赖。也可直接运行 Compose，但需自行保持相同配置文件、项目名和迁移／备份顺序。

目标机不需要 Git、JDK、Node、宿主 Python 业务依赖或源码。服务运行环境已经在镜像中。模型权重、Chat 模型服务、业务数据和私有凭据不包含在通用镜像包中，应分别准备。

## 2. 在制作机生成四个 AMD64 镜像

以下命令从制作机工作区根目录执行，`deployment/` 与三个业务工程同级。`release-20261016-1` 为示例版本，每次发布替换为唯一版本号，不覆盖旧版本 tag。

```bash
docker buildx version
deployment/scripts/build-amd64-images.sh release-20261016-1
```

现有脚本构建 AI、Metor、MySQL，默认输出到工作区 `dist/m6-amd64-images-release-20261016-1/`。专用 builder 名为 `m6-amd64-builder`，可用 `docker buildx inspect m6-amd64-builder --bootstrap` 确认支持 `linux/amd64`。

前端需另行制作：

```bash
docker buildx build \
  --builder m6-amd64-builder \
  --platform linux/amd64 \
  --provenance=false \
  --tag metor-platform-frontend:release-20261016-1 \
  --output type=docker,dest=dist/m6-amd64-images-release-20261016-1/frontend_release-20261016-1_linux-amd64.tar \
  frontend

python3 deployment/scripts/inspect-docker-archive.py \
  dist/m6-amd64-images-release-20261016-1/frontend_release-20261016-1_linux-amd64.tar
```

四个制品与部署变量对应如下：

| 制品中的镜像 tag | 部署变量 |
|---|---|
| `mysql:8.4` | `MYSQL_IMAGE` |
| `ai-runtime-service:release-20261016-1` | `AI_RUNTIME_IMAGE` |
| `metor-service:release-20261016-1` | `METOR_IMAGE` |
| `metor-platform-frontend:release-20261016-1` | `FRONTEND_IMAGE` |

三个后端归档由构建脚本校验，前端由上述检查命令校验，均应显示 `linux/amd64`。构建成功与架构校验不等于容器启动或 JNI 验收通过。

构建失败时可按组件续跑，例如：

```bash
M6_BUILD_COMPONENTS=metor \
  deployment/scripts/build-amd64-images.sh release-20261016-1
```

镜像源和 Gradle 缓存预热方法见 [AMD64 隔离构建方案](amd64-build.md)。不要为解决下载失败而把含凭据的整个宿主缓存目录打进镜像。

## 3. 组装可搬运部署包

部署包使用以下结构，解包后的根目录对应目标机 `/opt/icp-diag`：

```text
icp-diag-amd64-release-20261016-1/
├── deployment/                 # Compose、mysql-init、migrations、脚本
│   ├── config/embedding-models.example.json
│   └── docs/                   # 运维说明
├── images/                     # 四个 AMD64 Docker archive
├── release-info.md             # 源码版本、镜像版本、构建／验收记录
└── SHA256SUMS
```

从工作区根目录执行，输出目录应尚不存在：

```bash
mkdir -p dist/icp-diag-amd64-release-20261016-1/images
mkdir -p dist/icp-diag-amd64-release-20261016-1/deployment/scripts
mkdir -p dist/icp-diag-amd64-release-20261016-1/deployment/config

cp deployment/compose.ai.yaml deployment/compose.metor.yaml \
  deployment/compose.full-local.yaml deployment/compose.shared-runtime.yaml \
  deployment/README.md dist/icp-diag-amd64-release-20261016-1/deployment/
cp -R deployment/mysql-init dist/icp-diag-amd64-release-20261016-1/deployment/
cp -R deployment/migrations dist/icp-diag-amd64-release-20261016-1/deployment/
cp deployment/scripts/local-stack.py deployment/scripts/inspect-docker-archive.py \
  dist/icp-diag-amd64-release-20261016-1/deployment/scripts/
cp deployment/config/embedding-models.example.json dist/icp-diag-amd64-release-20261016-1/deployment/config/
cp -R deployment/docs dist/icp-diag-amd64-release-20261016-1/deployment/

cp dist/m6-amd64-images-release-20261016-1/ai-runtime-service_release-20261016-1_linux-amd64.tar \
  dist/m6-amd64-images-release-20261016-1/metor-service_release-20261016-1_linux-amd64.tar \
  dist/m6-amd64-images-release-20261016-1/mysql_8.4_linux-amd64.tar \
  dist/m6-amd64-images-release-20261016-1/frontend_release-20261016-1_linux-amd64.tar \
  dist/icp-diag-amd64-release-20261016-1/images/
```

### 数量配置映射

整栈 Compose 已透传 `METOR_AEROSPACE_DECLARATION_MAX_LOG_FILES`，默认 20。目标环境修改私有 env 后重新创建 Metor；无需修改部署包中的 Compose，也不添加未被包装脚本读取的额外配置文件。

在 `release-info.md` 记录三仓提交号及未提交源码差异、四个镜像 tag、JNI 库与模型制品版本、构建日期、目标环境验证结果。不要填写私有凭据或客户事件内容。

全部公共文件确认后，从部署包根目录生成校验清单：

```bash
cd dist/icp-diag-amd64-release-20261016-1
find . -type f ! -name SHA256SUMS -exec shasum -a 256 {} + > SHA256SUMS
```

生成清单后不要修改包内文件。目标机配置属于解包后的部署定制，应另行备份。不复制制作机的 `runtime/config/docker.env`、业务数据、备份或模型权重到通用包。

现有 `local-stack.py export` 从本机镜像库导出，不会自动把 ARM64 转成 AMD64。本流程直接使用 AMD64 archive，避免混入本机运行镜像。

## 4. 目标机统一目录

将公共部署包放入 `/opt/icp-diag`。模型权重另行放入指定目录：

```text
/opt/icp-diag/
├── deployment/
│   ├── config/embedding-models.example.json
│   └── docs/
├── images/
├── release-info.md
├── SHA256SUMS
└── runtime/
    ├── config/
    │   ├── docker.env
    │   └── embedding/docker.json
    ├── models/embedding/        # 完整 BGE 模型，只读挂载
    ├── data/
    │   ├── metor/              # 原始日志、报告和平台附件
    │   └── ai/{documents,chroma}/
    ├── logs/docker/{ai,metor}/
    ├── work/{ai,metor}/
    └── backups/
```

| 宿主路径 | 容器路径 | 属性 |
|---|---|---|
| `runtime/data/metor` | `/data/metor` | Metor 可写，升级保留 |
| `runtime/data/ai/documents` | `/data/ai/documents` | AI 可写，升级保留 |
| `runtime/data/ai/chroma` | `/data/ai/chroma` | AI 可写，禁止两套实例同时写入 |
| `runtime/models/embedding` | `/models/embedding` | 只读，宿主路径不能填进模型清单的 `modelPath` |
| `runtime/config/embedding/docker.json` | `/config/embedding-models.json` | 只读单文件挂载，启动前文件必须存在 |
| `runtime/logs/docker/ai`、`metor` | `/logs/ai`、`/logs/metor` | 各服务可写 |
| `runtime/work/ai`、`metor` | `/work/ai`、`/work/metor` | 临时工作目录，升级不替换挂载 |

MySQL 保留 Compose 的 `mysql-data` 命名卷，当前项目名下通常为 `icp-diag-local_mysql-data`，以实际检查为准。不创建 `runtime/data/mysql`，不把旧数据库目录直接绑定到新环境。容器标准输出仍由 Docker 日志驱动管理，包括前端日志，不需要另建前端业务数据目录。

## 5. 首次部署到全新 Linux 主机

以下步骤只用于全新环境。已有部署不重新初始化凭据，不覆盖现有 `runtime` 或 MySQL 卷，更新见第 8 节。命令以能管理 `/opt/icp-diag` 且能访问 Docker 的运维账户执行；需要系统权限时使用 `sudo`。

### 5.1 校验并导入镜像

```bash
cd /opt/icp-diag
sha256sum -c SHA256SUMS

docker load --input images/mysql_8.4_linux-amd64.tar
docker load --input images/ai-runtime-service_release-20261016-1_linux-amd64.tar
docker load --input images/metor-service_release-20261016-1_linux-amd64.tar
docker load --input images/frontend_release-20261016-1_linux-amd64.tar

docker image inspect \
  mysql:8.4 ai-runtime-service:release-20261016-1 \
  metor-service:release-20261016-1 metor-platform-frontend:release-20261016-1 \
  --format '{{.RepoTags}} {{.Os}}/{{.Architecture}}'
```

四个镜像都应为 `linux/amd64`。配置使用 `pull_policy: never`，缺少镜像时会失败，不会替你从公网下载。

### 5.2 生成私有配置

先准备完整 Embedding 权重，至少不能只有 `config.json` 而没有权重和 tokenizer。确认模型目录后执行：

```bash
cd /opt/icp-diag
python3 deployment/scripts/local-stack.py --help
python3 deployment/scripts/local-stack.py init \
  --model-path /opt/icp-diag/runtime/models/embedding
```

脚本生成 `runtime/config/docker.env`、数据库密码、JWT 密钥和 `runtime/config/embedding/docker.json`。Python 只使用标准库，无须安装业务依赖。脚本遇到已有 env 会拒绝覆盖，不要删除它来强行重新初始化。

编辑生成的 env，保留随机密码及数据库 URL，只修改或补充以下部署项：

```dotenv
WORKSPACE_RUNTIME_DIR=/opt/icp-diag/runtime
METOR_PLATFORM=linux/amd64
MYSQL_IMAGE=mysql:8.4
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261016-1
METOR_IMAGE=metor-service:release-20261016-1
FRONTEND_IMAGE=metor-platform-frontend:release-20261016-1

AI_EMBEDDING_MODEL_HOST_PATH=/opt/icp-diag/runtime/models/embedding
AI_EMBEDDING_MODELS_CONFIG_HOST_PATH=/opt/icp-diag/runtime/config/embedding/docker.json

METOR_AEROSPACE_DECRYPTION_ENABLED=true
METOR_AEROSPACE_DECLARATION_MAX_LOG_FILES=20
METOR_AEROSPACE_AI_ENABLED=false
```

上面不是完整 env，不可用它覆盖生成文件。航空 AI 初次关闭，待模型服务及六类业务场景配置完成后再开启。仅验证解密和解析时关闭 AI 不代表故障诊断最终成功。

`WORKSPACE_RUNTIME_DIR` 会让包装脚本自动加载 `compose.shared-runtime.yaml`。脚本固定使用 `icp-diag-local` 项目名和 `metor_service` 业务库，目标机部署也沿用，不随意换项目名造成新卷。数据库另有 `metor_ai` 库，两库使用独立应用账号。

### 5.3 创建挂载目录并授权

```bash
mkdir -p runtime/data/metor runtime/data/ai/documents runtime/data/ai/chroma
mkdir -p runtime/logs/docker/ai runtime/logs/docker/metor
mkdir -p runtime/work/ai runtime/work/metor runtime/backups
chmod 0700 runtime/config runtime/backups
chmod 0600 runtime/config/docker.env
chmod 0755 runtime/config/embedding
chmod 0644 runtime/config/embedding/docker.json

docker run --rm --entrypoint id metor-service:release-20261016-1
docker run --rm --entrypoint id ai-runtime-service:release-20261016-1
```

从实际镜像读取 UID/GID，再授权各自目录，不硬编码某台机器的账户编号：

```bash
metor_owner="$(docker run --rm --entrypoint sh metor-service:release-20261016-1 -c 'printf "%s:%s" "$(id -u)" "$(id -g)"')"
ai_owner="$(docker run --rm --entrypoint sh ai-runtime-service:release-20261016-1 -c 'printf "%s:%s" "$(id -u)" "$(id -g)"')"

sudo chown -R "$metor_owner" runtime/data/metor runtime/logs/docker/metor runtime/work/metor
sudo chown -R "$ai_owner" runtime/data/ai runtime/logs/docker/ai runtime/work/ai
chmod -R a+rX runtime/models/embedding
```

这组授权针对首次部署的指定目录，不对 `/opt/icp-diag` 整体递归改属主，也不使用 `chmod 777`。模型权重须为完整实际目录；若包含软链接，确认链接目标也随模型制品可访问。启用 SELinux 的发行版还需按主机策略配置挂载标签，不通过关闭安全策略解决访问失败。

## 6. 启动与访问

先校验配置，不打印含密码的完整展开结果：

```bash
cd /opt/icp-diag
python3 deployment/scripts/local-stack.py compose config --quiet

python3 deployment/scripts/local-stack.py compose up -d --wait mysql
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
python3 deployment/scripts/local-stack.py compose ps
```

逐条确认成功，失败时停止后续步骤。AI 的 Alembic 迁移必须显式运行，Metor 启动时执行 Flyway。已有 MySQL 卷不会重放初始化脚本，修改 env 密码也不会自动给已有数据库用户改密。

从旧环境迁入时，先采用[备份恢复流程](backup-restore.md)在空库及空文件目录恢复，不把上述空环境启动当作数据迁移。跨架构迁移使用逻辑 SQL 备份和文件备份，不复制正在运行的 MySQL 物理数据目录。恢复配置中的 ARM64 tag、制作机路径也必须换成目标值。

默认入口均绑定主机回环地址：

| 服务 | 宿主端口 | 容器间地址 |
|---|---|---|
| 前端 | `127.0.0.1:18180` | `frontend:8080` |
| Metor | `127.0.0.1:18080` | `metor:8080` |
| AI | `127.0.0.1:18092` | `ai-runtime:8090` |
| MySQL | `127.0.0.1:13306`，共享配置启用 | `mysql:3306` |

```bash
curl --fail http://127.0.0.1:18180/healthz
curl --fail http://127.0.0.1:18080/actuator/health/readiness
curl --fail http://127.0.0.1:18092/internal/health/ready
```

首次远程测试可从操作电脑建立 SSH 隧道：

```bash
ssh -N -L 18180:127.0.0.1:18180 operator@linux-host
```

浏览器访问操作电脑的 `http://127.0.0.1:18180`。正式对外提供入口时使用受控反向代理和 TLS，不直接开放 MySQL／AI 管理端口。前端当前绑定地址在 Compose 中写为 `127.0.0.1`，不存在只加 env 就能修改它的前端绑定变量。

## 7. JNI 与业务验收

Metor AMD64 镜像已包含 `/usr/local/lib/libEncryptAndDecrypt.so`，不需要宿主另挂 `.so`。该库为 Linux AMD64，不能用 ARM64 镜像完成相同验证。

```bash
python3 deployment/scripts/local-stack.py compose exec -T metor sh -c \
  'test -r /usr/local/lib/libEncryptAndDecrypt.so && ldd /usr/local/lib/libEncryptAndDecrypt.so'
```

动态依赖不能有 `not found`。这只证明文件及依赖可见，还需通过实际 DAT 调用验证 JVM 加载、JNI 符号和解密结果。

按顺序记录以下结果，客户样本和事件内容只存私有验收目录：

1. 检查 Metor 进程有效解密开关为开启，无 `UnsatisfiedLinkError` 等加载异常。
2. 用获准 DAT 样本验证解密、拆分和事件入库，再用 DAT/ZIP 混合多根验证每根来源、组内数量与顺序。
3. 分别验证故障与巡检、源复用、共享目录重建、数据库查询、DOCX 和全部原根导出。
4. 配置平台中的真实模型服务、业务场景及绑定，验证容器可达的模型地址。容器内 `localhost` 不是宿主模型服务。
5. 将 `METOR_AEROSPACE_AI_ENABLED` 改为 `true`，重新创建 Metor，再验证真实 AI 故障与巡检成功。健康检查或固定 AI 响应不替代此项。
6. 做一次受控停启、断网运行和隔离备份恢复演练，记录镜像 ID、数据库迁移版本和数据对账结果。

前端多选仍为独立交付事项，不把后端接口多文件测试记作多选 UI 已验收。

## 8. 日常更新与单服务升级

升级只更换目标镜像版本，保持私有配置、宿主数据目录、项目名和数据库卷。容器重建会保留挂载数据，但单实例更新会短暂停机，不是滚动零停机发布。

维护前暂停新申报和摄取操作，等待正在执行的诊断及写入任务结束，再进行停写备份。当前 Metor 重启只重新发现 READY 任务，不自动恢复 RUNNING 任务；不要用直接重启中断任务，再未经核对将其重置为 READY。积压较多时先安排排空窗口，异常中断按步骤、报告和日志核查后处理。

### 8.1 更新前备份

在旧镜像 tag 和旧配置仍有效时先备份，每次使用尚不存在的新目录：

```bash
cd /opt/icp-diag
python3 deployment/scripts/local-stack.py backup \
  /opt/icp-diag/runtime/backups/before-release-20261017-1
```

备份会短暂停止前端、Metor、AI 写入，再恢复原运行状态，包含两个业务库、应用文件、Chroma 和私有配置，不包含模型权重和镜像。模型与旧镜像另行保留。备份含密码，不能进入通用交付包；还应复制到受保护的异机存储，统一目录内的副本不能防宿主磁盘故障。

含迁移的维护窗口可用 `backup --keep-stopped <新目录>` 让写入服务保持停止，再按 AI、Metor、前端顺序恢复。共享模式备份会检查 8080／8090，避免本机开发进程继续写同一份数据。

### 8.2 只更新前端

校验更新包后导入新镜像，在 `runtime/config/docker.env` 中只改 `FRONTEND_IMAGE`：

```bash
docker load --input /absolute/path/frontend-new-amd64.tar
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

检查页面、登录和接口代理。若依赖新版 API，按兼容关系更新后端，不能只升级前端。

### 8.3 只更新 Metor

完成备份并保留旧配置后，导入新镜像，只改 `METOR_IMAGE`，再执行：

```bash
docker load --input /absolute/path/metor-new-amd64.tar
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose stop frontend metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

检查 Flyway、readiness、JNI 和业务样本。此步骤不更换 AI／MySQL 镜像，不重建其容器；前述一致性备份仍会短暂停写。若使用了 `--keep-stopped`，需先恢复原版本 AI 服务并确认就绪，再启动 Metor。

### 8.4 只更新 AI Runtime

完成备份后，导入新镜像并修改 `AI_RUNTIME_IMAGE`。`ai-migrate` 与 `ai-runtime` 共用该变量：

```bash
docker load --input /absolute/path/ai-runtime-new-amd64.tar
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose stop frontend metor ai-runtime
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

迁移失败时不继续恢复调用方。不要依赖上次已退出成功的旧迁移容器，也不要只换 AI 容器而漏跑迁移。验证真实检索、图谱、文档摄取和场景调用。

MySQL 更新单独安排数据库升级与恢复演练，不混入普通应用更新。

### 8.5 仅修改配置

环境变量或挂载变更后重新创建对应服务，例如：

```bash
python3 deployment/scripts/local-stack.py compose \
  up -d --no-deps --force-recreate --wait metor
```

`restart` 不重新读取 Compose 环境变量或挂载。AI 配置变更按暂停调用方、重建 AI、确认就绪、恢复 Metor 和前端的顺序执行。模型清单替换为新宿主文件后也要重新创建 AI，避免单文件旧挂载仍引用旧文件。

Chat 模型 API Key、模型服务、场景提示词等通过平台配置，保存在数据库，不需要为了修改这些业务配置重建镜像。Embedding 权重、模型 ID 或归一化设置变化可能要求重建 Chroma，见 [Embedding 运维](../../ai-runtime-service/docs/operations/embedding-models.md)。

## 9. 排查、回退与禁止事项

```bash
cd /opt/icp-diag
python3 deployment/scripts/local-stack.py compose ps
python3 deployment/scripts/local-stack.py compose logs --tail=200 metor
python3 deployment/scripts/local-stack.py compose logs --tail=200 ai-migrate ai-runtime
python3 deployment/scripts/local-stack.py compose exec -T mysql \
  sh -c 'test -d /var/lib/mysql'
```

| 现象 | 先检查 |
|---|---|
| `python3` 不存在 | 安装宿主 Python，镜像中的 Python 不等于宿主 Python |
| 无法识别 `!override` | 升级 Compose 插件到支持的版本 |
| 文件写入失败 | 指定挂载目录的实际 UID/GID、只读设置、SELinux 标签 |
| 页面无法远程访问 | 当前绑定回环地址，使用 SSH 隧道或正式反向代理 |
| 容器找不到模型 | 宿主权重完整性、只读挂载、清单中的容器路径 |
| JNI 加载失败 | 镜像架构、解密开关、库依赖、JNI 符号和实际调用日志 |
| 修改 env 未生效 | Compose 是否透传变量，以及是否重新创建服务 |
| AI 流程失败 | 航空 AI 开关、真实场景配置及容器到模型服务的网络 |

纯代码且数据兼容的更新，可恢复旧镜像 tag 并按相同依赖顺序重新创建。执行过不兼容数据库、索引或文件格式迁移后，只回退镜像不足以恢复系统，应停止写入，在新隔离目标恢复备份并对账；保留升级后的新增业务数据。

多文件版本降级前停止新增多根单据，让多根 READY 任务在支持它的版本处理完毕。旧程序不能接管这些任务，V20 的 TEXT 字段不缩回 VARCHAR(255)。派生文件可重建不代表原始根、元数据或业务库可以删除。

日常操作不执行 `down -v`、`docker volume prune`，不重复 `init`，不覆盖现有私有 env，不整体替换 `runtime`，不同时启动两套实例写同一份 Chroma。不输出或公开分享完整 Compose 展开配置、私有备份和客户事件。

## 10. 没有宿主 Python 时的 Compose 入口

推荐提前安装 Python，以便使用包含一致性备份和恢复检查的包装脚本。若只需在私有 env、目录授权及备份均已准备好的主机启动或查看服务，可在 Bash 中定义相同拓扑的入口：

```bash
cd /opt/icp-diag
stack() {
  docker compose -p icp-diag-local \
    --env-file /opt/icp-diag/runtime/config/docker.env \
    -f /opt/icp-diag/deployment/compose.ai.yaml \
    -f /opt/icp-diag/deployment/compose.metor.yaml \
    -f /opt/icp-diag/deployment/compose.full-local.yaml \
    -f /opt/icp-diag/deployment/compose.shared-runtime.yaml "$@"
}

stack config --quiet
stack ps
```

本文 `python3 deployment/scripts/local-stack.py compose ...` 可替换为 `stack ...`，启动顺序和迁移门禁保持不变。但 `init`、`backup`、`restore-stack` 是 Python 包装脚本的能力，不是 Compose 子命令，不能写成 `stack backup`。没有对应备份方案时先补齐工具，不跳过备份直接升级。

## 参考

- [部署入口](../README.md)
- [AMD64 隔离构建](amd64-build.md)
- [日常更新](updates.md)与[备份恢复](backup-restore.md)
- Docker：[`!override` 版本要求](https://docs.docker.com/reference/compose-file/merge/)、[单服务更新](https://docs.docker.com/compose/how-tos/production/)、[`restart` 配置边界](https://docs.docker.com/reference/cli/docker/compose/restart/)
