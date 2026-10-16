# ICP Diag 整栈部署

此目录是与 `frontend/`、`metor-service/`、`ai-runtime-service/` 同级的独立部署工程，不是符号链接，不由任何业务工程持有。Git 仓库与远端由维护者配置，迁移操作不自动执行 Git 初始化、提交或推送。

所有发布统一使用这里的 stack。业务工程只维护源码开发、测试和 Dockerfile，不再使用各工程独立 Compose 发布。

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


页面默认入口为 `http://127.0.0.1:18180`。前端镜像 tag 不必与旧名称一致，架构需匹配 `METOR_PLATFORM`。

Metor 对应 `METOR_IMAGE`，AI 对应 `AI_RUNTIME_IMAGE`。更新后端前暂停新写入，等待运行任务结束，并做一致性备份。具体操作只维护在[日常更新](docs/updates.md)，不重新初始化、不删除数据卷。

## 文档

| 操作 | 文档 |
|---|---|
| 前端、Metor、AI 单独更新及回退 | [日常更新](docs/updates.md) |
| 唯一配置、目录和端口 | [配置说明](docs/configuration.md) |
| AMD64 镜像制作、打包、首次安装与 JNI | [AMD64 完整步骤](docs/amd64.md) |
| Buildx、下载与缓存 | [AMD64 构建细节](docs/amd64-build.md) |
| 同架构运行镜像导出 | [离线交付](docs/offline-deployment.md) |
| 一致性备份与隔离恢复 | [备份恢复](docs/backup-restore.md) |
| 常见错误 | [故障处理](docs/troubleshooting.md) |

AI 本地源码运行与模型业务配置仍由 AI 工程文档维护，不在这里复制。旧独立部署资料放在 `archive/standalone/`，只供历史对照，不运行其脚本。

## 宿主依赖与验证

部署管理需要 Python 3.9+、Docker Engine、Compose 2.24.4+，备份恢复使用 `tar`、`gzip`。脚本只用 Python 标准库，不要求宿主安装 JDK、Node 或 Python 业务依赖。

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
