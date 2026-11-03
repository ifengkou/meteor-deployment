# Apple Silicon 隔离制作 Linux AMD64 归档

本文只维护专用 Buildx builder、单组件归档、下载源和缓存细节。客户 AMD64 输入、普通构建、版本冻结及统一组包以[客户 build](customer-release/01-build.md)为准；本机 ARM64 制作另见[本机 build](local-release/01-build.md)。本文不维护安装／更新命令。

## 适用范围与边界

在 Apple Silicon 上使用独立的 docker-container builder 制作 AMD64 归档，结果通过 type=docker 输出为 tar。基础镜像留在 builder 缓存中，不执行 --load、docker pull 或 docker load，不改变日常 ARM64 镜像和 tag。

脚本固定使用 linux/amd64，不读取 build.env。ARM64 本机构建直接使用[本机 build](local-release/01-build.md)的 local-stack.py build。制作成功及 archive 校验仅证明构建结果和声明架构，不证明原生 AMD64 运行或真实 DAT 解密通过。

## 1. 前置检查与专用 builder

从四工程工作区根目录、在 Bash 会话中执行；任一步失败先停止。SDK 0.7.1 和正式公开配置先按[输入清单](customer-release/01-build.md#1-冻结源码及外部输入)准备。

```bash
docker buildx version
docker info --format '{{json .RegistryConfig.Mirrors}}'
```

build-amd64-images.sh 默认创建或复用 m6-amd64-builder，使用 docker-container driver，并检查 builder 支持的目标平台。首次创建时，它读取 Docker daemon 的第一个 Docker Hub mirror；没有 mirror 时使用官方仓库。可显式指定：

```bash
M6_DOCKERHUB_MIRROR=https://your-working-mirror.example.com \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64
```

已存在的 builder 复用原配置。需要改 mirror 且确定不再需要其缓存时，可以先移除这个专用 builder，再由制作脚本创建；不操作默认镜像库：

```bash
docker buildx rm m6-amd64-builder
```

自定义 builder 名称使用 M6_BUILDER_NAME，后续组件、前端和缓存预热必须使用同一个 builder。

归档脚本默认复用缓存，不强制 `--pull`；主动更新基础镜像时设置 `M6_PULL_BASE_IMAGES=1`。
普通 local-stack.py 构建的 ARM64／AMD64 基础镜像 tag 与该 builder 缓存相互独立。
Metor 的镜像源参数和代理缺 manifest 处理见[基础镜像缓存](metor-base-images.md)。

## 2. AI、Metor、MySQL 归档

示例 tag 与构建指南的 AMD64 build.env 一致。完整制作执行：

```bash
M6_MYSQL_IMAGE=icp-diag-mysql:8.4-amd64-20261028-1 \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64
```

脚本默认只制作 ai、metor、mysql；前端见第 3 节。输出目录默认是 dist/m6-amd64-images-release-20261028-1-amd64，可用 M6_IMAGE_OUTPUT_DIR 修改。

### 单组件制作或失败续跑

以下命令按需要选择。首次仅制作某一项或未验收版本的失败续跑可选择组件；已发布／已验收版本有源码变化时必须使用新版本号，不覆盖旧制品。

```bash
# 仅 AI
M6_BUILD_COMPONENTS=ai \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64

# 仅 Metor
M6_BUILD_COMPONENTS=metor \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64

# 仅 MySQL，使用专用 tag
M6_BUILD_COMPONENTS=mysql M6_MYSQL_IMAGE=icp-diag-mysql:8.4-amd64-20261028-1 \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64

# 多组件选择
M6_BUILD_COMPONENTS="ai metor" \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64
```

AI 和 Metor 固定 CUSTOMER_REQUIRED 并检查正式输入。AI_RUNTIME_IMAGE／METOR_IMAGE 的 tag 由传给脚本的版本号确定；MySQL tag 由 M6_MYSQL_IMAGE 确定，必须与组包 build.env 一致。

每个组件先写 .tar.partial，校验 config、层文件及 SHA256 blob 后才移动为正式 tar。仅制作一项不代表完整交付包已经就绪；三个脚本归档全部存在并通过检查时才输出其汇总 SHA256SUMS。

## 3. 单独制作前端归档

前端不是 M6_BUILD_COMPONENTS 的可选项，需要单独调用 Buildx。仅制作前端且专用 builder 尚不存在时，先创建它；若已由脚本创建则直接复用。自定义 builder 名称时同步替换以下 m6-amd64-builder：

```bash
if ! docker buildx inspect m6-amd64-builder >/dev/null 2>&1; then
  docker buildx create --name m6-amd64-builder --driver docker-container
fi
docker buildx inspect m6-amd64-builder --bootstrap

ICP_AMD64_VERSION=release-20261028-1-amd64
ICP_AMD64_OUTPUT="$PWD/dist/m6-amd64-images-${ICP_AMD64_VERSION}"
mkdir -p "$ICP_AMD64_OUTPUT"

docker buildx build \
  --builder m6-amd64-builder \
  --platform linux/amd64 \
  --progress=plain --provenance=false \
  --metadata-file "$ICP_AMD64_OUTPUT/frontend.build-metadata.json" \
  --tag "metor-platform-frontend:${ICP_AMD64_VERSION}" \
  --output "type=docker,dest=$ICP_AMD64_OUTPUT/frontend_${ICP_AMD64_VERSION}_linux-amd64.tar.partial" \
  frontend

python3 deployment/scripts/inspect-docker-archive.py \
  "$ICP_AMD64_OUTPUT/frontend_${ICP_AMD64_VERSION}_linux-amd64.tar.partial" \
  --expect-os linux --expect-architecture amd64
mv "$ICP_AMD64_OUTPUT/frontend_${ICP_AMD64_VERSION}_linux-amd64.tar.partial" \
  "$ICP_AMD64_OUTPUT/frontend_${ICP_AMD64_VERSION}_linux-amd64.tar"
```

前端专用 builder 的下载源沿用其创建配置；上面的直接创建方式不自动读取 M6_DOCKERHUB_MIRROR。

## 4. Gradle 下载与缓存预热

Metor 构建使用固定 id metor-gradle 的 BuildKit cache mount。首次构建需要 Gradle 8.14 分发包和依赖，后续可复用；Docker Hub mirror 不代理 Gradle、PyPI 或 GHCR。

已有完整、经验证的 Gradle 8.14 分发目录及 modules-2 依赖缓存时，可预热同一个专用 builder，再离线编译 Metor。以下路径替换为实际缓存位置：

```bash
deployment/scripts/seed-gradle-cache.sh \
  /Users/sloong/.gradle/wrapper/dists/gradle-8.14-bin/38aieal9i53h9rfe7vjup95b9 \
  /Users/sloong/.gradle/caches/modules-2

M6_GRADLE_OFFLINE=1 M6_BUILD_COMPONENTS=metor \
  deployment/scripts/build-amd64-images.sh release-20261028-1-amd64
```

预热脚本只复制指定分发目录、完成标记和 modules-2 制品／元数据，不复制整个 Gradle 用户目录、gradle.properties、凭据、init script 或宿主 JDK。编译仍由 AMD64 JDK 执行；缺依赖时 --offline 会失败，不隐式下载。

自定义 builder 时给预热脚本设置 GRADLE_CACHE_BUILDER 或 M6_BUILDER_NAME，与制作保持一致。不要用全局 --no-cache 破坏缓存复用；升级 Wrapper 时同步更新 seed-gradle-cache.Dockerfile 的版本约定。Gradle 编译离线不等于整个镜像构建无网络，基础镜像和 apt 等仍可能联网。

## 5. 制作结果与移交组包

四个归档应为：

```text
dist/m6-amd64-images-release-20261028-1-amd64/
├── ai-runtime-service_release-20261028-1-amd64_linux-amd64.tar
├── metor-service_release-20261028-1-amd64_linux-amd64.tar
├── mysql_8.4_linux-amd64.tar
├── frontend_release-20261028-1-amd64_linux-amd64.tar
└── SHA256SUMS
```

脚本生成的 SHA256SUMS 仅覆盖 AI、Metor、MySQL 三个归档；前端需单独完成检查。完整四镜像、模型、配置及文档的最终校验清单由[统一组包流程](customer-release/01-build.md#4-验证实际镜像并导出)生成，不手工拼客户交付包。

构建日志、build-metadata.json 和 inspection.json 保留为制作方证据。将四个已核验 tar 移交独立组包环境，继续构建指南的第 4 节；本文不执行客户安装、数据库迁移、启动或更新。
