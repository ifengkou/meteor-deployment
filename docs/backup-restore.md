# 整栈备份与恢复

本文宿主命令适用于已有完整 SDK 安装的 Linux root。macOS Docker Desktop 按[本机 deploy](local-release/02-deploy.md)使用 desktop-stack.py。自动恢复要求可读取相同宿主 machine-id。

以下命令从工作区或安装根目录执行，统一读取 `runtime/config/docker.env`。MySQL 使用命名卷，应用文件由相同 Compose 挂载读取；备份不依赖 MySQL 物理目录位于统一宿主目录。

## 一致性备份

先暂停新申报和摄取，等待运行任务结束，再执行：

```bash
python3 deployment/scripts/local-stack.py backup /absolute/protected/new-backup-directory
```

脚本短暂停止本项目的前端、Metor、AI 写入，导出 `metor_service`、`metor_ai`，保存 Metor 文件、AI 原文档、Chroma、私有配置和 SHA-256，之后恢复原来运行的服务。

每次使用尚不存在的新目录。备份目录为 0700，文件为 0600，包含凭据及业务数据，不提交 Git 或通用镜像包。模型权重、镜像、日志和临时目录不在业务备份内，需要另行保留模型与旧镜像，并将备份复制到受保护的异机存储。

更新维护窗口使用：

```bash
python3 deployment/scripts/local-stack.py backup --keep-stopped /absolute/protected/before-release
```

该模式让写入服务保持停止，备份失败也不自动恢复写入。失败时停止发布，保留现场。成功后按 AI、Metor、前端顺序恢复。

共享模式还会保存存在的 local 私有配置，并检查本机 8080／8090，防止源码进程继续写同一份数据。不要同时运行两套 AI 写同一 Chroma。

## 隔离恢复演练

仅验证授权目录时，使用 [SDK 0.7.1 授权资料专项演练](license-backup-validation.md)：在独立 Linux 卷和断网容器内，由程序断言原安装身份、密钥、许可、两端时间记录及数值权限。无需启动业务栈或人工复签；arm64 不代替客户 AMD64 验收。以下步骤用于整栈数据库和文件恢复。

不要覆盖现有运行库。使用独立项目、未占用端口、全新数据目录和数据库卷。先从备份准备独立的 0600 私有 env，核对旧镜像与模型身份，并修改 `WORKSPACE_RUNTIME_DIR` 指向新隔离根目录，不能继续使用原业务目录。所有模型清单及宿主路径也需核对。

```bash
python3 deployment/scripts/local-stack.py \
  --project icp-diag-local-restore-check --env-file /absolute/private/restore.env \
  compose up -d --wait mysql

python3 deployment/scripts/local-stack.py \
  --project icp-diag-local-restore-check --env-file /absolute/private/restore.env \
  restore-stack /absolute/protected/before-release

python3 deployment/scripts/local-stack.py \
  --project icp-diag-local-restore-check --env-file /absolute/private/restore.env \
  compose up -d --wait
```

恢复要求两个目标库和应用文件目录为空，并校验备份完整性。不要为通过检查清空原业务数据。跨架构使用逻辑 SQL 和文件归档，不搬运正在运行的 MySQL 物理数据目录。

恢复后核对数据库迁移版本、表数量、文件、用户登录、图谱、文档状态和真实检索。readiness 通过不等于数据对账完成。保留恢复前后产生的新写入，切换入口前单独对账。

`restore-metor` 仅用于首次导入原平台单库和文件，要求空目标，不作为日常全栈恢复或更新命令。不能重复用旧 phoenix 备份覆盖已运行的 metor_service。

## Chroma 重建

MySQL、原文档与原模型完整时，可使用整栈入口触发重建：

```bash
deployment/scripts/rebuild-chroma.sh
deployment/scripts/rebuild-chroma.sh --knowledge-base-id 12
```

执行前备份并暂停业务写入，重建后检查任务和真实检索。模型 ID、权重或归一化变化的规则见 AI 工程的[Embedding 运维](../../ai-runtime-service/docs/operations/embedding-models.md)。历史独立 backup／restore 脚本已归档，不用于当前栈。

## 授权资料随整栈备份保留

整栈备份保存私有 license-state.tar.gz，包含实际 LICENSE_ROOT 下的安装 UUID、service.key、商业许可及两服务时间记录（以及存在的恢复挑战）。该归档和清单均为 0600，目录为 0700，不能放入普通镜像发行包。文件锁不归档；发现临时文件、符号链接、未知文件、错误数值所有者或权限会拒绝备份。

当前宿主脚本只负责文件和归档检查，停止写入后的协议完整性由固定新版 AI 镜像内 SDK validate_installation 以只读挂载核验，不创建 Runtime 或打开锁，不因商业缺失／过期拒绝完整安装。停机前 preflight 仅检查文件系统。restore 先把原字节和权限写入独立 staging，经同一 SDK check 核对 installationId 后才发布。licenseState 仍严格保持 archive、installationId、machineIdSha256 三字段。

先导入新镜像，再运行新版备份工具。源码部署明确设置 LICENSE_TOOLS_IMAGE 为新 AI 镜像完整 ID；导出包使用 manifest 的 licenseToolsImage。即使回退 AI 业务镜像，这个工具 ID 和新版脚本仍保持不变。停止旧初始化任务和所有外部写入者是前提，不能依赖旧 flock 与 SDK record lock 互斥。完整步骤见 [SDK 升级与回退](license-sdk-upgrade.md)。

`LICENSE_ROOT` 与 `LICENSE_MACHINE_ID_PATH` 按 Compose 第一份配置所在的 `deployment/` 目录解析相对路径，支持字面的绝对/相对路径；不支持路径中再嵌套变量。进程环境中的同名变量与 Compose 一样优先。不要将备份输出放入授权目录。生产授权目录包含 root/21000、Metor 21001 和 AI 21002 的私有资料，执行整栈备份/恢复需具备 root 权限，使用原私有配置和对应 Docker 环境；脚本在停止服务或导入业务数据前预检权限。

恢复仅支持**同宿主、空授权目标**，应在 `license-init` 前执行：

1. 停止目标前端、Metor、AI（共享模式还需停止源码进程）；准备空业务库/文件卷及授权目录的可写父目录。
2. 在恢复 env 中显式设置隔离的 `LICENSE_ROOT`，与业务文件隔离路径一起核对，不能继续指向原运行授权目录。
3. 使用 `restore-stack`。脚本先检查 SHA-256、归档路径/类型、数值权限、安装/密钥/时间记录，再恢复原身份；非空目录一律拒绝，包括同安装的已有目录，避免覆盖更新的时间高水位。

备份清单额外保存配置的宿主 machine-id 的 SHA-256，自动恢复要求目标可读取同一标识；此项只是运维误操作保护，不能替代 SDK 机器绑定。无可读 machine-id 仍允许备份，但自动恢复授权到空目录会拒绝并要求人工处理。换宿主仍按原规则重新签发，不提供迁机。
