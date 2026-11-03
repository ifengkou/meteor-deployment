# Metor 双架构基础镜像缓存

普通 `local-stack.py build --service metor` 根据 build.env 的 `METOR_PLATFORM`，
为 JDK 和 JRE 分别维护两个平台的本地缓存 tag：

```text
icp-diag-base/eclipse-temurin:21-jdk-jammy-arm64
icp-diag-base/eclipse-temurin:21-jre-jammy-arm64
icp-diag-base/eclipse-temurin:21-jdk-jammy-amd64
icp-diag-base/eclipse-temurin:21-jre-jammy-amd64
```

缓存属于当前 Docker context。脚本检查镜像的实际 OS／架构，使用平台 manifest 的 ID
加 tag；仅有多架构索引、尚未下载目标平台配置不算命中。它会先保存本地公共 tag 已有的
两个平台内容，再拉取缺失平台。缓存命中时不执行 pull，构建通过 Dockerfile 的
`METOR_JDK_IMAGE`／`METOR_JRE_IMAGE` 参数引用本地 tag 及其 manifest digest，并使用 `--pull=false`。
同时使用 Docker 随附的 BuildKit frontend，避免外部 `docker/dockerfile:1` 的下载和解析差异。
固定 digest 与内置 frontend 一起避免非本机架构的本地 tag 远端重试；旧版镜像存储中无
RepoDigests 的本地自建镜像退回仅使用 tag。
构建不再需要解析公共 Temurin tag；Gradle 或 apt 仍可能联网。

提前准备两种架构，在工作区根目录执行：

```bash
python3 deployment/scripts/metor_base_images.py --platform linux/arm64
python3 deployment/scripts/metor_base_images.py --platform linux/amd64
```

之后按原命令构建，目标由各自 build.env 决定：

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261029-1-amd64/build.env build --service metor
```

更新 Java 基础镜像时显式刷新对应平台，然后重建应用镜像：

```bash
python3 deployment/scripts/metor_base_images.py --platform linux/amd64 --refresh
```

两种架构的刷新独立。不要删除这些缓存 tag 或执行清理未使用镜像的操作后仍期待零下载。

## 镜像代理缺 manifest

若 `docker.ketaops.cc/.../manifests/sha256:... not found`，表示代理无法提供所需内容。
脚本首先尝试 Docker Hub 的默认路径；失败时自动尝试明确的官方端点
`registry-1.docker.io/library/eclipse-temurin:...`，不修改 daemon 全局 mirror。
两条路径均失败会停止构建；修复网络或选择可访问的基础镜像后重试。

可以通过**进程环境变量**指定其他仓库或固定 digest：

```bash
METOR_JDK_IMAGE=registry.example.com/java:21-jdk \
METOR_JRE_IMAGE=registry.example.com/java:21-jre \
python3 deployment/scripts/metor_base_images.py --platform linux/amd64
```

构建时保留相同环境变量。自定义来源使用独立的带来源摘要的缓存 tag，避免误用旧来源；
自定义仓库失败时直接报错。Dockerfile 单独使用时可直接传同名 `--build-arg`。

## 专用 Buildx 归档

`build-amd64-images.sh` 使用 docker-container driver，不能直接读取上述 daemon 本地 tag。
它在自己的持久缓存中保存基础镜像和构建层，默认不加 `--pull`；需要主动检查新版基础镜像
时设置 `M6_PULL_BASE_IMAGES=1`。不清理 builder 就能保留其缓存，但缓存不保证所有远端元数据
查询都能离线完成。

该入口支持同名环境变量选择仓库。例如代理异常时：

```bash
METOR_JDK_IMAGE=registry-1.docker.io/library/eclipse-temurin:21-jdk-jammy \
METOR_JRE_IMAGE=registry-1.docker.io/library/eclipse-temurin:21-jre-jammy \
M6_BUILD_COMPONENTS=metor deployment/scripts/build-amd64-images.sh release-20261029-1-amd64
```

不要把 `icp-diag-base/...` 传给这个独立 builder。完整归档步骤见 [AMD64 构建细节](amd64-build.md)。

反过来，专用 builder 中已经下载过某个基础镜像时，可以用已记录、已验证的平台 digest
导入普通构建的缓存，避免重复下载层。例如将 `<digest>` 替换为已有 AMD64 JDK 的 digest：

```bash
docker buildx build --builder m6-amd64-builder --platform linux/amd64 \
  --pull=false --provenance=false --load \
  -t icp-diag-base/eclipse-temurin:21-jdk-jammy-amd64 -f - /tmp <<'DOCKERFILE'
FROM eclipse-temurin:21-jdk-jammy@sha256:<digest>
DOCKERFILE
```

JRE 同理，替换镜像名、缓存 tag 和对应 digest。此命令只导入基础镜像，不执行应用构建或部署。
