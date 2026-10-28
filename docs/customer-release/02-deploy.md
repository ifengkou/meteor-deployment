# 阶段二：客户部署（首次安装／已有 SDK 更新）

执行方：客户运维／我方实施。第 1—6 节只用于全新 Linux AMD64 安装；已有完整 SDK 安装直接看[第 7 节](#7-已有环境更新)，不重新 prepare／init／license-init。本机 Docker Desktop 更新另见[本机 deploy](../local-release/02-deploy.md)。

本次客户已确认 Linux x86_64／AMD64，使用本次正式 AMD64 包，并在原生 Linux AMD64 上验收。

## 1. 主机和资料就绪

本次目标环境为 Docker Engine 24.0.7、Python 3.8.10，另需 tar、gzip、sha256sum、curl。AMD64 包固定携带 Compose v2.33.0，统一入口自动调用；系统 docker-compose 1.25.0 可保留，不另装 Python 3.12。命令需要 Docker 权限，安装根目录操作需要相应系统权限。

```bash
uname -m
docker version
python3 --version
```

`uname -m` 应为 `x86_64`，包内四镜像应为 `linux/amd64`；若检测为 `aarch64`，停止本次安装并重新核对主机。当前 DAT JNI 制品为 AMD64。提前核对磁盘、内存、模型推理容量、时钟同步、域名、证书与业务访问网络。

本次交付为一个包含四镜像、完整 Embedding、部署资产和约定凭据的私有 `tar.gz`，另附归档 `.sha256`。Chat 服务和业务配置仍按[资料准备](business-materials.md)落实。

以下在客户 Linux 的 root 运维会话执行（可先用 `sudo -i` 进入），仅用于全新安装；目标目录已有部署时停止，走更新流程。

## 2. 校验归档、解压并导入镜像

```bash
cd /absolute/transfer
sha256sum -c icp-diag-linux-amd64-candidate-20261027-1.tar.gz.sha256
mkdir -p /opt/icp-diag
tar --no-same-owner -xzf icp-diag-linux-amd64-candidate-20261027-1.tar.gz \
  -C /opt/icp-diag --strip-components=1
cd /opt/icp-diag
sh deployment/scripts/import-images.sh .
```

包内根下包含 `deployment/`、`images/`、`models/embedding/`、`manifest.json` 和 `SHA256SUMS`。导入脚本先验包，再加载并核对实际镜像 ID 和架构；缺件、摘要或架构不符时停止。镜像导入不需要授权、数据库或 Chat 服务在线。

## 3. 一条命令准备配置、目录和权限

```bash
python3 deployment/scripts/prepare-runtime.py
```

此脚本仅在目标 Linux 以 root 运行，默认安装根为脚本所在交付包的根目录，执行以下工作：

- 校验完整包、模型文件和已导入镜像，拒绝与目标机原生架构不同的包；检查实际 Metor UID/GID 为 21001、AI 为 21002。
- 从 manifest 自动填写本次四镜像引用及 `linux/amd64`，不再手工替换 `p6-local`。
- 从包内 `deployment/config/customer.env` 原样复用制作机 `runtime/config/docker.env` 中的 MYSQL_ROOT_PASSWORD、AI_DB_PASSWORD、METOR_DB_PASSWORD 和 JWT 密钥，生成 `runtime/config/docker.env`（0600）。AI_DB_URL 自动按实际密码进行 URL 编码。
- 自动填写目标机运行目录、授权根与模型路径；Embedding 直接只读挂载包内 `/opt/icp-diag/models/embedding`，无需另传模型包或复制权重。
- 创建业务数据、日志、工作和备份目录，设置指定目录数值 owner／mode；模型文件设为只读。不会递归改已有业务文件的 owner，不使用 chmod 777。
- 创建容器路径为 `/models/embedding` 的模型清单。默认开启 AMD64 解密，航空 AI 保持关闭，待模型服务和六场景配置完成后开启。

相同配置下可重复执行；已有不同配置、非空目录属主不符或路径含软链接时拒绝覆盖。配置之后如经人工调整，不再用准备脚本重置它，按更新流程维护。源 env 不会整体进入交付包，不包含制作机路径、旧镜像、客户安装身份或签发私钥。

包内凭据与发行清单固定，采用客户约定的受控渠道交付，归档权限 0600、导出目录 0700；不提交 Git、不公开分发。生成的 env 是 Compose 格式，脚本负责特殊字符转义，不通过 shell `source` 加载。人工更改值时保留正确引号。

便携包自动使用 manifest 中的固定 AI 工具镜像，无须另设 LICENSE_TOOLS_IMAGE。授权根仍为 `/opt/icp-diag/runtime/license`，下一步显式初始化。还需由客户确认真实、稳定的 `/etc/machine-id` 与 SELinux 挂载策略；准备脚本不造机器标识、不修改防火墙。

## 4. 单独初始化授权

确认所有本安装 Metor／AI、源码进程与旧初始化任务都已停止：

```bash
sudo python3 deployment/scripts/local-stack.py \
  --env-file /opt/icp-diag/runtime/config/docker.env license-init
sudo python3 deployment/scripts/local-stack.py \
  --env-file /opt/icp-diag/runtime/config/docker.env license-init
```

首次应为 `INITIALIZED`，重复为 `ALREADY_INITIALIZED`。工具在固定 AI 镜像内断网调用 SDK，生成安装身份、32 字节主密钥及两份初始 clock，设置目录权限；宿主不安装 SDK，不需手工写 JSON。保留整个 `/opt/icp-diag/runtime/license`，不 copy 演示环境的身份和 key。

失败保留现场。`OUTCOME_UNKNOWN` 需停写后用同命令核对重试；已完成身份缺件或损坏时不靠删除目录重建，按[备份恢复](../backup-restore.md)处理。

## 5. 迁移并按顺序启动

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

## 6. 客户访问入口与首管理员

默认前端监听 `0.0.0.0:18180`，局域网浏览器可使用客户主机 IP 访问；防火墙／安全组允许实际客户端来源。也可在操作电脑运行 SSH 隧道：

```bash
ssh -N -L 18180:127.0.0.1:18180 operator@customer-host
```

浏览器访问 `http://127.0.0.1:18180`。全新空用户库的第一次有效登录会创建首管理员；由授权实施人员先在受控入口完成，使用客户约定的强口令，再开放业务入口。已有库使用原管理员，无默认客户密码。

需要客户域名／TLS 时配置反向代理，统一代理页面与 API，并验收上传限制、长任务超时、路径和登录行为。同宿主代理可转发到 `http://127.0.0.1:18180`，远端代理使用客户主机 IP，并落实对应防火墙来源规则。发布端口由 FRONTEND_EXPOSED_PORT 配置。

Metor、AI 和 MySQL 保持本机维护端口，不为浏览器单独开放。入口方案、域名、证书续期负责人写入发行记录。

完成后进入[授权签发](03-license-issue.md)，再按[导入和最终验收](04-license-import.md)开通业务。

## 7. 已有环境更新

仅适用于已有完整 SDK 安装的 Linux 客户。保留数据库卷、业务文件、模型配置、密码、JWT 和整个 LICENSE_ROOT；原许可仍符合本次产品信任时无需重签。本机更新按[本机 deploy](../local-release/02-deploy.md)执行。

### 7.1 新包单独解压，不覆盖原运行目录

我方先按 [build](01-build.md)制作并验收新包。客户校验新 tar.gz 与 .sha256，在未占用的新版本目录解压，运行新包的 import-images.sh 导入镜像。保留旧包与旧镜像；**不运行 prepare-runtime.py**，不把新包的 customer.env 覆盖到原运行 env。

例如新包根为 `/opt/icp-diag/releases/release-20261028-1-amd64`，实际运行配置仍为 `/opt/icp-diag/runtime/config/docker.env`。下面在 Linux root 的同一 Bash 会话中定义两个绝对路径；换版本时只换新工具路径：

```bash
ICP_STACK=/opt/icp-diag/releases/release-20261028-1-amd64/deployment/scripts/local-stack.py
ICP_ENV=/opt/icp-diag/runtime/config/docker.env
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose config --quiet
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose ps
```

新脚本会自动调用同目录包内固定 Compose 和 manifest 中的 AI 工具镜像。不要复制新 deployment 单个文件到旧包、混用 manifest 与工具镜像；直接保留完整新包，并始终显式指定原 env。实际配置的 WORKSPACE_RUNTIME_DIR、LICENSE_ROOT、模型与清单路径须为原安装绝对路径。

### 7.2 备份后再改运行 tag

暂停入口、等待任务完成，停止所有外部源码写入与旧初始化任务，使用新工具备份旧运行版本：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" backup --keep-stopped \
  /opt/icp-diag/runtime/backups/before-release-20261028-1
```

备份目录必须不存在，成功后写入服务保持停止；失败停止升级。备份包含两库、文件、Chroma、私有配置与 SDK 状态；模型及旧镜像另行保留。备份 env 必须仍描述旧版本，已提前改 tag 时先用更新前配置核对恢复；不要把新 tag 误记成原运行版本。

在**原完整 runtime/config/docker.env** 只修改相应 AI_RUNTIME_IMAGE／METOR_IMAGE／FRONTEND_IMAGE，值按新包 manifest.images 的 reference 填写。MYSQL_IMAGE 保持原版本，除非本次明确包含数据库升级。无需改 compose.ai.yaml、compose.metor.yaml、compose.full-local.yaml 的兜底 tag；不拿制作 build.env 覆盖运行配置。

保留原密码、JWT、路径、端口和授权资料；不初始化、不删除 clock、不换身份。Shell 同名 *_IMAGE、METOR_PLATFORM、LICENSE_ROOT、LICENSE_TOOLS_IMAGE 变量可能覆盖直接 Compose／工具选择，文件配置方式下先清除这些残留 export。

### 7.3 迁移、重建和验收

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose config --quiet
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --wait mysql
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose run --rm --no-deps ai-migrate
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait ai-runtime
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait metor
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait frontend
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose ps
```

逐条成功再继续；核对实际容器镜像、健康、Metor／AI 各自 ACTIVE、原数据、真实检索与航空业务。restart 不加载新镜像、环境或挂载。验收后记录本次包摘要、镜像 ID、迁移版本与所用工具目录。

单服务更新也先导入相应新镜像并备份，只修改对应 *_IMAGE：

- 前端：普通 backup 自动恢复原服务后，只重建 frontend。
- Metor：普通备份后停止 frontend、metor，改 tag，再依次重建 metor、frontend，AI 保持原可用版本。
- AI：使用 --keep-stopped 备份，改 AI_RUNTIME_IMAGE，然后执行 ai-migrate → ai-runtime → metor → frontend。

单服务重建均用 `compose up -d --no-deps --wait <service>`；如果用了 --keep-stopped 停止所有写入者，就按全套顺序恢复它们。SDK、公开信任或两端契约改变时一起更新受影响服务。只改运行配置／挂载时使用 `--force-recreate`，仍遵循依赖顺序。

只回退兼容的业务镜像时保留当前最新授权资料、新工具及 manifest，按依赖顺序重建；已发生不兼容数据库／索引／文件迁移时，按[备份恢复](../backup-restore.md)在同宿主全新隔离目标恢复并对账。不能以旧 clock、重新初始化或 down -v 代替回退。
