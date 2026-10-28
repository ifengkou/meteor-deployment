# Linux AMD64 架构说明与验收要点

本文只维护 AMD64 平台边界和 JNI 验收要点。构建、组包、首次安装及日常更新分别使用下列入口，不在此重复操作步骤。

## 操作入口

| 任务 | 唯一操作说明 |
| --- | --- |
| 冻结版本、准备输入、客户 AMD64 镜像、单服务制作、统一组包 | [构建与交付包](customer-release/01-build.md) |
| 本机 ARM64 构建与部署 | [本机 build](local-release/01-build.md) → [本机 deploy](local-release/02-deploy.md) |
| Apple Silicon 的专用 Buildx、组件归档、下载源与缓存 | [AMD64 隔离构建细节](amd64-build.md) |
| 客户宿主依赖、校验／解压、目录权限、初始化、迁移、启动与访问 | [首次部署](customer-release/02-deploy.md) |
| 签发商业许可 | [授权签发](customer-release/03-license-issue.md) |
| 导入许可与最终业务验收 | [授权导入与验收](customer-release/04-license-import.md) |
| 已有环境全套／单服务更新、配置变更与回退 | [客户 deploy](customer-release/02-deploy.md#7-已有环境更新) |
| 一致性备份和隔离恢复 | [备份恢复](backup-restore.md) |
| SDK 输入、已有安装信任兼容与升级 | [SDK 接入与升级](license-sdk-upgrade.md) |
| Chat、场景、规则及业务资料 | [业务资料清单](customer-release/business-materials.md) |

客户交付包中只包含 customer-docs 的使用指南；这些制作方技术文档不进入客户包。

## 架构约定

本次客户目标为 **Linux x86_64／AMD64**。客户主机 uname -m 应为 x86_64，四镜像实际平台均为 linux/amd64。构建参数或 env 中写 linux/amd64 不会把已有 ARM64 镜像转换为 AMD64，最终按实际镜像／归档和 manifest 核对。

| 项目 | AMD64 | ARM64 |
| --- | --- | --- |
| METOR_PLATFORM | linux/amd64 | linux/arm64 |
| 常见宿主 | x86_64 Linux | Apple Silicon Docker／aarch64 Linux |
| SDK 与客户模式 | SDK 0.7.1，CUSTOMER_REQUIRED | 相同，不因架构切换为开发模式 |
| DAT JNI | 包含 x86-64 的 libEncryptAndDecrypt.so | Dockerfile 移除该库，不能验证此 DAT 解密链路 |
| 对当前客户发行的作用 | 原生验收与交付目标 | 对应平台开发／补充验证 |

Apple Silicon 上的 AMD64 构建及模拟运行可以发现部分问题，但不代替原生客户架构验收。普通 JVM 启动成功不能证明 JNI 可以加载或 DAT 解密正确。

## JNI 与真实业务验收

Metor AMD64 镜像内包含 `/usr/local/lib/libEncryptAndDecrypt.so`，无需从宿主另挂该库。服务按首次部署指南就绪后，可作以下只读检查：

```bash
python3 deployment/scripts/local-stack.py compose exec -T metor sh -c \
  'test -r /usr/local/lib/libEncryptAndDecrypt.so && ldd /usr/local/lib/libEncryptAndDecrypt.so'
```

依赖检查不能出现 not found；文件存在和 ldd 通过仍不能代替实际 JNI 调用。记录以下验收结果，客户样本和事件内容保存在私有资料目录：

1. Metor 的实际 DAT 解密开关已开启，没有 UnsatisfiedLinkError 等加载异常。
2. 使用获准 DAT 样本验证真实解密、解析及事件入库；多根 DAT／ZIP 按交付范围核对来源、数量和顺序。
3. 对照客户期望结果验证故障、巡检、报告、原始文件及下载导出；前端交互另按人工清单验收。
4. 完成实际 Chat、场景和检索资源配置，验证真实模型可达与航空 AI 结果，不能用固定响应代替。
5. 按相应操作指南完成停启、断网和隔离恢复验收，记录版本、镜像 ID、包摘要、迁移版本和数据对账。

架构、JNI 和客户验收记录随本次发行保存；不要把历史 ARM64 演示、旧镜像的健康检查或构建日志当作本次 AMD64 业务验收结论。
