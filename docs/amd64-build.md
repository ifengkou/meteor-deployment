# 在 Apple Silicon 上隔离构建 Linux AMD64 镜像

## 目标与验证边界

本方案在 macOS M2 上使用独立的 `docker-container` Buildx builder 构建 M6 的三个 Linux AMD64
镜像。AMD64 基础镜像仅进入该 builder 的缓存，结果直接导出为 Docker archive；不执行
`docker pull --platform linux/amd64`、`--load` 或 `docker load`，因此不会改变本地 ARM64 镜像和 tag。

本阶段验证：

- AI Runtime 和 metor-service Dockerfile 的所有 build step 实际成功；
- MySQL 8.4 AMD64 制品可获取；
- 三个 archive 结构有效，镜像 config 均声明 `linux/amd64`；
- 生成每个 archive 的 SHA-256。

本阶段明确不验证：AMD64 容器启动、Compose 冷启动、健康检查、数据库迁移、备份恢复和断网重启。
这些项目需要 AMD64 Linux 主机，在正式发布环境验收。

## 前置检查

```bash
docker buildx inspect --bootstrap
docker info --format '{{json .RegistryConfig.Mirrors}}'
```

本机 builder 必须支持 `linux/amd64`。新建 builder 时，脚本自动读取 Docker daemon 配置中的第一个
Docker Hub mirror，并写入该 builder 的独立配置；没有 mirror 时使用官方仓库。可显式覆盖：

```bash
M6_DOCKERHUB_MIRROR=https://your-working-mirror.example.com \
deployment/scripts/build-amd64-images.sh 0.1.0
```

若同名 builder 已存在，脚本复用其原配置。要更换 mirror，应显式删除这个专用 builder 后重建；该
动作只删除专用 builder 缓存，不操作默认 Docker image store：

```bash
docker buildx rm m6-amd64-builder
```

## 执行构建

```bash
cd /Users/sloong/Workspace/github/icp_diag
deployment/scripts/build-amd64-images.sh 0.1.0
```

输出目录默认为：

```text
dist/m6-amd64-images-0.1.0/
├── ai-runtime-service_0.1.0_linux-amd64.tar
├── metor-service_0.1.0_linux-amd64.tar
├── mysql_8.4_linux-amd64.tar
└── SHA256SUMS
```

可以使用 `M6_IMAGE_OUTPUT_DIR` 修改输出位置。架构校验由标准库脚本
`inspect-docker-archive.py` 完成，不依赖 skopeo，也不把 archive 导入本地 Docker。

按组件续跑（不会重建未选中的组件）：

```bash
M6_BUILD_COMPONENTS="metor mysql" deployment/scripts/build-amd64-images.sh 0.1.0
```

脚本同时保存各组件的 `.build.log`、`.build-metadata.json` 和归档的 `.inspection.json`。构建先输出
`.tar.partial`，校验 config/层成员及 SHA-256 blob 后才替换正式归档；失败不会覆盖上次成功的 tar。
三个归档全部存在且校验通过才生成总 `SHA256SUMS`。这些检查不等价于运行验证。

metor 构建使用固定 id `metor-gradle` 的独立 BuildKit cache mount。未预热时，Wrapper 首次通过
官方 `services.gradle.org` 地址获取 Gradle 8.14；同一 builder 后续构建直接复用分发包和模块依赖，
Dockerfile 不再动态改写 `GRADLE_DISTRIBUTION_URL`。Docker Hub mirror 不代理 Gradle、PyPI 或
GHCR；首次填充这些缓存时仍需要相应网络，或使用下述本地缓存预热流程。

### Gradle 下载不稳定时：复用已验证缓存

若本机已有完整的 Gradle 8.14 分发目录及相同项目依赖缓存，可以先用以下命令填充**专用 builder**
的 `metor-gradle` cache mount，然后进行 Gradle 离线编译：

```bash
deployment/scripts/seed-gradle-cache.sh \
  /Users/sloong/.gradle/wrapper/dists/gradle-8.14-bin/38aieal9i53h9rfe7vjup95b9 \
  /Users/sloong/.gradle/caches/modules-2

M6_GRADLE_OFFLINE=1 M6_BUILD_COMPONENTS=metor \
  deployment/scripts/build-amd64-images.sh 0.1.0
```

将示例路径替换为自己的已验证缓存。脚本只复制 Gradle 8.14 分发目录、完成标记以及 modules-2 的
制品/元数据，不复制整个 Gradle 用户目录、`gradle.properties`、凭据、init script 或本机 JDK。
Java 编译仍由 AMD64 JDK 执行；缓存缺少依赖时 `--offline` 会明确失败，不会隐式下载或跳过编译。
`seed-gradle-cache.Dockerfile` 的版本/路径绑定于当前 wrapper 8.14，升级 wrapper 时需一起更新。
预热和构建必须使用同一个 builder；该流程不要添加全局 `--no-cache`，否则不能复用 cache mount。
这仅代表 Gradle 编译阶段离线，不代表整个镜像构建无网络（基础镜像和 apt 仍可能联网）。

手工复核：

```bash
python3 deployment/scripts/inspect-docker-archive.py \
  dist/m6-amd64-images-0.1.0/ai-runtime-service_0.1.0_linux-amd64.tar

cd dist/m6-amd64-images-0.1.0
shasum -a 256 -c SHA256SUMS
```

## 后续运行验收

获得 AMD64 Linux 主机后，再执行 `docker load`、双 Compose 冷启动、migration gate、readiness、账号
隔离和备份恢复测试。在此之前不应把“构建及归档验证通过”表述为“AMD64 运行验证通过”。
