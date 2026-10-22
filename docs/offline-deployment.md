# 整栈离线交付

部署统一使用独立 `deployment/` 工程，不再交付单独 AI 或 Metor Compose。以下命令从包含 `deployment/` 的工作区或安装根目录执行。

## 同架构镜像导出

先完成源码构建和运行验收，再导出配置中选定的四个运行镜像：

```bash
python3 deployment/scripts/local-stack.py export /absolute/path/to/new-full-stack-bundle
```

此命令要求三个业务源码仓库与部署工程同级。它从本机 Docker 镜像库导出，不改变架构。当前 Mac 的 ARM64 运行镜像不能作为 AMD64 制品交付。

包内包含四个镜像、部署 Compose、脚本、公共模型清单、发布文档、版本清单和 SHA-256。不包含凭据、数据库、业务文件或模型权重。目标机不需要 JDK、Node 或源码。

## AMD64 制作与安装

跨架构构建、前端镜像补齐、部署包组装、`/opt/icp-diag` 目录和 JNI 验收统一见 [AMD64 操作步骤](amd64.md)。MySQL 保留 Docker 命名卷。

新目标机提前准备 Docker Engine、Compose 2.24.4+、Python 3.9+、tar／gzip 和模型权重。部署包装脚本只使用 Python 标准库，不需要 pip 包。已有环境不重新运行 init，不覆盖私有配置。

使用 export 生成的同架构包时，先从包根目录校验，再导入：

```bash
sha256sum -c SHA256SUMS
docker load --input images/full-stack.tar
python3 deployment/scripts/local-stack.py compose config --quiet
```

最后一条要求已经按首次部署流程生成目标机 `runtime/config/docker.env`。没有私有配置时先执行 AMD64 文档中的首次配置步骤。MySQL、AI 迁移、AI、Metor、前端按顺序启动。

模型权重和获准业务备份通过受控介质另行传输。Chat 模型服务需由目标环境提供，不能将离线镜像加载等同于真实模型已可用。

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
