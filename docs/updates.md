# Docker 更新操作

本文命令从工作区或安装根目录执行，操作当前 `icp-diag-local`，不接触旧项目。
源码构建时，三个业务工程与独立 `deployment/` 工程同级。运行预制镜像不要求业务源码。

## 配置位置

| 用途 | 本地开发 | 当前 Docker |
| --- | --- | --- |
| AI 环境变量 | 工作区 `runtime/config/ai.local.env`（`tools/local.sh` 加载）或显式指定环境文件 | 工作区 `runtime/config/docker.env` |
| AI 模型目录配置 | `AI_EMBEDDING_MODELS_CONFIG` 指向的 JSON；版本化示例为 `ai-runtime-service/config/embedding-models.example.json` | 上述 env 的 `AI_EMBEDDING_MODELS_CONFIG_HOST_PATH`，挂载 `/config/embedding-models.json` |
| Metor 环境变量 | `metor-service/.env.local`、`metor-app/src/main/resources/application-local.yml` | 同一 `runtime/config/docker.env` + `deployment/compose.metor.yaml` + `compose.full-local.yaml` |
| 前端接口代理 | `frontend/vite.config.ts` 和前端环境文件 | `frontend/deploy/default.conf.template`；`JAVA_UPSTREAM=metor:8080` |
| Compose 定义 | 源码 local 使用进程脚本，不另启独立 Compose | `deployment/compose.ai.yaml`、`compose.metor.yaml`、`compose.full-local.yaml` |
| 数据与文件 | 由各环境数据库 URL、storage 配置决定 | MySQL 命名卷；Metor、AI documents/Chroma 按共享宿主目录挂载 |

当前入口前端 18180、Metor 18080、AI 18092，MySQL 仅发布本机端口 13306；目标库为
`metor_service`、`metor_ai`。密钥、数据库密码和宿主权重路径只放私有 env。
不要复制 `.env.example` 覆盖活跃配置。具体本地启动方式以各仓 README 为准。

当前共享目录映射由 `WORKSPACE_RUNTIME_DIR` 启用 `compose.shared-runtime.yaml`；详情见 [配置索引](configuration.md)。更新和一致性备份前必须停止 local 的 AI/Metor。包装脚本检查 8080/8090，拒绝在 local 写入服务运行时备份。

## 更新前

1. 保存三个仓库的当前版本、镜像 tag/ID、Compose 文件和私有配置快照。
2. 将私有 `runtime/config/docker.env` 中要更新的 `AI_RUNTIME_IMAGE`、`METOR_IMAGE`、
   `FRONTEND_IMAGE` 改为新的唯一版本 tag；保留旧 tag。不要使用同名 tag 覆盖旧制品。
3. 检查变更是否含 Alembic/Flyway、模型配置或文件格式变更；数据库/模型升级必须有恢复方案。
4. 如修改了 Embedding 配置，先将新 JSON 放到新的宿主文件路径，再更新 env 的挂载路径；
   保存旧文件。不要在已绑定的文件上用原子替换后只重启容器，旧挂载可能仍指向旧文件。

以下命令中的备份目录每次使用新的绝对路径：

```sh
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py build
python3 deployment/scripts/local-stack.py backup --keep-stopped /absolute/protected/backup-before-release
```

`build` 不停止运行服务。备份短暂停写，包含两个业务库、Metor 文件、AI 文档与
Chroma、私有配置和校验清单，不重复保存模型权重。`--keep-stopped` 让原本运行的写入
服务在备份后保持停止，失败时也保持停止；备份失败必须排查，禁止继续迁移。
普通 `backup` 仅恢复备份前原本运行的服务，不启动原本停止的服务。

## 全套更新

完成上述构建和一致性备份后，按顺序执行：

```sh
python3 deployment/scripts/local-stack.py compose up -d --wait mysql
# 每次显式创建一次新的迁移任务，不能依赖上次退出成功的旧容器。
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
python3 deployment/scripts/local-stack.py compose ps
```

任一步失败即停止后续步骤。`--no-deps` 避免更新单个服务意外重建其他服务，但也跳过
Compose 依赖门禁，因此必须先完成迁移、AI readiness，再启动 Metor；Metor 启动时
执行 Flyway。迁移服务使用与 AI Runtime 相同的新镜像。未计划升级 MySQL 时保持其镜像
不变，不将 MySQL 版本升级混入普通应用发布。

验收至少覆盖登录、已有平台记录、文件访问、图谱、Excel 导入、独立检索及场景调用。
涉及知识库时验证真实文档检索，涉及模型时验证真实服务；不要将协议 fixture 记为真实模型。
确认通过后更新交付版本记录，可重新 `export` 生成离线镜像包。

## 仅更新单个服务

更新对应镜像 tag、检查配置并构建目标服务：

```sh
python3 deployment/scripts/local-stack.py build --service frontend
# 或 --service metor / --service ai；ai 对应 Compose 的 ai-runtime 与 ai-migrate。
```

- **前端**：`compose up -d --no-deps --wait frontend`，随后验证登录与页面。静态资源不改变
  数据库；若同时改 API 契约，按全套顺序更新相关后端。
- **Metor**：先执行一致性备份（普通 `backup` 会恢复原运行状态），然后
  `compose stop frontend metor`，再依次 `compose up -d --no-deps --wait metor` 和
  `compose up -d --no-deps --wait frontend`。有 Flyway 变更时必须确认对应 AI 版本兼容。
- **AI Runtime**：一致性备份后 `compose stop frontend metor ai-runtime`，然后依次执行
  全套更新中的 `ai-migrate`、`ai-runtime`、`metor`、`frontend` 四条命令。
  不能只重建 `ai-runtime` 而漏掉迁移；保留调用方停止状态直到 AI 就绪。

上文 `compose ...` 均为 `python3 deployment/scripts/local-stack.py compose ...` 的缩写。
失败时不继续启动入口，先检查对应服务日志。单服务更新不执行 `down`，不删卷。

## 仅更新配置

环境变量或 Compose 挂载变化必须执行 `up -d --no-deps --force-recreate --wait <service>`；
`restart` 不重新载入 Compose 环境或挂载。先备份配置及业务数据，再停止依赖方，按
AI → Metor → 前端恢复。只改前端变量只重建前端；AI 参数变化先验证模型目录和 readiness。
无需运行 `init`。模型 ID、权重或归一化配置变化可能要求重建 Chroma，按
[Embedding 运维](../../ai-runtime-service/docs/operations/embedding-models.md) 执行，不能仅修改指纹绕过验证。

## 回退与恢复

纯代码且数据格式兼容时，将 env 中对应镜像 tag 恢复旧版本，按相同依赖顺序重新创建服务。
保留原数据库卷及业务写入，不运行 `down -v`、`docker volume prune`。

数据库已执行不兼容迁移、索引或文件格式改变时，**只回退镜像不足以回退系统**。
停止写入，使用发布前一致性备份在全新隔离目标恢复；备份后的新增业务写入需先另行保存
并对账。不要对原卷盲目执行 downgrade 或覆盖导入。恢复演练使用独立配置及未占用端口：

```sh
python3 deployment/scripts/local-stack.py --project icp-diag-local-restore-check \
  --env-file /absolute/protected/restore-check.env compose up -d --wait mysql
python3 deployment/scripts/local-stack.py --project icp-diag-local-restore-check \
  --env-file /absolute/protected/restore-check.env restore-stack /absolute/protected/backup-before-release
```

演练 env 使用新端口、正确模型目录与备份中的数据库账号，权限 0600；恢复要求空库、空文件卷。
验证完整后再切换入口。详见 [备份恢复](backup-restore.md)。
