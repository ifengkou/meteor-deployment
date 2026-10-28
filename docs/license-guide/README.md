# 授权操作指引

当前操作适用 License SDK 0.7.1、Issuer 0.4.0，按以下阶段执行：

| 操作 | 指引 |
| --- | --- |
| 准备 SDK、公开配置并构建镜像 | [本机 build](../local-release/01-build.md)／[客户 build](../customer-release/01-build.md) |
| 首次安装与初始化 | [客户 deploy](../customer-release/02-deploy.md) |
| 更新已有安装 | [本机 deploy](../local-release/02-deploy.md)／[客户更新](../customer-release/02-deploy.md#7-已有环境更新) |
| 签发商业许可 | [我方签发](../customer-release/03-license-issue.md) |
| 导入、续期与验收 | [授权导入](../customer-release/04-license-import.md) |
| 时间异常签名恢复 | [恢复流程](../license-recovery.md) |
| 备份与恢复安装资料 | [备份恢复](../backup-restore.md) |
| SDK 版本升级 | [输入与兼容要求](../license-sdk-upgrade.md) |

首次安装由 SDK 生成身份、密钥和时间记录；后续更新保留原安装资料。商业许可由我方签发、客户管理员导入，Metor 与 AI 各自校验状态。

## 协议图解

打开 [index.html](index.html)可离线阅读协议与集成图解。HTML 的接口示例适用 SDK 0.6.0／Issuer 0.3.0；当前实施命令使用上表指引。

| 图解 | 内容 |
| --- | --- |
| [授权控制机制](01-control.html) | 签发、校验与受控范围 |
| [防时间回拨与恢复](02-clock-recovery.html) | 时间高水位与签名恢复 |
| [Issuer 签发流程](03-issuer.html) | 商业签发、幂等与重试 |
| [SDK 接入步骤](04-sdk.html) | Runtime、guard 与生命周期 |
| [Metor 集成与运行](05-metor.html) | Java 装配和管理 API |
| [AI Runtime 集成与运行](06-ai-runtime.html) | Python 装配、独立校验与 ControlProof |
| [客户日常操作](07-operations.html) | 初始化、导入、续期与恢复 |
| [完整性与失败处理](08-integrity-failures.html) | 摘要、CAS、原子提交和备份边界 |

图解交互仅模拟协议，不执行 SDK 或修改真实时钟。源码与状态机说明见[授权机制](../license-implementation.md)。
