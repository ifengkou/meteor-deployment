# 阶段二：客户首次部署

执行方：客户运维／我方实施。仅用于全新 Linux 安装。已有环境从[更新](../updates.md)和[SDK 升级](../license-sdk-upgrade.md)执行，保留私有配置、数据卷和整个授权目录。

本次客户已确认 Linux x86_64／AMD64，使用本次正式 AMD64 包，并在原生 Linux AMD64 上验收。

## 1. 主机和资料就绪

准备匹配架构的 Docker Engine、Compose 2.24.4+、Python 3.9+、tar、gzip、sha256sum、curl；离线机提前准备这些宿主工具的发行版安装包与依赖。命令需要 Docker 权限，安装根目录操作需要相应系统权限。

```bash
uname -m
docker version
docker compose version
python3 --version
```

`uname -m` 应为 `x86_64`，包内四镜像应为 `linux/amd64`；若检测为 `aarch64`，停止本次安装并重新核对主机。当前 DAT JNI 制品为 AMD64。提前核对磁盘、内存、模型推理容量、时钟同步、域名、证书与业务访问网络。

将完整公共包解包到 `/opt/icp-diag`，根下直接包含 `deployment/`、`images/`、`manifest.json` 和 `SHA256SUMS`。在业务启动前按[资料准备](business-materials.md)放好完整 Embedding 权重；Chat／业务配置可在授权开通后从平台配置。

## 2. 校验包、导入镜像

```bash
cd /opt/icp-diag
sh deployment/scripts/verify-bundle.sh .
sh deployment/scripts/import-images.sh .
```

脚本先验包，加载后核对镜像 reference、ID 和平台。失败即停止，不手工改 manifest 绕过。此时不需 SDK 初始化，也不需数据库或模型服务在线。

## 3. 生成并核对私有配置

确认完整权重放在 `/opt/icp-diag/runtime/models/embedding` 后：

```bash
python3 deployment/scripts/local-stack.py init \
  --model-path /opt/icp-diag/runtime/models/embedding
```

生成 `runtime/config/docker.env`（0600）和 `runtime/config/embedding/docker.json`。已有 env 会拒绝覆盖；不要删除已有配置强行重试。`init` 只检查模型 `config.json` 存在，不能证明权重完整。

**启动前编辑生成的 env，保留随机密码和 AI_DB_URL**。下面是需要核对的条目，不是完整文件，镜像引用与平台以本包 manifest 为准：

```dotenv
WORKSPACE_RUNTIME_DIR=/opt/icp-diag/runtime
MYSQL_IMAGE=mysql:8.4
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261026-1
METOR_IMAGE=metor-service:release-20261026-1
FRONTEND_IMAGE=metor-platform-frontend:release-20261026-1
METOR_PLATFORM=linux/amd64
LICENSE_ROOT=/opt/icp-diag/runtime/license
LICENSE_MACHINE_ID_PATH=/etc/machine-id
AI_EMBEDDING_MODEL_HOST_PATH=/opt/icp-diag/runtime/models/embedding
AI_EMBEDDING_MODELS_CONFIG_HOST_PATH=/opt/icp-diag/runtime/config/embedding/docker.json
METOR_AEROSPACE_DECRYPTION_ENABLED=true
METOR_AEROSPACE_DECLARATION_MAX_LOG_FILES=20
METOR_AEROSPACE_AI_ENABLED=false
```

`init` 仍写历史 `p6-local` 应用 tag，必须替换；不要把上述示例 tag 当作已存在的镜像。本次保留 `METOR_PLATFORM=linux/amd64` 并开启解密，完成真实 DAT 验收。航空 AI 先关闭，六场景准备完成后再开启；关闭 AI 不是最终业务验收通过。

便携包自动读取 manifest 中的固定 AI 工具镜像，无须设置 LICENSE_TOOLS_IMAGE；源码安装才需要显式填写完整不可变 AI 镜像 ID。配置中不得有与包内工具 ID 冲突的旧值。

核对目标机存在稳定的真实 machine-id；缺失时由客户系统管理流程处理，不能造一个临时文件冒充。HOST_INSTALL 许可绑定最终宿主与安装身份；迁机或重建安装前先规划授权处理。

## 4. 创建目录、落实数值权限

以下只操作全新安装的指定目录：

```bash
mkdir -p runtime/data/metor runtime/data/ai/documents runtime/data/ai/chroma
mkdir -p runtime/logs/docker/metor runtime/logs/docker/ai
mkdir -p runtime/work/metor runtime/work/ai runtime/backups
chmod 0700 runtime/config runtime/backups
chmod 0600 runtime/config/docker.env
chmod 0755 runtime/config/embedding
chmod 0644 runtime/config/embedding/docker.json
```

使用 manifest 中的实际镜像 tag 检查 `docker run --rm --pull=never --network=none --entrypoint id <镜像>`。当前 Metor 为 `21001:21001`，AI 为 `21002:21002`，共同许可组 `21000`。确认一致后：

```bash
sudo chown -R 21001:21001 runtime/data/metor runtime/logs/docker/metor runtime/work/metor
sudo chown -R 21002:21002 runtime/data/ai runtime/logs/docker/ai runtime/work/ai
chmod -R a+rX runtime/models/embedding
```

模型需可遍历、可读；不要对整个安装目录递归改 owner 或使用 chmod 777。SELinux 主机落实对应挂载策略。已有数据目录须先备份并单独核对，不能套用首次目录授权当作迁移工具。

## 5. 单独初始化授权

确认所有本安装 Metor／AI、源码进程与旧初始化任务都已停止：

```bash
sudo python3 deployment/scripts/local-stack.py \
  --env-file /opt/icp-diag/runtime/config/docker.env license-init
sudo python3 deployment/scripts/local-stack.py \
  --env-file /opt/icp-diag/runtime/config/docker.env license-init
```

首次应为 `INITIALIZED`，重复为 `ALREADY_INITIALIZED`。工具在固定 AI 镜像内断网调用 SDK，生成安装身份、32 字节主密钥及两份初始 clock，设置目录权限；宿主不安装 SDK，不需手工写 JSON。保留整个 `/opt/icp-diag/runtime/license`，不 copy 演示环境的身份和 key。

失败保留现场。`OUTCOME_UNKNOWN` 需停写后用同命令核对重试；已完成身份缺件或损坏时不靠删除目录重建，按[备份恢复](../backup-restore.md)处理。

## 6. 迁移并按顺序启动

```bash
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose up -d --wait mysql
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
python3 deployment/scripts/local-stack.py compose ps
curl --fail http://127.0.0.1:18180/healthz
curl --fail http://127.0.0.1:18080/actuator/health/readiness
curl --fail http://127.0.0.1:18092/internal/health/ready
```

逐条确认成功，失败时不继续。AI 显式跑 Alembic，Metor 启动执行 Flyway。无商业许可时健康、登录和有鉴权的授权维护仍可用，受控业务拒绝。健康通过不等于商业许可有效。

项目名沿用 `icp-diag-local`；MySQL 使用该项目命名卷，两个库为 `metor_service`／`metor_ai`。已有卷不重放初始化 SQL，修改 env 密码不自动修改已有数据库账户。不要 `down -v` 或重建数据卷。

## 7. 客户访问入口与首管理员

默认前端固定监听 `127.0.0.1:18180`，没有前端绑定地址 env。首次实施可在操作电脑运行：

```bash
ssh -N -L 18180:127.0.0.1:18180 operator@customer-host
```

浏览器访问 `http://127.0.0.1:18180`。全新空用户库的第一次有效登录会创建首管理员；由授权实施人员先在受控入口完成，使用客户约定的强口令，再开放业务入口。已有库使用原管理员，无默认客户密码。

正式局域网访问采用**同宿主反向代理**：客户域名／TLS 入口转发到 `http://127.0.0.1:18180`，统一代理页面与 API；验收上传限制、长任务超时、路径和登录行为。远端代理不能直接访问客户机的回环端口，需要另外评审入口绑定与防火墙方案，不能只改 FRONTEND_EXPOSED_PORT。

Metor、AI 和 MySQL 保持本机维护端口，不为浏览器单独开放。入口方案、域名、证书续期负责人写入发行记录。

完成后进入[授权签发](03-license-issue.md)，再按[导入和最终验收](04-license-import.md)开通业务。
