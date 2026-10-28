# 离线交付入口

Linux AMD64 客户交付按 [customer-release/build](customer-release/01-build.md) → [customer-release/deploy](customer-release/02-deploy.md)执行。客户完整包包含四个镜像、完整 Embedding、获准复用的数据库密码／JWT、五份客户使用指南、manifest 和校验清单，输出 tar.gz 与 .sha256；不含研发过程文档、业务数据、安装身份、商业许可或签发私钥。

客户使用预制镜像，无需源码、JDK、Node、宿主 SDK 或在线安装 Python 业务依赖。目标为 Docker 24.0.7、Python 3.8.10，包内独立 Compose 2.33.0；系统 docker-compose 1.25.0 保留。Chat 服务和业务资料另按[资料清单](customer-release/business-materials.md)准备。

Apple Silicon 制作 AMD64 的 builder、缓存、单组件归档见[AMD64 构建细节](amd64-build.md)。隔离 Buildx 的 tar 需要在组包环境加载；export 从已有镜像统一组包，不重新构建源码。禁止手工拼包，或改已核验包后沿用旧摘要。

本机 ARM64 普通 build 直接进入 Docker 镜像库，无需为了本机更新而导出／导入。按 [local-release/build](local-release/01-build.md) → [local-release/deploy](local-release/02-deploy.md)执行。

AI 无网源码制作需提前准备目标 Linux 架构及 Python 3.12 的完整 wheelhouse，见对应 build 文档。单个 SDK wheel 不等于产品依赖闭包；Java／前端不由 AI 的 --offline 参数支持。
