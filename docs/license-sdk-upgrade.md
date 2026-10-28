# SDK 构建输入与升级要求

产品使用正式 License SDK 0.7.1。Java 与 Python 各自本地校验，共享一份商业许可。构建和部署操作分别按以下入口执行：

| 场景 | build | deploy |
| --- | --- | --- |
| 本机 Docker Desktop／Linux ARM64 | [本机构建](local-release/01-build.md) | [本机部署与更新](local-release/02-deploy.md) |
| 客户 Linux AMD64 | [客户构建与组包](customer-release/01-build.md) | [客户首次部署与更新](customer-release/02-deploy.md) |

## 1. 准备输入

| 资料 | 来源与用途 |
| --- | --- |
| SDK 制品和 SHA256SUMS | 制作方取得正式 Release 并校验，分别进入 Java 与 AI 镜像 |
| license-product.json | 产品 Issuer 导出的公开配置；两个工程使用同一原始文件 |
| identity／service.key／两份 clock | 首次安装显式执行 license-init，由镜像内 SDK 生成 |
| active.license.json | 我方签发的商业许可，由管理员在软件授权页面导入 |
| 恢复挑战与后续时间记录 | SDK 按服务独立维护 |

构建输入位置见 [Java 输入](../../metor-service/license-build/README.md)和 [AI 输入](../../ai-runtime-service/license-build/README.md)。客户使用预制镜像，宿主不安装 SDK，也不手工生成身份、密钥或 clock。

## 2. 核对兼容性

升级前逐项核对产品、服务、协议域、编码前缀、key ID 与公钥。保留既有客户仍需使用的全部公开信任，并确认我方 Issuer 配置匹配本次发行。将正式制品摘要和公开配置摘要写入发行记录。

在隔离环境验证新镜像对既有许可、安装身份和时间记录的兼容性，再制作正式交付包。两个后端 SDK、公开配置或契约一起变化时，按兼容范围同时更新受影响服务。

## 3. 准备镜像和工具

按对应 build 文档制作 CUSTOMER_REQUIRED 镜像，校验镜像内实际 SDK 载荷、公开配置和 API 清单。

客户包通过 manifest 固定本包 AI 工具镜像；源码本机配置 LICENSE_TOOLS_IMAGE 为已核验兼容 AI 镜像的完整 sha256 ID。工具与业务镜像分别管理，回退业务镜像时保留新版工具。

## 4. 备份并更新

暂停业务写入，等待任务结束，按对应 deploy 文档完成一致性备份并保持应用停止。备份须包含业务库、文件、配置和整个授权状态。

保留原授权根、安装身份、密钥、商业许可和各服务时间记录，修改相应运行镜像，按 AI 数据库迁移 → AI → Metor → 前端顺序恢复。已有安装不重新执行 license-init。

## 5. 验收

核对实际镜像与健康状态，确认 Metor／AI 各自 ACTIVE，原许可、用户、业务文件和检索仍可用。比较升级前后的安装身份、商业许可摘要与时间高水位；正常 checkpoint 可以推进时间记录。

首次安装、升级、重启、离线运行和兼容回退分别验收，按[发布检查清单](customer-release/readiness.md)留存结果。时间异常使用[签名恢复流程](license-recovery.md)。

## 6. 回退与恢复

业务数据格式兼容时，只回退已验收业务镜像，保留最新授权资料和新版部署工具。数据格式不兼容时，按[备份恢复](backup-restore.md)在满足条件的隔离空目标恢复并对账。
