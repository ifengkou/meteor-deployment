# ICP Diag 整栈部署

此目录是与 `frontend/`、`metor-service/`、`ai-runtime-service/` 同级的独立部署工程，不是符号链接，不由任何业务工程持有。Git 仓库与远端由维护者配置，迁移操作不自动执行 Git 初始化、提交或推送。

所有发布统一使用这里的 stack。业务工程只维护源码开发、测试和 Dockerfile，不再使用各工程独立 Compose 发布。

交付包文档仅从 `customer-docs/` 的显式白名单导出，包含客户使用、安装、授权、业务配置和运维五份指南；本工程 `docs/` 下的研发过程、历史演示、构建与验收记录不进入客户包。

**客户正式交付从 [分阶段交付指南](docs/customer-release/README.md) 开始**：包含当前收口结论、构建、部署、授权签发、授权导入，以及模型与业务资料准备。历史演示部署记录不作为本次发行的验收结果。

## 唯一配置与命令入口

以下命令都从工作区根目录或安装根目录执行，即包含 `deployment/` 和 `runtime/` 的目录：

```bash
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose ps
```

唯一私有运行配置是 `runtime/config/docker.env`，权限为 `0600`。`deployment/.env.full-local.example` 只是模板，不能覆盖现有配置。旧 `.env.full-local`、各工程 `.env.docker` 不参与发布。

项目名保持 `icp-diag-local`，组合 `compose.ai.yaml`、`compose.metor.yaml`、`compose.full-local.yaml`。配置 `WORKSPACE_RUNTIME_DIR` 后自动叠加 `compose.shared-runtime.yaml`。不要逐个 Compose 文件单独启动另一套数据库。

源码工作区使用已有 `runtime/`；Linux 新主机安装根目录为 `/opt/icp-diag`，应用数据、模型、日志和工作文件归入其 `runtime/`，MySQL 保留命名卷。迁移部署工程不迁移正在运行的数据目录，不重建服务。

## Compose 服务名

发布、停止或查看日志时，命令最后填写下表的服务名，不是工程名、镜像名或容器全名。例如 Java 后端填写 `metor`，不能填写 `metor-service`。

| 服务 | 命令中的服务名 | 镜像配置变量 |
|---|---|---|
| 前端 | `frontend` | `FRONTEND_IMAGE` |
| Java 后端 | `metor` | `METOR_IMAGE` |
| AI 服务 | `ai-runtime` | `AI_RUNTIME_IMAGE` |
| AI 数据库迁移任务 | `ai-migrate` | 与 AI 服务共用 `AI_RUNTIME_IMAGE` |
| MySQL | `mysql` | `MYSQL_IMAGE` |

查看当前已创建容器对应的服务名，尚未创建的一次性迁移任务可能不在输出中：

```bash
python3 deployment/scripts/local-stack.py compose ps --all --services
```

例如，修改 `runtime/config/docker.env` 中的 `METOR_IMAGE` 并完成升级前备份后，更新 Java 后端使用：

```bash
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
```

`ai-migrate` 是一次性任务，使用 `compose run --rm --no-deps ai-migrate` 显式执行，不作为常驻服务发布。AI 升级的迁移与启动顺序见[日常更新](docs/updates.md)。

## 已有镜像如何发布

前端构建好镜像后，只在 `runtime/config/docker.env` 修改：

```dotenv
FRONTEND_IMAGE=precision-workspace:release-20261016001
```

执行：

```bash
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```


前端默认监听 `0.0.0.0:18180`，本机可访问 `http://127.0.0.1:18180`，局域网使用宿主机 IP，并允许对应防火墙／安全组来源。前端镜像 tag 不必与旧名称一致，架构需匹配 `METOR_PLATFORM`。

Metor 对应 `METOR_IMAGE`，AI 对应 `AI_RUNTIME_IMAGE`。更新后端前暂停新写入，等待运行任务结束，并做一致性备份。具体操作只维护在[日常更新](docs/updates.md)，不重新初始化、不删除数据卷。

## 文档

本机最新验证与清理结果见 [2026-10-26 Linux ARM64 交付验证](docs/arm64-local-validation-20261026.md)。新项目 18183 与原开发项目 18180 并存。

| 操作 | 文档 |
|---|---|
| 前端、Metor、AI 单独更新及回退 | [日常更新](docs/updates.md) |
| 唯一配置、目录和端口 | [配置说明](docs/configuration.md) |
| AMD64 镜像制作、打包、首次安装与 JNI | [AMD64 完整步骤](docs/amd64.md) |
| Buildx、下载与缓存 | [AMD64 构建细节](docs/amd64-build.md) |
| 同架构运行镜像导出 | [离线交付](docs/offline-deployment.md) |
| 一致性备份与隔离恢复 | [备份恢复](docs/backup-restore.md) |
| SDK 0.7.1 首次安装、既有安装升级与回退 | [授权 SDK 升级](docs/license-sdk-upgrade.md) |
| 新 SDK 独立容器实部署、访问方式及复杂步骤记录 | [0.7.1 容器部署记录](docs/sdk071-container-deployment.md) |
| 常见错误 | [故障处理](docs/troubleshooting.md) |
| 授权生成、签发、校验、防回拨与恢复原理（Mermaid） | [授权机制实现逻辑](docs/license-implementation.md) |

AI 本地源码运行与模型业务配置仍由 AI 工程文档维护，不在这里复制。旧独立部署资料放在 `archive/standalone/`，只供历史对照，不运行其脚本。

## 宿主依赖与验证

### 离线授权初始化与当前能力

产品固定使用正式 SDK **0.7.1**，我方 Issuer 当前版本 **0.4.0**；两者继续使用 v1 商业许可与恢复协议。
制作方从 SDK Release 准备制品，并将本产品 Issuer 下载的同一份 `license-product.json` 原字节用于两端构建：
[Metor 授权构建](../metor-service/license-build/README.md)、[AI 授权构建](../ai-runtime-service/license-build/README.md)。
客户不需要 SDK 包、发行制作工具或签发私钥；客户镜像的模式、信任和 API 清单摘要已在制作期固定，运行环境变量不能替换。

**当前完整包首次安装顺序：校验 tar.gz 与解压 → 导入完整镜像 → root 运行 `python3 deployment/scripts/prepare-runtime.py` → 单独 `license-init` → 启动业务 → 取得申请、签发、导入。** export 自动纳入完整 Embedding，并复用工作区 runtime/config/docker.env 的三项数据库密码及 JWT；目标机镜像、路径、目录与权限由准备脚本落实。完整命令见[客户部署](docs/customer-release/02-deploy.md)。
便携包先运行包内 `deployment/scripts/import-images.sh`，再由 `prepare-runtime.py` 准备配置。旧 init 仍供源码本地开发使用，不用于当前完整客户包首次安装。
源码部署还需将已评审 AI 工具镜像的不可变 ID 写入 `runtime/config/docker.env`：

```dotenv
LICENSE_ROOT=/opt/icp-diag/runtime/license
LICENSE_TOOLS_IMAGE=sha256:<已评审的本地AI镜像完整64位ID>
```

镜像 ID 用 `docker image inspect --format '{{.Id}}' ai-runtime-service:<release>` 查询，不能填浮动 tag。
便携包通过 `manifest.licenseToolsImage` 自动固定工具镜像，不要求客户另选一份；
manifest 的 `licensing` 同时记录 SDK 版本、正式制品摘要和公开配置摘要，镜像导入前后均需通过包内核验。 新导出还记录各镜像 configId（归档配置原字节摘要），以兼容经典 Docker 与 containerd 镜像存储的 ID 表示差异；运行时仍解析为已核准的不可变本地 ID。

在停止 Metor、AI、本机业务进程及所有旧初始化任务后，执行：

```bash
sudo python3 deployment/scripts/local-stack.py --env-file /absolute/runtime/config/docker.env \
  license-init
```

宿主命令只使用 Python 标准库与 Docker，在固定 AI 镜像内调用 SDK 初始化器，使用
`--pull=never`、`--network=none`，不启动 AI 主程序、数据库或模型服务；不在宿主安装 SDK。
需要 root 设置数值所有者。Metor UID/GID 为
`21001:21001`，AI 为 `21002:21002`，共同读取组为 `21000`。已有账号 ID 冲突或
目录权限不符时明确失败，不递归修改无关数据。升级既有安装前，应在隔离环境核对
原业务卷的数值所有者与新镜像的读写权限；初始化命令只管理许可目录，不迁移业务卷。

身份、32 字节安装主密钥及两端初始 clock 全部由 SDK 生成，工具只落实受审的目录权限。
正常首次结果为 `INITIALIZED`，重复核对为 `ALREADY_INITIALIZED`。合法 SDK draft 可续作；
旧 `.identity-stage-*` 或其他孤立资料拒绝自动处理，保留现场人工检查。若 SDK 已完成、权限收尾失败，
保留资料并在停止写入后重试同一命令，不删除目录。完成安装缺少 key 或 clock 时不会补造。
普通应用启动也不会自动初始化或修复这些资料，操作者不用手工制作文件。

首次启动后，管理员在“设置 → 软件授权”取得申请，交我方 Issuer 签发，再从同页导入。
只有 Metor 通过 SDK 发布共享商业许可；SDK 在原子发布前设置并确认共享组和 `0640`，AI 只读本地验证。
SDK 的 `start()`／`close()` 管理时间检查点，产品不再有另一套 HMAC／商业导入事务或 checkpoint 循环。
商业许可异常不替代健康检查，也不令应用退出。

Compose 保持身份只读、共享许可仅 Java 可写及两端状态隔离。入口仅在真实宿主
machine-id 文件存在时选择 `compose.license-host.yaml`；可用 `LICENSE_MACHINE_ID_PATH`
指定实际来源。缺少该文件不自动生成替代标识，合法无绑定许可无需机器标识。

已有完整安装升级保留整个授权目录，不重新 init、不换身份、不重新签发正常旧许可。
故障回退旧业务镜像时保留最新 clock，并继续使用新版部署工具及固定工具镜像；备份的协议完整性核验只调用 SDK 只读 `check`。
SDK 新 record lock 与旧安装器 flock 不构成相互排斥，不能同时运行；工具只能检测已知业务写入者，操作者仍须停止外部旧任务。
旧客户全部公开信任的兼容核对、人工页面操作和目标 Linux AMD64 验收须单独记录，不能以通用 SDK 测试或 ARM64 结果代替。

客户部署管理支持 Python 3.8.10+，AMD64 导出包固定携带 Compose v2.33.0，统一入口自动调用包内工具；系统 Docker 24.0.7 与 docker-compose 1.25.0 可保留。源码开发入口继续使用 `docker compose`（2.24.4+）。备份恢复使用 `tar`、`gzip`。脚本只用 Python 标准库，不要求宿主安装 JDK、Node 或 Python 业务依赖。

无需 Docker 的脚本安全测试：

```bash
python3 -m unittest discover -s deployment/tests -p test_local_stack.py
```

部署资产的补充测试使用 pytest，仅供开发验证，不是目标机运行依赖：

```bash
python3 -m pytest deployment/tests/test_deployment_assets.py
```

首次新环境可使用 `init`，已有配置禁止重新生成。源码构建要求三仓同级，便携部署包不需要源码；脚本路径不依赖执行时当前目录，但示例统一从工作区或安装根目录执行。

## 独立仓库迁移交接

部署文件已从业务工程迁到此真实目录，旧独立发布资料保存在 `archive/standalone/`。业务仓库中对应文件会表现为删除，部署目录需由维护者建立专用 Git 仓库后保存；不要只提交业务仓库的删除而漏掉新部署仓库。

本次迁移不初始化 Git、不提交、不推送、不重建容器，唯一运行配置仍为原来的 `runtime/config/docker.env`。原 `deployment/.env.full-local` 已保留到工作区 `runtime/backups/deployment-migration-20261016/deployment.env.full-local`，权限 0600，不作为运行配置。用户已有的 Metor `.env.docker` 保留但不读取。

提交部署仓库前检查忽略规则，不加入私有 env、运行数据、客户样本、镜像归档或数据库备份。模型清单示例和占位 env 模板可提交，真实密钥只保存在安装根目录的私有 runtime 中。

### 时间异常恢复

使用 SDK 0.7.1 的同一服务 Runtime，Metor 与 AI 独立在线恢复。操作步骤、手抄申请及错误处理见 [中文恢复手册](docs/license-recovery.md)。AI 维护客户端已包含在镜像内，宿主无需安装授权 SDK。

### 离线授权图解手册

打开 [八主题可视化入口](docs/license-guide/index.html)，或查看[文件目录](docs/license-guide/README.md)。这些 HTML 保留为 2026-10-23 的 SDK 0.6.0 历史讲解；
当前接入、安装和升级以 [SDK 升级手册](docs/license-sdk-upgrade.md) 及上述新构建说明为准，不运行旧初始化或 DER 输入示例。
全部 HTML 可离线打开，无需启动业务服务；时间页交互仅为教学模型。
