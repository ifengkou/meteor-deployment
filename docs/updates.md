# 更新操作入口

| 场景 | build | deploy |
| --- | --- | --- |
| 本机 Apple Silicon Docker Desktop | [本机镜像制作](local-release/01-build.md) | [本机部署与更新](local-release/02-deploy.md) |
| 客户 Linux AMD64 | [客户镜像与统一包](customer-release/01-build.md) | [客户首次部署与更新](customer-release/02-deploy.md) |

## 配置位置

运行版本在完整 runtime/config/docker.env 的 *_IMAGE 切换，Compose 中的 tag 为字段缺失时的兜底。build.env 用于单次制作，不自动合并，也不用于启动。字段和优先级见[配置说明](configuration.md#镜像-tag-与构建文件)。

## 全套更新

按对应 deploy 文档完成备份、修改运行镜像、数据库迁移、容器重建及业务验收。

## 仅更新单个服务

制作方法在对应 build 文档；运行切换见[本机单服务更新](local-release/02-deploy.md#单服务更新)与[客户更新](customer-release/02-deploy.md#7-已有环境更新)。

## 仅更新配置

备份后使用 up --force-recreate 应用环境与挂载变化，按服务依赖顺序恢复。

## 回退与恢复

见[本机版本回退](local-release/02-deploy.md#版本回退)、[客户更新](customer-release/02-deploy.md#7-已有环境更新)及[备份恢复](backup-restore.md)。
