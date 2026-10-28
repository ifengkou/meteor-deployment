# ICP Diag 整栈部署

独立 deployment 工程与 frontend、metor-service、ai-runtime-service 同级，各仓库各自维护版本。业务工程维护源码和 Dockerfile，Docker 发布统一使用本工程。

## 先选择部署场景

| 场景 | 总入口 | build 阶段 | deploy 阶段 |
| --- | --- | --- | --- |
| 本机 Apple Silicon Docker Desktop，更新 icp-diag-local | [本机部署目录](docs/local-release/README.md) | [制作 Linux ARM64 镜像](docs/local-release/01-build.md) | [本机部署与更新](docs/local-release/02-deploy.md) |
| Linux AMD64 客户交付 | [客户交付目录](docs/customer-release/README.md) | [冻结版本、制作镜像、统一 tar.gz](docs/customer-release/01-build.md) | [客户首次部署与更新](docs/customer-release/02-deploy.md) |

两者均使用 SDK 0.7.1、CUSTOMER_REQUIRED。首次客户安装按 deploy 完成目录准备、授权初始化和启动；已有安装按更新流程保留配置、数据和授权资料。

客户签发、导入分别见[授权签发](docs/customer-release/03-license-issue.md)、[授权导入与验收](docs/customer-release/04-license-import.md)。构建成功、健康成功、商业许可有效是不同检查。

## 唯一配置与命令入口

命令从包含 deployment/、三个源码工程及 runtime/ 的工作区根目录执行；客户则从解包安装根目录执行。

- 制作配置：显式 `--env-file runtime/release/<版本>/build.env`，只用于本条 build／export 命令，不自动查找或合并。普通 build 输出当前 Docker 镜像库，不生成 dist 文件。
- 运行配置：完整 `runtime/config/docker.env`，0600，保存镜像、数据库密码、JWT、模型、授权、业务目录及端口。切版本只改对应 *_IMAGE，不修改 Compose 的兜底 tag；不拿 build.env／模板覆盖它。
- 本机 deploy：`python3 deployment/scripts/desktop-stack.py ...`，Linux 运维容器调用原部署脚本，处理 Docker Desktop 数值权限。首次先按本机 deploy 构建工具镜像。
- Linux 客户 deploy：`python3 deployment/scripts/local-stack.py ...`，客户包自动使用独立 Compose 2.33.0；系统 docker-compose 1.25.0 保留。

源码构建仍使用 Mac 上的 local-stack.py。完整参数位置、默认路径、公开配置指定方式及阶段边界见对应 build／deploy 文档。[配置说明](docs/configuration.md)只维护字段含义，不替代操作流程。

## Compose 服务名

| 服务名 | 镜像字段 |
| --- | --- |
| frontend | FRONTEND_IMAGE |
| metor | METOR_IMAGE |
| ai-runtime | AI_RUNTIME_IMAGE |
| ai-migrate（一次性数据库迁移） | AI_RUNTIME_IMAGE |
| mysql | MYSQL_IMAGE |

默认项目名 icp-diag-local；组合 compose.ai.yaml、compose.metor.yaml、compose.full-local.yaml，配置 WORKSPACE_RUNTIME_DIR 后追加共享 runtime overlay。不要逐个 YAML 单独启动另一套数据库。ai-migrate 不创建授权目录，不能替代 license-init。

## 交付包边界

统一包包括四镜像、完整 Embedding、获准复用的三项数据库密码／JWT、manifest 和校验清单；客户仍另备 Chat 服务和[业务资料](docs/customer-release/business-materials.md)。只从 customer-docs/ 白名单导出五份客户指南，本仓库 docs/ 的构建、过程与历史验证记录及本机工具不进入包。包不含客户安装身份、商业许可、业务数据、Issuer、私钥或口令。

## 文档

| 参考资料 | 用途 |
| --- | --- |
| [配置说明](docs/configuration.md) | 配置归属、路径、镜像字段与端口 |
| [更新入口](docs/updates.md) | 旧链接导航，转至本机／客户 deploy |
| [AMD64 构建细节](docs/amd64-build.md) | Apple Silicon 专用 Buildx、单组件归档、下载与缓存 |
| [AMD64 架构边界](docs/amd64.md) | JNI、真实 DAT 与原生客户验收 |
| [Linux 备份恢复](docs/backup-restore.md) | 一致性备份与同宿主空目标恢复 |
| [SDK 构建输入与升级](docs/license-sdk-upgrade.md) | 正式制品、公开信任兼容、已有 SDK 升级与回退 |
| [时间异常恢复](docs/license-recovery.md) | 单服务签名恢复 |
| [故障处理](docs/troubleshooting.md) | 缺挂载、权限、网络、健康和构建故障 |
| [授权机制](docs/license-implementation.md) | SDK 与产品职责及运行机制 |

customer-docs/ 保持自包含，便于离线交付。授权操作从 [license-guide](docs/license-guide/README.md) 的当前指引进入；源码运行和模型业务配置由各业务工程 README 维护。

## 宿主依赖与验证

客户管理脚本支持 Python 3.8.10+，目标 Docker 24.0.7，AMD64 包内独立 Compose 2.33.0；不要求客户安装 Python 3.12。源码构建及本机 Docker Desktop 依赖见本机 build／deploy。SDK／公开配置按两端 license-build/README.md 准备，忽略于 Git 的正式输入须在新检出／CI 单独准备。

部署工具回归测试从工作区根目录执行：

```bash
python3 -m pytest deployment/tests -q
```

不将真实 env、模型、SDK 私有输入、运行数据、数据库备份、客户样本或镜像归档加入 Git。已有运行环境不重新执行 init，不删除数据卷。
