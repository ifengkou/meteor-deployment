# 离线授权图解手册

本目录八个 HTML 保留为 **2026-10-23 历史图解**，基线为 SDK 0.6.0／Issuer 0.3.0，不是当前 SDK 0.7.1 的接入和安装指令。
协议原理仍可参考；旧 DER 信任输入、部署自建初始化和调度代码示例不再是受支持的生产路径。
当前首次安装、旧安装升级与回退请从 [SDK 升级手册](../license-sdk-upgrade.md) 开始；制作输入见
[Metor 构建说明](../../../metor-service/license-build/README.md)和 [AI 构建说明](../../../ai-runtime-service/license-build/README.md)，恢复见 [当前恢复手册](../license-recovery.md)。

打开 [index.html](index.html)；全部 HTML 可直接用浏览器离线打开，无需启动服务器或业务服务。

需要对照源码理解算法与状态变化时，阅读[授权机制实现逻辑](../license-implementation.md)：包含机器申请、签发幂等、商业导入、受控请求、一天回拨容差及单服务签名恢复的 Mermaid 时序图和流程图。

| 文件 | 内容 |
| --- | --- |
| [授权控制机制](01-control.html) | 谁签发、谁校验、控制什么 |
| [防时间回拨与恢复](02-clock-recovery.html) | 时间为何只前进，何时允许重建 |
| [Issuer 签发流程](03-issuer.html) | 我方如何生成、签发与重试 |
| [SDK 接入步骤](04-sdk.html) | 固定制品、Runtime、guard 与生命周期 |
| [Metor 集成与运行](05-metor.html) | Java 装配、过滤器、关键入口与管理 API |
| [AI Runtime 集成与运行](06-ai-runtime.html) | Python 装配、独立校验与 ControlProof |
| [客户日常操作](07-operations.html) | 初始化、导入、续期与恢复怎么做 |
| [完整性与失败处理](08-integrity-failures.html) | 清单保护、CAS、原子提交和备份边界 |

02 页的交互只模拟算法，不执行 SDK、不写 clock 或修改真实时钟。其余代码块仅用于理解上述历史基线，不将它们用于新安装或覆盖现有安装资料。
本轮按用户要求未执行人工页面验证；客户 Linux AMD64 验收与 ARM64 自动验证分别记录，不能互相替代。源码相对链接适用于完整开发工作区。
