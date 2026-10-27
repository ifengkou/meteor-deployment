# 本机 Linux ARM64 交付部署验证（2026-10-26）

状态：已完成构建、完整包导出／校验／导入、独立部署及 API／真实向量检索验证。保留开发环境并修复其 MySQL 历史挂载故障。本记录针对 macOS Docker Desktop 中的 **Linux ARM64**，不是客户 Linux AMD64／真实 DAT/JNI 或人工 UI 验收。

## 清理与保留

按用户要求删除 icp-diag-m7、icp-diag-local-restore-check、icp-diag-sdk071-20261025 的 13 个容器、4 个闲置网络及 12 个明确的历史验证镜像；所有历史数据卷保留。未清理其他工程、开发数据或历史发布回退镜像。清理审计在工作区 runtime/arm64-release-20261026/cleanup-result.json。

开发环境 icp-diag-local 原 MySQL 容器引用已迁移掉的 AI 工程 mysql-init 路径，重建 MySQL 容器以使用当前 deployment 脚本，保留原命名卷和凭据；前端、Java、AI、MySQL 最终均 healthy。

## 当前访问与管理

| 项目 | 地址／位置 |
| --- | --- |
| 新验证项目前端 | http://127.0.0.1:18183/ |
| 软件授权 | http://127.0.0.1:18183/platform/settings/license |
| 原开发环境前端 | http://127.0.0.1:18180/ |
| 新 Java／AI／MySQL 维护端口 | 127.0.0.1:18083／18093／13309 |
| 新项目 | icp-diag-arm64-verify |
| 安装卷 | icp-diag-arm64-verify-install |
| 管理员 | arm64-admin；随机密码仅在工作区 runtime/arm64-release-20261026/accounts.json（0600） |
| 最终交付包 | dist/icp-diag-arm64-verify-20261026-2.tar.gz，另附 .sha256 |
| 许可 | 本机验证专用 TERM／UNBOUND，正式 vendor-icp-2026 密钥签发；到期 UTC 2026-11-25T11:57:50Z |

从工作区根目录执行，命令只管理新验证项目：

```bash
python3 runtime/arm64-release-20261026/manage.py status
python3 runtime/arm64-release-20261026/manage.py logs ai-runtime
python3 runtime/arm64-release-20261026/manage.py stop
python3 runtime/arm64-release-20261026/manage.py start
```

Docker Desktop 的数值权限验证使用独立 Linux 安装卷；卷内放完整交付包和 runtime，由临时运维容器调用同一 prepare-runtime.py、local-stack.py 和 SDK 初始化器。模型来自包内副本，不复用开发 Chroma、业务文件、数据库或许可身份。运维镜像 icp-deployment-tools:arm64-verify-20261026-1 仅用于这个 Mac 验证环境，不进入客户四镜像交付包。Linux 客户仍按标准 /opt/icp-diag 宿主目录流程部署。

## 制品与结果

| 镜像 | 不可变 ID |
| --- | --- |
| mysql:8.4 | `sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb` |
| ai-runtime-service:arm64-verify-20261026-1 | `sha256:1b9e3883a6e9952860e53fe40fd8ba933298e207aff0cb370c94d337b0caf1e8` |
| metor-service:arm64-verify-20261026-1 | `sha256:e27269d5b9db35893f36c4eeaad588f8ac34f0964e232eeb40e9583a087d4265` |
| metor-platform-frontend:arm64-verify-20261026-1 | `sha256:4f5b31ea3e32de1b0552c488504a9bb7be0c19bb459047903169f710ab0a6a6e` |

公开配置 SHA256：`67997a6148814a2b4898d9b149efd4dd5f307643c3d53b91dd5e90e6fc18ba03`；SDK 0.7.1、两端 CUSTOMER_REQUIRED。完整包包含 Embedding 和获准复用的三项数据库密码／JWT；未包含客户安装身份、业务数据、签发私钥或口令。归档权限 0600，SHA256：`e357cb7d403bfbf8d59cdec8af01f8a96c83099b54ea4a3aa6cf3e4ff00ad568`。

已确认：

1. 三个应用新构建成功，四镜像均 Linux ARM64；导出检查实际 SDK、客户模式、公开配置一致性及 API 清单。完整 Embedding 在新 AI 镜像中断网编码，维数 512；包内全部制品及外层归档校验通过，实际导入镜像后再次核对 ID。
2. 在真正 Linux 卷内执行 prepare 两次成功；SDK 初始化 INITIALIZED → ALREADY_INITIALIZED，安装身份一致。目标 env 四项凭据与源 docker.env 原样一致，端口和路径按隔离环境配置。
3. AI Alembic／Java Flyway 迁移成功，四服务 healthy，AI 数据库／Embedding／Chroma readiness 正常。
4. 无许可时 Java 与 AI 受控操作均拒绝。经用户明确批准创建新管理员，并使用现有正式 Issuer 签发本机 30 天无绑定许可，实际导入 APPLIED、重复 ALREADY_APPLIED，两端独立 ACTIVE。共享文件为 UID 21001／GID 21000／0640，AI 可读。
5. 通过新前端 → Java 鉴权代理 → AI 新建合成知识库、上传中文文本，真实索引 SUCCEEDED，检索命中 1 条，首次最高相似度约 0.787。
6. 重建新应用容器后，许可 ACTIVE、商业文件摘要不变、原知识库仍可真实检索。
7. 最终包执行整栈一致性备份，含两业务库、应用文件、Chroma、私有配置和 SDK 授权状态，备份后应用自动恢复 healthy；之后再次确认许可与真实检索可用。备份位于安装卷 runtime/backups/arm64-acceptance-final-20261026。
8. 补充部署回归：74 passed／3 skipped，另有 19 subtests；macOS 跳过项不冒充 Linux AMD64 验收。

## 本轮发现并修复

备份原先使用 compose start 恢复已有容器，但首次安装用 run --rm ai-migrate 后，Compose 报 ai-runtime 缺失 ai-migrate 依赖，导致备份后服务未恢复。现改为按 AI、Java、前端顺序使用 up --no-deps --no-recreate --wait，只恢复原来运行的写入服务，保留其配置。新增回归测试，并从修正后的第二版交付包实际完成整栈备份及自动恢复；首版压缩包已移除。

包装器现在接受经过校验的 icp-diag- 小写实例名，默认仍为 icp-diag-local；新实例须独立 env、数据目录／卷和端口。此变化用于保留开发环境时进行隔离验证。原签发口令文件权限由 0644 收紧为 Issuer 要求的 0600，密钥与口令内容未改变。

## 验证边界与证据

未进行人工 UI、外部 Chat、六类航空场景／真实航空样本、签名时间恢复或隔离灾难恢复演练。ARM64 镜像不含现有 x86-64 JNI，保持解密关闭；客户 AMD64 仍需重新制作并原生验证真实 DAT、完整航空业务和恢复。当前为验证构建，四仓源码／部署工作区状态已记入 manifest，不是已冻结、已推送的客户正式发行基线。

证据在工作区 runtime/arm64-release-20261026/：images.json、deployment.json、verification.json、final-audit.json、构建／部署／备份日志。账号、签名许可和签发参数是私有资料；不把账号密码、JWT、ControlProof、主密钥或口令写进公共记录。
