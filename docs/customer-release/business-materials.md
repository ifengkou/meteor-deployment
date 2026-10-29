# 另行准备的模型、业务资料与凭据

本页与镜像制作并行执行。完整 Embedding、三项数据库密码与 JWT 现在纳入统一交付包；Chat 服务、场景、知识资料与客户业务数据仍需准备。由实施负责人记录来源、版本／摘要、配置映射及验收结果。

## 1. Embedding 完整制品随包

默认使用已批准的 `bge-small-zh-v1.5` 完整目录；export 默认读取工作区 `runtime/config/docker.env` 的 `AI_EMBEDDING_MODEL_HOST_PATH`，也可用 `--model-path /absolute/model` 显式指定。目录须包含真实权重、模型配置、SentenceTransformer modules、tokenizer，以及现有 `model-manifest.json`（artifactName、dimension、来源 revision 及权重摘要等）；不能仅有 config.json、Git LFS 指针或指向制作机缓存的软链接。

export 复制全部文件到交付包的 `models/embedding/`，用本次固定 AI 镜像从该副本断网加载并编码中文，核对实际维数与模型 manifest。文件摘要进入全包 SHA256SUMS，模型 manifest 摘要与加载通过结果进入发行 manifest。无需为客户另外制作／导入模型压缩包。

客户解压统一包后只需运行 `prepare-runtime.py`，模型路径、只读权限和容器挂载清单自动就绪。AI 启动后 readiness 的 embeddingModel 应为 UP，再创建知识库、上传获准文本、等待索引成功并检索命中。

模型使用／再分发条件由制作方随来源资料保留。更换权重、tokenizer、normalize 或模型身份时不能沿用不兼容旧向量；新建知识库重建索引后再切换场景绑定。模型、知识库内容和 Chat 模型是不同的交付资料。

## 2. Chat 模型服务

先明确由客户内网推理服务、客户宿主服务或获准外部服务提供，交接下列信息：

| 信息 | 准备与核验 |
| --- | --- |
| 服务地址与协议 | AI 容器可访问的真实 endpoint、协议及模型名称，不填容器 localhost 冒充宿主 |
| 推理能力 | 所需模型权重／运行器、上下文长度、并发、超时、配额与 GPU／CPU 容量 |
| 网络 | DNS、端口、路由、TLS／证书、代理和防火墙；断公网要求下服务仍须在客户内网可达 |
| 凭据 | 客户专用 API Key 与保管／轮换负责人，单独安全交接 |
| 参数 | temperature、输出 token、stream 等与本次场景验证一致的设置 |

在平台“智能场景 → 模型服务”创建记录并测试真实响应。配置保存在 AI 数据库，不在 docker.env 中配置 Chat API Key，也不写入镜像。宿主模型服务可使用经实测可达的宿主名／地址；不要假设所有 Linux 安装都自动配置 `host.docker.internal`。

## 3. 航空六场景与绑定

通过平台场景管理创建本客户获准的提示词、参数、模型服务和检索绑定，逐一运行真实输入。Metor 配置映射的默认值如下：

| Metor 配置后缀（METOR_AEROSPACE_AI_SCENES_） | 默认场景 ID |
| --- | --- |
| CAUSE_JUDGE | cause-judge |
| CAUSE_JUDGE_REVIEW | cause-judge-review |
| REPORT_QUERY | report-query |
| INSPECTION_NODE | inspection-node |
| INSPECTION_SUMMARY | inspection-summary |
| TICKET_KEYWORD | ticket-keyword |

使用自定义 ID 时同步写入私有 env 的对应变量并重建 Metor。场景存在但指向禁用模型、空知识库或错误图谱也不能交付。当前没有承诺“一键导出／导入所有客户场景”；新装从已评审配置表逐项建立，获准迁移则按整栈备份恢复处理，不把演示数据库当通用初始化数据。

航空业务默认使用 AI Runtime，生成配置中的 `METOR_AEROSPACE_AI_ENABLED=true`。模型服务、提示词和绑定通过平台保存后生效；若调整 env 中的场景 ID 映射或 AI 调用参数，重新创建 Metor：

```bash
python3 deployment/scripts/local-stack.py compose \
  up -d --no-deps --force-recreate --wait metor
```

模型与场景配置完成后，分别运行真实故障和巡检，确认场景调用及业务结果。

## 4. 规则、知识与业务文件

| 资料 | 准备方式与完成条件 |
| --- | --- |
| 六类规则字典 | Metor Flyway 只建表；获准使用随包规则数据时，显式执行 migrations 下 SQL 并核对行数／刷新缓存 |
| 规则 JSON | 当前镜像含已固定的规则配置；客户有差异时先评审，记录来源与版本，不临场改容器文件 |
| 知识库原文 | 获取客户授权原文，创建知识库并选择正确 embeddingModelId，上传／摄取成功后检索验证 |
| 知识图谱 | 按场景需要准备节点、关系和原资料，导入／构建后核对范围与引用；不从演示环境复制无关资料 |
| 真实验收样本 | 获准 DAT／ZIP、多根及报告样本，记录期望结果；包含解密、事件入库、故障／巡检和导出对账 |
| 既有业务迁移 | 明确是否迁移、迁移范围、停写窗口、备份与对账；使用逻辑 SQL 和文件备份，不能跨架构拷正在运行的 MySQL 数据目录 |

规则 SQL 随统一包在 `deployment/migrations/metor/ai631-rules-upsert.sql`。Metor 首次启动建表后可使用容器内 MySQL 客户端，不需客户另装客户端；先获业务批准，再执行：

```bash
python3 deployment/scripts/local-stack.py compose exec -T mysql sh -c \
  'MYSQL_PWD="$METOR_DB_PASSWORD" exec mysql --default-character-set=utf8mb4 -u"$METOR_DB_USER" "$METOR_DATABASE"' \
  < deployment/migrations/metor/ai631-rules-upsert.sql
```

明细、预期行数和 upsert 语义见[随包规则说明](../../migrations/metor/README.md)。该脚本会更新同主键规则，不把它当无影响的检查命令；执行后核对缓存刷新及实际诊断结果。

## 5. 账号、私有配置和交接

数据库密码与 JWT 密钥直接复用制作机现有 `runtime/config/docker.env` 对应值，由 export 提取四个允许字段，客户 prepare 脚本据此生成目标 env（0600），不重新随机生成；首管理员由授权人员先完成初始化，不设置通用默认客户口令。另行准备普通操作员、所需系统 API Key／scope、模型凭据、入口域名证书及其负责人。

已约定的数据库密码／JWT 随私有交付包交接；其他凭据按客户约定安全渠道交接，均不放 Git、发行 manifest、截图或验收日志。备份中的私有 env、数据库和安装主密钥也按敏感资料保护。

客户专用清单逐项标明“我方交付／客户提供／本次不启用”、版本／摘要、路径或业务 ID、配置关系、完成日期和验收结果。最终保留与本次镜像兼容的模型副本、场景／规则清单、业务备份及恢复步骤。
