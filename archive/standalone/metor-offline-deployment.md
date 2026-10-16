# metor-service 独立离线部署文档

当前全套部署采用 `icp-diag-local`，入口 `18180`，共用 MySQL 的 `metor_service` 与 `metor_ai` 业务库。请优先使用 [配置索引](../../ai-runtime-service/docs/operations/configurations.md) 和 [Docker 更新手册](../../ai-runtime-service/docs/operations/docker-updates.md)。本文仅保留 Metor + MySQL 的可选独立交付流程，示例 `phoenix` 与端口 `8080/3307` 不适用于当前整栈升级。

## 1. 适用范围

本文用于在完全无公网的 Linux 主机上部署 `metor-service`。目标环境只运行：

- `metor-service` 应用容器；
- MySQL 8.4 容器；
- MySQL 和业务文件两个 Docker Volume。

离线主机不需要 JDK、Gradle、Maven，也不能在离线主机执行 `docker compose build`。推荐在可联网且 CPU 架构与目标机一致的制品机完成构建，把应用镜像和 MySQL 镜像一起导出。

## 2. 部署前提

### 2.1 离线主机

最低要求：

- Linux x86_64 或 arm64；
- Docker Engine 24+；
- Docker Compose v2；
- 可用磁盘至少 20GB，实际容量按上传文件、报告和 MySQL 数据增长评估；
- 应用端口默认 `8080`；
- MySQL 宿主机映射端口默认 `3307`，应用容器内部始终访问 `mysql:3306`；
- 系统时区建议设为 `Asia/Shanghai`。

确认版本：

```bash
docker version
docker compose version
uname -m
df -h
```

### 2.2 架构必须一致

制品机和离线主机的镜像架构必须一致。制品机执行：

```bash
docker image inspect metor-service:0.1.0 \
  --format '{{.Os}}/{{.Architecture}}'
docker image inspect mysql:8.4 \
  --format '{{.Os}}/{{.Architecture}}'
```

常见映射：

| `uname -m` | Docker 架构 |
|---|---|
| `x86_64` | `linux/amd64` |
| `aarch64`、`arm64` | `linux/arm64` |

不要把 Apple Silicon 本机构建的 arm64 镜像直接交付给 x86_64 服务器。需要跨架构构建时显式使用 `docker buildx`，并在对应架构上完成启动验证。

## 3. 在联网制品机生成离线包

以下命令在项目根目录执行。

### 3.1 准备基础镜像

Dockerfile 使用 OpenJDK 21 的 Eclipse Temurin 发行版：

```bash
docker pull eclipse-temurin:21-jdk-jammy
docker pull eclipse-temurin:21-jre-jammy
docker pull mysql:8.4
```

国内网络可以先通过镜像代理拉取，再打回标准标签。Dockerfile 和 Compose 必须继续使用标准标签，避免生产配置绑定某个公共代理。

### 3.2 构建并验证应用镜像

构建上下文必须包含以下运行资产：

```text
runtime/ai631/conf/fault_scene.json
runtime/ai631/conf/readArg.json
runtime/ai631/lib/libEncryptAndDecrypt.so
```

配置 JSON 会进入镜像 `/opt/metor/ai631/conf`，不进入应用 JAR/classpath，也不需要在离线目录中
单独挂载。当前 `.so` 是 Linux AMD64 ELF：AMD64 构建会将其安装到 `/usr/local/lib` 并执行
`ldconfig`，ARM64 构建会排除该库。需要 JNI 解密的交付镜像必须使用 `linux/amd64` 构建。

Dockerfile 的 `metor-gradle` BuildKit cache 会在同一个 builder 中复用已下载的 Gradle 8.14
分发包和依赖。需要从本机 Gradle cache 预热并强制离线编译时，使用
`../ai-runtime-service/deployment/scripts/seed-gradle-cache.sh` 和 `M6_GRADLE_OFFLINE=1`；完整命令见 README。

在 `.env.docker` 中设置发布版本：

```text
METOR_IMAGE_TAG=0.1.0
```

构建：

```bash
./gradlew clean check integrationTest bootJar
docker compose --env-file .env.docker build --pull=false metor
docker image inspect metor-service:0.1.0
```

建议在导出前进行一次 Compose 冒烟验证：

```bash
docker compose --env-file .env.docker up -d
docker compose --env-file .env.docker ps
curl --fail http://127.0.0.1:8080/actuator/health/readiness
docker compose --env-file .env.docker down
```

`docker compose down` 不带 `-v`，不会删除验证期间的 Volume。需要全新验证环境时使用独立 Compose project name，不要删除正在使用的数据卷。

### 3.3 组装离线目录

```bash
export METOR_RELEASE=0.1.0
export OFFLINE_DIR="metor-service-${METOR_RELEASE}-offline"

mkdir -p "${OFFLINE_DIR}/images"
cp compose.yaml "${OFFLINE_DIR}/"
cp .env.docker.example "${OFFLINE_DIR}/.env.docker.example"
cp docs/offline-deployment.md "${OFFLINE_DIR}/"
cp docs/troubleshooting-guide.md "${OFFLINE_DIR}/"

docker save \
  --output "${OFFLINE_DIR}/images/metor-service-${METOR_RELEASE}.tar" \
  "metor-service:${METOR_RELEASE}"

docker save \
  --output "${OFFLINE_DIR}/images/mysql-8.4.tar" \
  mysql:8.4
```

离线运行不需要导出 JDK/JRE 镜像，因为应用已在联网制品机完成构建。只有计划在离线主机重新构建源码时才需要额外导出 Gradle 依赖和 JDK 镜像；生产部署不推荐这样做。

### 3.4 生成校验文件

macOS：

```bash
cd "${OFFLINE_DIR}"
find . -type f ! -name SHA256SUMS -exec shasum -a 256 {} \; \
  | LC_ALL=C sort -k2 > SHA256SUMS
cd ..
tar -czf "${OFFLINE_DIR}.tar.gz" "${OFFLINE_DIR}"
shasum -a 256 "${OFFLINE_DIR}.tar.gz"
```

Linux：

```bash
cd "${OFFLINE_DIR}"
find . -type f ! -name SHA256SUMS -exec sha256sum {} \; \
  | LC_ALL=C sort -k2 > SHA256SUMS
cd ..
tar -czf "${OFFLINE_DIR}.tar.gz" "${OFFLINE_DIR}"
sha256sum "${OFFLINE_DIR}.tar.gz"
```

通过受控介质传输压缩包及其外层 SHA-256。不要把真实 `.env.docker`、数据库备份或业务文件放入普通交付包。

## 4. 在离线主机安装

### 4.1 校验并解压

```bash
sha256sum metor-service-0.1.0-offline.tar.gz
tar -xzf metor-service-0.1.0-offline.tar.gz
cd metor-service-0.1.0-offline
sha256sum -c SHA256SUMS
```

所有文件必须显示 `OK`。校验失败时停止部署，重新传输制品。

### 4.2 加载镜像

```bash
docker load --input images/mysql-8.4.tar
docker load --input images/metor-service-0.1.0.tar

docker image inspect mysql:8.4 >/dev/null
docker image inspect metor-service:0.1.0 >/dev/null
```

### 4.3 创建环境配置

```bash
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

至少修改：

```text
MYSQL_DATABASE=phoenix
MYSQL_USER=keta
MYSQL_PASSWORD=<独立强密码>
MYSQL_ROOT_PASSWORD=<不同的独立强密码>
METOR_IMAGE_TAG=0.1.0
APP_EXPOSED_PORT=8080
MYSQL_EXPOSED_PORT=3307
```

注意：

- Compose 中应用通过 `mysql:3306` 访问数据库，不要把 `DB_URL` 改成 `localhost`；
- `@`、`-`、`_` 等字符可直接写在 `.env.docker` 值中，不要添加多余反斜杠；
- `.env.docker` 不进入 Git，不随普通日志或问题截图外发；
- MySQL Volume 首次初始化后，再修改 `.env.docker` 中的密码不会自动修改数据库内用户密码。

### 4.4 启动

```bash
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --no-build --pull never
docker compose --env-file .env.docker ps
```

离线环境必须使用 `--no-build --pull never`，确保 Docker 不尝试访问公网。

验证：

```bash
curl --fail http://127.0.0.1:8080/actuator/health/liveness
curl --fail http://127.0.0.1:8080/actuator/health/readiness
curl --fail http://127.0.0.1:8080/actuator/prometheus | head
```

预期两个容器均为 `healthy`，readiness 返回 `UP`。

## 5. 服务管理

```bash
# 查看状态
docker compose --env-file .env.docker ps

# 查看日志
docker compose --env-file .env.docker logs --tail=200 metor
docker compose --env-file .env.docker logs --tail=200 mysql

# 仅在配置和镜像未变化时重启进程，不重启数据库
docker compose --env-file .env.docker restart metor

# 停止并保留数据
docker compose --env-file .env.docker down

# 再次启动
docker compose --env-file .env.docker up -d --no-build --pull never
```

严禁在生产环境执行：

```bash
docker compose --env-file .env.docker down -v
docker volume rm <volume>
```

这些命令会删除数据库或业务数据卷。

## 6. 数据备份

### 6.1 MySQL 逻辑备份

```bash
mkdir -p backups
docker compose --env-file .env.docker exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump \
   -u root --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
  > "backups/phoenix-$(date +%Y%m%d-%H%M%S).sql"
```

检查备份非空：

```bash
test -s backups/phoenix-*.sql
```

### 6.2 业务文件 Volume 备份

先记录实际 Volume 名称：

```bash
docker volume ls | grep metor-data
```

使用应用镜像打包只读挂载的数据卷：

```bash
mkdir -p backups
docker run --rm \
  --entrypoint sh \
  -v metor-service_metor-data:/source:ro \
  -v "$PWD/backups:/backup" \
  metor-service:0.1.0 \
  -c 'tar -czf /backup/metor-data.tar.gz -C /source .'
```

如果 Compose project name 不是 `metor-service`，需要替换实际 Volume 名称。

## 7. 离线升级

1. 在联网制品机完成新版本测试并导出新应用镜像；
2. 传入离线主机并校验 SHA-256；
3. 升级前备份 MySQL 和业务文件；
4. `docker load` 新镜像；
5. 将 `.env.docker` 中 `METOR_IMAGE_TAG` 改为新版本；
6. 执行升级。

```bash
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --no-build --pull never metor
docker compose --env-file .env.docker ps
curl --fail http://127.0.0.1:8080/actuator/health/readiness
```

环境文件或镜像变更需要执行上面的 `up -d` 重新创建容器，不能只用 `restart`。

Flyway 会在应用启动时自动执行新迁移。迁移 SQL 一旦在任何共享环境执行，禁止修改原文件，只能新增更高版本迁移。

## 8. 回滚

应用代码回滚：

1. 保留上一版本应用镜像；
2. 将 `.env.docker` 的 `METOR_IMAGE_TAG` 改回上一版本；
3. 重新创建应用容器。

```bash
docker compose --env-file .env.docker up -d --no-build --pull never metor
```

数据库回滚不能仅靠切换镜像完成。若新版本执行了不可逆 Flyway 迁移，应按发布前演练的恢复方案使用备份恢复。禁止手工删除 `flyway_schema_history` 记录来伪造回滚。

## 9. 交付验收清单

- [ ] 应用和 MySQL 镜像架构与目标机一致；
- [ ] 压缩包及内部文件 SHA-256 校验通过；
- [ ] 离线主机未执行任何 `pull` 或 `build`；
- [ ] `.env.docker` 已修改且权限为 `0600`；
- [ ] `docker compose --env-file .env.docker config --quiet` 通过；
- [ ] 两个容器为 `healthy`；
- [ ] liveness、readiness 和 Prometheus 端点可访问；
- [ ] MySQL 与业务文件 Volume 已创建；
- [ ] 备份、升级和回滚步骤已演练；
- [ ] 部署包、密钥和备份按不同安全等级保存。
