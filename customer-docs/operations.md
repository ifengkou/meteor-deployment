# 运维

以下在 Linux root 运维会话执行。保留项目名 icp-diag-local、原数据库卷、业务目录、模型、授权目录及完整运行配置。日常更新不执行 init 或 license-init，不执行 down -v 或 volume prune。

## 命令入口

每个运维终端先设置当前完整发行包中的脚本路径和原运行配置路径。首次安装的默认值如下；升级后将 ICP_STACK 改为新发行包内脚本的绝对路径，ICP_ENV 仍指向原配置：

```bash
ICP_STACK=/opt/icp-diag/deployment/scripts/local-stack.py
ICP_ENV=/opt/icp-diag/runtime/config/docker.env
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose config --quiet
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose ps
```

本文及其他指南中的 ICP_STACK／ICP_ENV 均使用上述已核对的值。脚本自动调用所选发行包内的固定 Compose 和 manifest 指定的 AI 工具镜像，不修改系统 Docker／Compose。

## 状态与日志

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose logs --tail=150 metor
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose logs --tail=150 ai-runtime
curl --fail http://127.0.0.1:18180/healthz
curl --fail http://127.0.0.1:18080/actuator/health/readiness
curl --fail http://127.0.0.1:18092/internal/health/ready
```

端口使用实际 env 配置。日志和备份按私有资料保管，不公开完整 Compose 展开配置。应用数据、日志和工作文件位于 runtime，MySQL 使用命名卷；同一 Chroma 只由一个 AI 实例写入。

## 一致性备份

暂停新业务并等待任务结束，使用尚不存在的备份目录：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" backup /opt/icp-diag/runtime/backups/backup-001
(
  cd /opt/icp-diag/runtime/backups/backup-001
  sha256sum -c SHA256SUMS
)
```

工具短暂停止写入服务，备份两业务库、业务文件、Chroma、私有配置和完整 SDK 授权状态，再恢复原运行服务。维护期间需要保持应用停止时使用 backup --keep-stopped；此模式下失败也保持停止，核对成功后再继续。

已启用航空诊断文件挂载的环境，按[航空诊断文件配置](business-config.md#航空诊断文件配置)另行备份实际的宿主机配置目录，并与本次备份一并保留。

备份不包含模型权重和镜像，另行保留发行包、原镜像和对应模型。备份包含密码与安装主密钥，存放于受保护的异机介质。

## 全套应用更新

### 1. 校验新包并导入镜像

新包解压到未使用的独立版本目录，不覆盖原 runtime。以下版本和归档名为示例，换成实际发行值：

```bash
ICP_RELEASE=release-20261028-1-amd64
ICP_BUNDLE="/opt/icp-diag/releases/${ICP_RELEASE}"
cd /absolute/transfer
sha256sum -c "icp-diag-${ICP_RELEASE}.tar.gz.sha256"
mkdir -p /opt/icp-diag/releases
mkdir "$ICP_BUNDLE"
tar --no-same-owner -xzf "icp-diag-${ICP_RELEASE}.tar.gz" \
  --strip-components=1 -C "$ICP_BUNDLE"
sh "$ICP_BUNDLE/deployment/scripts/import-images.sh" "$ICP_BUNDLE"
```

已有安装不运行 prepare-runtime.py，不用新包配置覆盖原运行 env。每个发行包中的脚本、Compose 和 manifest 配套使用，不单独复制某个脚本到其他包。原 env 中业务目录、模型、清单和 LICENSE_ROOT 保持原安装绝对路径。

### 2. 备份原运行版本

确认新旧版本兼容，暂停入口并等待任务结束。沿用当前部署的 `ICP_STACK` 和 `ICP_ENV`，此时 env 仍选择原镜像。使用尚不存在的备份目录，执行备份并校验：

```bash
ICP_BACKUP="/opt/icp-diag/runtime/backups/before-${ICP_RELEASE}"
python3 "$ICP_STACK" --env-file "$ICP_ENV" backup --keep-stopped \
  "$ICP_BACKUP" &&
  (cd "$ICP_BACKUP" && sha256sum -c SHA256SUMS)
```

已启用航空诊断文件挂载时，同时完成上述宿主机配置目录备份。备份和校验成功后再切版本。保留旧包、旧镜像和对应模型。

### 3. 切换部署入口和应用镜像

将 `ICP_STACK` 切换到目标发行包的脚本，`ICP_ENV` 仍指向原运行配置。

```bash
ICP_STACK="$ICP_BUNDLE/deployment/scripts/local-stack.py"
```

只修改原 runtime/config/docker.env 中的以下字段，值取自新包 manifest.json 的 images.reference：

| 字段 | 使用该镜像的服务 |
| --- | --- |
| AI_RUNTIME_IMAGE | ai-runtime、ai-migrate |
| METOR_IMAGE | metor |
| FRONTEND_IMAGE | frontend |

MYSQL_IMAGE 保持原版本，数据库升级另行安排。保留密码、JWT、端口、模型、业务路径和整个授权目录；不修改 Compose YAML 的兜底 tag，不用制作 build.env 覆盖运行配置。按文件配置操作时，确保 Shell 没有覆盖这些字段的同名 export 变量。

目标版本要求迁移配置时，按该版本的升级说明完成迁移，再重建受影响的服务。

### 4. 迁移并重建

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose config --quiet
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --wait mysql
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose run --rm --no-deps ai-migrate
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait ai-runtime
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait metor
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait frontend
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose ps
```

逐条成功后再继续。ai-migrate 仅执行 AI 数据库 schema 迁移；Metor 启动时执行 Flyway。核对实际容器镜像、健康、原账号和业务数据，按[软件授权](license.md)确认授权，再验收真实业务和检索。

打开前端的「系统信息」，核对三个应用的版本和 Git 提交 ID 与新包 `manifest.json` 中的 `version`、`revision` 一致。版本信息刷新告警单独处理，服务启动结果以 Compose 和健康检查为准。

后续运维继续使用本次选定的 ICP_STACK 和原 ICP_ENV；将所用发行包路径与版本交接给运维人员。

## 单服务更新与配置变更

### 用镜像 tar 更新 Metor 和 Frontend

适用于已部署的 Linux AMD64 环境，且本次交付物为服务镜像 tar 和 `SHA256SUMS`。 当前 Compose 需支持自动创建航空诊断配置目录。仍使用旧版 Compose 且目录不存在时，先按发行说明升级部署资产。从[命令入口](#命令入口)设置当前部署使用的 `ICP_STACK` 和 `ICP_ENV`。沿用现有部署脚本、Compose、AI Runtime、MySQL、模型及授权资料。以下版本号、文件名和路径按实际交付填写。每条命令成功后再继续。

1. 在客户主机校验收到的文件、导入两个镜像，再确认实际架构为 `linux/amd64`。记录输出的镜像 ID，并保留旧镜像以备回退。

   ```bash
   RELEASE=release-20261116-1-amd64
   cd /absolute/transfer
   sha256sum -c SHA256SUMS
   docker load --input "metor-service_${RELEASE}_linux-amd64.tar"
   docker load --input "frontend_${RELEASE}_linux-amd64.tar"
   docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
     "metor-service:$RELEASE" "metor-platform-frontend:$RELEASE"
   ```

2. 暂停入口、等待在途任务完成并停止外部写入。用仍指向旧镜像的运行配置备份，使用尚不存在的备份目录。普通 `backup` 会短暂停止写入服务，随后恢复原运行服务。已启用航空诊断文件挂载时，按[一致性备份](#一致性备份)一并备份宿主机配置。

   ```bash
   ICP_BACKUP="/opt/icp-diag/runtime/backups/before-$RELEASE"
   python3 "$ICP_STACK" --env-file "$ICP_ENV" backup "$ICP_BACKUP"
   (cd "$ICP_BACKUP" && sha256sum -c SHA256SUMS)
   ```

3. 备份验证通过后，记下旧 tag，在原有 `$ICP_ENV` 文件中修改以下两项。保留其余设置。

   ```dotenv
   METOR_IMAGE=metor-service:release-20261116-1-amd64
   FRONTEND_IMAGE=metor-platform-frontend:release-20261116-1-amd64
   ```

4. 校验 Compose 配置，停止并依次重建 Metor 和 Frontend。Metor 在启动时执行 Flyway。对照第 1 步的镜像 ID 核对实际容器镜像，验证登录和业务操作后恢复入口。

   ```bash
   unset METOR_IMAGE FRONTEND_IMAGE
   python3 "$ICP_STACK" --env-file "$ICP_ENV" compose config --quiet
   python3 "$ICP_STACK" --env-file "$ICP_ENV" compose stop frontend metor
   python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait metor
   python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --wait frontend
   python3 "$ICP_STACK" --env-file "$ICP_ENV" compose ps
   ```

### 只更新一个服务

只收到一个服务的镜像 tar 时，按上面的步骤校验并导入该镜像、备份原环境并修改对应的镜像 tag。继续使用当前的 `ICP_STACK` 和 `ICP_ENV`。收到完整发行包时，按[全套应用更新](#全套应用更新)第 1–3 步校验、导入、备份和切换部署入口，只修改本次更新服务的 tag。随后按下表重建服务，Compose 命令均接在 `python3 "$ICP_STACK" --env-file "$ICP_ENV" compose` 后。

| 服务 | 运行配置与重建顺序 |
| --- | --- |
| Frontend | 普通备份后修改 `FRONTEND_IMAGE`，执行 `up -d --no-deps --wait frontend`。 |
| Metor | 普通备份后修改 `METOR_IMAGE`，执行 `stop frontend metor`，再依次重建 `metor`、`frontend`。 |
| AI Runtime | 备份时使用 `--keep-stopped`，修改 `AI_RUNTIME_IMAGE`，按全套更新第 4 步执行 `ai-migrate`，再依次恢复 `ai-runtime`、`metor`、`frontend`。 |

若用 `--keep-stopped` 停止了所有应用，按全套更新的启动顺序恢复服务。SDK、公开配置或两端契约变化时按对应升级说明更新受影响服务，并完成所需的配置迁移。

### 修改环境变量或挂载

环境变量或挂载变化需重建对应容器，例如：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --force-recreate --wait metor
```

restart 不读取新的镜像选择、环境或挂载。

## 回退与恢复

数据格式兼容时，在原 env 恢复已验收的镜像 tag，按依赖顺序重建，保留当前最新授权身份、许可、clock 和部署工具。

数据格式不兼容时，停止写入并保留现场，由实施人员使用 restore-stack 在同宿主隔离空目标恢复，再做数据对账。目标需具备可读取的同一宿主 machine-id、独立数据路径及未占用端口；两个业务库、业务文件和授权目标为空，应用保持停止，且不先执行 license-init。恢复配置使用备份对应的数据库账号、密码和模型。

恢复目标启用航空诊断文件挂载时，在目标 env 中设置独立的 `METOR_RULES_CONFIG_HOST_PATH`，并在执行 restore-stack 前恢复单独备份的配置。备份源没有现场覆盖文件时，Metor 在启动时使用内置默认配置。

跨架构使用逻辑 SQL 和文件备份，不复制运行中的 MySQL 物理目录。过旧时间记录按[软件授权](license.md)处理，不使用旧 clock 覆盖运行状态。

## 日常检查

定期检查宿主 UTC、磁盘容量、服务健康、授权期限、备份校验和恢复演练结果。维护域名、证书、防火墙及模型服务网络，核对真实检索和航空业务结果。需要服务方协助时，提供版本、时间、请求编号和经过脱敏的相关日志。
