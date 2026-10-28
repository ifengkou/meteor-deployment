# deploy：本机 Docker 更新

适用：已有完整运行配置、业务数据和授权安装的 `icp-diag-local`。先按 [build](01-build.md)制作 Linux ARM64 镜像，再执行本文。命令均从工作区根目录执行。

## 1. 检查部署环境

本机部署通过 desktop-stack.py 在 Linux 运维容器中执行原 local-stack.py。首次使用运维工具时制作工具镜像：

```bash
docker --context desktop-linux build --platform linux/arm64 \
  -f deployment/tools/Dockerfile.desktop \
  -t icp-diag-local-tools:py312-docker2751 deployment
```

运维镜像包含 Python 3.12、Docker CLI 27.5.1 和 Compose 2.33.0，使用本机 Docker Desktop 引擎。运行时挂载工作区、Docker socket 和配置的授权卷。

完整运行配置为 runtime/config/docker.env，权限 0600。核对并保留以下配置：

| 字段 | 要求 |
| --- | --- |
| WORKSPACE_RUNTIME_DIR | 当前工作区 runtime 的绝对路径 |
| DESKTOP_LICENSE_VOLUME | icp-diag-local-license |
| LICENSE_ROOT | 上述卷的实际 Mountpoint |
| LICENSE_TOOLS_IMAGE | 已核验 SDK 0.7.1 AI 工具镜像的完整 sha256 ID |
| LICENSE_MACHINE_ID_PATH | 本机无 Linux 宿主标识时使用约定的不存在路径 |
| METOR_PLATFORM | linux/arm64 |
| METOR_AEROSPACE_DECRYPTION_ENABLED | false |

```bash
docker --context desktop-linux volume inspect icp-diag-local-license --format '{{.Mountpoint}}'
python3 deployment/scripts/desktop-stack.py compose config --quiet
python3 deployment/scripts/desktop-stack.py compose ps
```

包装器默认读取完整 docker.env，不传递 Shell 的同名镜像或授权路径覆盖值。指定其他完整配置时，将 --env-file 放在子命令前。build.env 只用于制作，不传给部署命令。

核对新镜像。以下以 release-20261028-1-arm64 为例，每次发布换为实际唯一版本：

```bash
docker --context desktop-linux image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  ai-runtime-service:release-20261028-1-arm64 \
  metor-service:release-20261028-1-arm64 \
  metor-platform-frontend:release-20261028-1-arm64
```

各项应为 linux/arm64，已在当前 Docker 镜像库中的镜像无需 load。SDK／公开配置变更时先按 [SDK 升级要求](../license-sdk-upgrade.md)核对兼容性。

## 2. 备份当前版本

暂停业务入口，等待任务完成，停止 Mac 上直接运行的 Metor／AI 及其他外部写入进程。保持 docker.env 仍选择当前运行版本，使用未占用的备份目录：

```bash
python3 deployment/scripts/desktop-stack.py backup --keep-stopped \
  runtime/backups/before-release-20261028-1-arm64
```

备份包含两业务库、业务文件、Chroma、私有配置和完整授权状态。模型与旧镜像另行保留。确认备份成功后继续；--keep-stopped 会让应用保持停止。备份目录含凭据与业务资料，按私有资料保管。

## 3. 切换运行镜像

仅编辑现有 runtime/config/docker.env 的对应字段：

```dotenv
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261028-1-arm64
METOR_IMAGE=metor-service:release-20261028-1-arm64
FRONTEND_IMAGE=metor-platform-frontend:release-20261028-1-arm64
METOR_PLATFORM=linux/arm64
```

保留 MYSQL_IMAGE、数据库密码、JWT、模型、端口、业务目录、DESKTOP_LICENSE_VOLUME、LICENSE_ROOT 和授权资料。常规版本更新不执行 init 或 license-init。Compose YAML 中的 tag 是变量缺失时的兜底，不随发布修改。

LICENSE_TOOLS_IMAGE 保持已核验的兼容工具镜像；SDK 升级时按升级要求选择工具。回退业务镜像时也保留新版工具。

## 4. 迁移与重建

每条命令成功后再执行下一条：

```bash
python3 deployment/scripts/desktop-stack.py compose config --quiet
python3 deployment/scripts/desktop-stack.py compose up -d --wait mysql
python3 deployment/scripts/desktop-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/desktop-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/desktop-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/desktop-stack.py compose up -d --no-deps --wait frontend
python3 deployment/scripts/desktop-stack.py compose ps
```

ai-migrate 执行 AI Alembic schema 迁移；Metor 启动时执行 Flyway。up 应用新镜像、环境和挂载，restart 仅重启现有容器。MySQL 使用原数据卷和凭据。

## 5. 验收

```bash
curl --fail http://127.0.0.1:18180/healthz
curl --fail http://127.0.0.1:18080/actuator/health/readiness
curl --fail http://127.0.0.1:18092/internal/health/ready
```

核对实际容器镜像与健康状态，使用原账号登录，检查原业务记录、文件、规则和知识库检索。软件授权页面应显示 Metor／AI 各自 ACTIVE；有效原许可沿用，续期或更换许可按[授权导入](../customer-release/04-license-import.md)执行。本机使用约定的 UNBOUND 许可。

前端默认监听 0.0.0.0:18180，本机访问 http://127.0.0.1:18180，局域网使用宿主机 IP 并配置防火墙。Metor、AI、MySQL 维护端口保持回环地址。ARM64 不执行当前 x86-64 JNI DAT 解密验收。

## 单服务更新

先按 [build](01-build.md)制作对应镜像，完成普通一致性备份，再只改对应 *_IMAGE。普通 backup 会恢复原运行服务：

```bash
python3 deployment/scripts/desktop-stack.py backup \
  runtime/backups/before-single-service-release
```

下表的 compose 均通过 `python3 deployment/scripts/desktop-stack.py compose ...` 执行：

| 服务 | 更新顺序 |
| --- | --- |
| frontend | 修改 FRONTEND_IMAGE，执行 up -d --no-deps --wait frontend |
| metor | stop frontend metor，修改 METOR_IMAGE，再依次 up -d --no-deps --wait metor、frontend |
| ai-runtime | stop frontend metor ai-runtime，修改 AI_RUNTIME_IMAGE，再依次执行 ai-migrate、ai-runtime、metor、frontend |

涉及两端契约、SDK 或公开配置时一起更新受影响服务。使用 --keep-stopped 停止所有应用后，按全套顺序恢复它们。

## 配置更新

备份后修改运行配置，对受影响服务执行 `compose up -d --no-deps --force-recreate --wait <service>`，按 AI → Metor → 前端顺序恢复。模型权重、模型 ID 或归一化配置变化时，按 [Embedding 运维](../../../ai-runtime-service/docs/operations/embedding-models.md)处理索引。

## 版本回退

数据格式兼容时，将相应 *_IMAGE 恢复为已验收版本，按依赖顺序重建；保留当前最新授权资料、授权卷和部署工具。

数据库、索引或文件格式不兼容时，按[备份恢复](../backup-restore.md)的目标条件进行隔离恢复与对账。本机未配置稳定 Linux machine-id 时，不直接使用要求同宿主指纹的 restore-stack 自动恢复。保留现有数据卷及备份，不执行 down -v 或 volume prune。
