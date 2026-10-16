# 部署故障处理

当前完整栈统一使用 `python3 deployment/scripts/local-stack.py compose ...`，从工作区或安装根目录执行。
配置位置见 [配置索引](configuration.md)，更新方法见 [更新手册](updates.md)。

| 现象 | 诊断 | 处理 |
|---|---|---|
| MySQL 长期 unhealthy | `docker compose logs mysql`；检查 Volume、磁盘和 root 密码 | 修复后重启；既有 Volume 密码与 `.env` 必须一致 |
| `ai-migrate` 非 0 退出 | 查看 migration 日志与 `alembic current/heads` | 保留现场；修复 migration 或恢复升级前备份，禁止改 `alembic_version` 绕过 |
| AI Runtime 不启动 | 检查模型目录挂载、权限、manifest 与环境变量 | 重新校验/安装同一模型制品；保持只读挂载 |
| readiness=503 | 查看响应中的 database、embeddingModel、chroma 分项和容器日志 | 只修复失败分项；liveness=200 不代表可接流量 |
| 外部 Chat 调用失败 | 使用模型服务 test API，检查 endpoint、协议和密钥 | 修复项目外 Chat 服务或内网路由；不会影响全局 readiness |
| 离线构建尝试联网 | 检查 wheelhouse 完整性和 `AI_OFFLINE_BUILD=1` | 在联网制品机重新生成 wheelhouse；不要在目标机临时下载 |
| 出现 CUDA/NVIDIA 包 | 检查 `uv.lock`、wheelhouse 文件名和 `pip list` | 拒绝发布，重新生成 CPU-only 锁与 wheelhouse |
| Chroma 损坏/丢失 | 确认 MySQL、原文档、模型 fingerprint 完整 | 恢复 Chroma 快照，或清空派生数据后运行重建脚本 |
| metor 无法调用 AI | 容器内检查 `METOR_PLATFORM_AI_RUNTIME_BASE_URL` 和业务 `METOR_AEROSPACE_AI_BASE_URL` 是否为 `http://ai-runtime:8090` | 使用 Compose service name，不要使用 `127.0.0.1` |

收集诊断信息时可以保存 `docker compose ps`、最近 200 行日志、镜像 RepoDigest、Compose config 摘要和
健康响应，但必须先脱敏；不要收集 `.env`、API Key、JWT secret、完整提示词或文档正文。
