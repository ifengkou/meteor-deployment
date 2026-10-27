# 整栈离线交付

部署统一使用独立 `deployment/` 工程，不再交付单独 AI 或 Metor Compose。以下命令从包含 `deployment/` 的工作区或安装根目录执行。

首次客户正式发版先读[分阶段交付指南](customer-release/README.md)：按本次发行完成收口、构建、部署、签发与导入，并单独准备模型和业务资料。

## 同架构镜像导出

先按 [SDK 制作、安装与升级](license-sdk-upgrade.md) 准备正式 SDK 0.7.1 和同一份 Issuer 公开配置，完成客户构建和目标平台验收，再导出配置中选定的四个运行镜像。制作方私有 env 的 LICENSE_TOOLS_IMAGE 必须是本次 AI 镜像不可变 ID：

```bash
python3 deployment/scripts/local-stack.py export /absolute/path/to/new-full-stack-bundle.tar.gz
```

此命令要求三个业务源码仓库与部署工程同级。它从本机 Docker 镜像库导出，不改变架构。当前 Mac 的 ARM64 运行镜像不能作为 AMD64 制品交付。

当前 format 2 私有交付包包含四个镜像、完整 Embedding、部署资产、版本清单与 SHA-256，以及现有 runtime/config/docker.env 的三项数据库密码和 JWT 密钥。可直接输出 tar.gz 与归档 .sha256；不包含数据库、业务文件、授权身份或签发私钥。目标机不需要 JDK、Node 或源码。默认模型路径同样从源 docker.env 读取，也可用 --model-path 指定。

## AMD64 制作与安装

跨架构构建、前端镜像补齐、部署包组装、`/opt/icp-diag` 目录和 JNI 验收统一见 [AMD64 操作步骤](amd64.md)。MySQL 保留 Docker 命名卷。

新目标机提前准备 Docker Engine、Compose 2.24.4+、Python 3.9+、tar／gzip；完整 Embedding 已在当前交付包内。部署包装脚本只使用 Python 标准库，不需要 pip 包。已有环境不运行首次准备或重新 init，不覆盖私有配置。

使用 export 生成的同架构包时，先从包根目录校验，再导入：

```bash
sh deployment/scripts/import-images.sh .
# 首次安装：在目标 Linux root 会话中准备本次镜像、复用凭据、目录与数值权限。
python3 deployment/scripts/prepare-runtime.py
python3 deployment/scripts/local-stack.py compose config --quiet
```

导入脚本先验证清单与固定 SDK 摘要，加载后核对镜像 reference、ID 和架构。tar.gz 的校验、解压、准备与启动完整步骤见[首次部署](customer-release/02-deploy.md)。首次安装不再运行随机生成凭据的 init；独立执行 license-init 后，按 MySQL、AI 迁移、AI、Metor、前端顺序启动。

完整 Embedding 直接随包挂载，客户无需另行传输模型包。Chat 模型服务、场景及获准业务资料仍按[业务资料准备](customer-release/business-materials.md)落实；不能将镜像加载等同于真实 Chat 已可用。已有客户保留原 env 与授权根，按升级手册操作，不运行首次准备或重新初始化。

## 更新与恢复

升级见[日常更新](updates.md)，数据迁移和隔离恢复见[备份恢复](backup-restore.md)。离线更新只导入要替换的镜像并修改对应 tag，不清理数据卷。

AI 离线源码构建仍要求匹配架构和 Python 版本的完整 wheelhouse，使用 `build --service ai --offline`。Metor／前端的无网源码重建不在此命令支持范围；运行预制镜像与离线源码重建是两件事。

历史独立部署工具已移入 `deployment/archive/standalone/`，不作为运行入口。

## SDK 与依赖的离线边界

客户只加载我方预制镜像：Java SDK 已打入 BootJar，Python SDK、cryptography、PyJWT 及其运行依赖已装入 AI 镜像。容器启动不执行 Maven、Gradle、pip 或 uv 安装；单个 Python SDK wheel 不等于自包含运行环境。

我方准备 AI 离线构建依赖时，显式选择最终 Linux 架构（目标 Python 固定为 3.12），不能把制作机缓存当作依赖闭包：

```bash
TARGET_PLATFORM=linux/amd64 deployment/scripts/prepare-wheelhouse.sh
# 也支持自定义输出目录；随后将完整目录交给该架构的构建任务。
TARGET_PLATFORM=linux/arm64 deployment/scripts/prepare-wheelhouse.sh /absolute/build/wheelhouse
```

准备命令需要我方联网、uv 和可运行目标架构的 Docker 环境，按锁文件下载全部二进制依赖，保留本地 SDK wheel 相对路径；下载后在目标容器内用 `--no-index --no-cache-dir --ignore-installed --dry-run` 检查完整安装闭包，输出 `SHA256SUMS`。目标架构镜像不可执行、Python 版本不符、SDK 缺失或缺少兼容 wheel 时直接失败，不回退源码编译。制作期准备工具不会进入客户镜像运行流程。
