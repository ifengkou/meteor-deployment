# 整栈备份与恢复

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
