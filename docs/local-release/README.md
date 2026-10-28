# 本机 Docker 构建与部署

适用：Apple Silicon macOS、Docker Desktop，以及已有完整运行配置、业务数据和授权安装的 `icp-diag-local`。镜像平台为 Linux ARM64，授权模式为 CUSTOMER_REQUIRED。

| 阶段 | 文档 | 完成标志 |
| --- | --- | --- |
| build | [制作镜像](01-build.md) | 新镜像进入本机 Docker 镜像库 |
| deploy | [部署与更新](02-deploy.md) | 完成备份、版本切换、数据库迁移、容器重建及验收 |

从包含 deployment/、三个业务工程和 runtime/ 的工作区根目录执行命令。build.env 用于本次制作，完整 runtime/config/docker.env 用于运行；部署时只修改对应镜像字段，保留数据库、模型、业务路径及授权卷。

本机授权资料使用专用 Linux 卷 `icp-diag-local-license`，通过 desktop-stack.py 维护。客户 Linux AMD64 的构建、首次安装、更新、签发和导入使用 [customer-release/](../customer-release/README.md)。
