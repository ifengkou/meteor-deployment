# 已停用的独立部署资料

此目录仅保留迁移前的独立 AI／Metor Compose、脚本和文档，供历史对照，不是可执行的部署入口。相对路径及配置约定不再维护，不运行这里的脚本，不从中复制配置覆盖当前环境。

当前唯一入口为 [deployment/README.md](../../README.md)，唯一私有运行配置为工作区或安装根目录的 `runtime/config/docker.env`。业务工程只负责源码开发和镜像构建。

历史私有 `.env.full-local` 已移入工作区 `runtime/backups/deployment-migration-20261016/`，没有进入公共部署目录；Metor 本机 `.env.docker` 保留原处但不再作为发布入口。已有容器和数据卷没有删除或重建。
