# 离线授权图解手册

使用 show-me 按当前源码整理，基线为 2026-10-23，SDK 0.6.0 / issuer 0.3.0。

打开 [index.html](index.html)；全部 HTML 可直接用浏览器离线打开，无需启动服务器或业务服务。

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

02 页的交互只模拟算法，不执行 SDK、不写 clock 或修改真实时钟。其余代码块是操作示例，需先替换路径、时间、UUID 和信任输入。页面人工验收及客户 Linux 最终交付仍分别在 Phase 7、Phase 8 记录。源码相对链接适用于完整开发工作区。
