# 模型与业务配置

完整 BGE Embedding 已包含在本包；Chat 服务、场景、知识资料及业务样本按客户交付范围准备。镜像和数据库启动成功不代表这些业务资源已经配置。

## Embedding 与知识库

准备脚本将 models/embedding 只读挂载到容器 /models/embedding，使用稳定模型 ID bge-small-zh-v1.5。未提供其他模型时不要启用额外条目。AI readiness 的 embeddingModel 应为 UP，随后创建知识库，上传获准原文，等待索引 SUCCEEDED 并检索验证。

更换权重、tokenizer、normalize 或模型身份时，不复用不兼容旧向量；新建知识库、重建索引后再切换场景绑定。模型文件与模型 manifest 随发行包保留，不在运行时联网下载。

## Chat 与场景

由客户或服务方提供容器可访问的 Chat endpoint、协议、模型名称、API Key、上下文长度、并发及超时配置。在平台“智能场景 → 模型服务”建立记录并测试真实响应。容器 localhost 指容器本身；宿主模型地址必须实际连通，不假设所有 Linux 均配置 host.docker.internal。

离线业务要求 Chat 服务在客户内网可达；Embedding 离线并不等于 Chat 已具备。模型配置、知识库／图谱、提示词与场景绑定保存于业务数据库，不写进镜像或公共文档。

航空业务默认使用下列场景 ID：

| 用途 | 场景 ID |
| --- | --- |
| 原因判断 | cause-judge |
| 判断复核 | cause-judge-review |
| 报告查询 | report-query |
| 巡检节点 | inspection-node |
| 巡检汇总 | inspection-summary |
| 单据关键词 | ticket-keyword |

通过平台创建获准的模型服务、提示词、检索参数、知识库／图谱及场景绑定，逐项用真实输入验证。自定义 ID 时同步修改私有 env 对应的 METOR_AEROSPACE_AI_SCENES_ 配置。完成后将 METOR_AEROSPACE_AI_ENABLED 改为 true，按[运维指南](operations.md)重新创建 Metor，并跑真实故障与巡检。

## 规则与业务资料

以下为六张规则表的首次导入流程，适用于 ICP Diag 目标六表为空的情况。从客户源系统导出最新规则快照，离线转换后显式导入；规则数据以该快照为准，使用工具生成的 SQL。目标已有规则时，先确认合并范围。

### 1. 在客户旧库侧只读导出

将 `deployment/scripts/ai631-rules.py` 单文件复制到能访问客户旧 MySQL 的机器。该机器需要 Python 3.8+ 和 `mysql` 命令行客户端，无需 pip、SDK 或新系统源码。使用本发行包中的脚本，并核对复制后的文件摘要。

使用专用私有目录保存配置与数据，在该目录放置脚本。新建 `source.cnf`（权限必须为 0600），填写实际旧库连接信息：

```ini
[client]
host=127.0.0.1
port=3306
user=rule_export
password="替换为实际密码"
protocol=TCP
```

账号只需旧库六张规则表的 SELECT 权限；密码含反斜杠或双引号时，按 MySQL option-file 规则转义。下面 `phoenix` 仅为旧库名示例，执行前必须替换；不能填新系统目标库名。命令在放置脚本和 source.cnf 的私有目录执行：

```bash
chmod 600 source.cnf
python3 ai631-rules.py export \
  --defaults-file ./source.cnf \
  --database phoenix \
  --output ./rules-source.json
sha256sum rules-source.json > rules-source.json.sha256
```

脚本检查六张表均存在、使用 InnoDB、字段及类型与既定映射相符，然后在一个一致性只读事务中读取六张表；不会修改旧库。导出期间不调整旧表结构。任何表缺失、字段变化或非事务引擎都会停止，不能手改映射绕过。逐表核对报告中的行数与源库实际一致，空表也应明确记录为 0。

密码只保存在本机私有 source.cnf，不放入命令参数、导出文件或报告；该配置文件不随规则资料传输。保留原始快照与摘要，通过受控渠道将快照、摘要和工具转交实施方。

### 2. 离线转换成新表 SQL

在有 Python 3.8+ 的实施机器执行。转换只读本地快照，不连接任何数据库：

```bash
sha256sum -c rules-source.json.sha256
python3 ai631-rules.py convert \
  --input ./rules-source.json \
  --output ./rules-upsert.sql
python3 -m json.tool rules-upsert.report.json
sha256sum rules-upsert.sql
```

得到 `rules-upsert.sql` 和 `rules-upsert.report.json`，文件权限为 0600。报告包含原始快照 SHA256、SQL SHA256 和六张表的实际源行数；核对 SQL 摘要等于报告的 sqlSha256。原样保留主键、NULL、空字符串、中文和换行；数值溢出、重复主键、必填字段缺失等异常会拒绝转换。工具拒绝覆盖已有导出、SQL 和报告，重做时换一个新文件名。

表映射如下，验收行数以本次导出报告为准：

| 客户旧表 | 新系统目标表 |
| --- | --- |
| ace_bit_event_dictionary | diag_bit_event_dict |
| ace_fault_event_dictionary | diag_fault_event_dict |
| ace_sys_call_dictionary | diag_syscall_dict |
| ace_running_state_dictionary | diag_running_state_dict |
| ace_running_state_rule | diag_running_state_rule |
| ace_special_dictionary | diag_special_dict |

### 3. 核对空目标并显式导入

在 ICP Diag 主机的 root 运维终端，先按[运维命令入口](operations.md#命令入口)配置当前 ICP_STACK 和原 ICP_ENV。把 SQL 和报告放在私有传输目录（以下以 `/opt/icp-rule-transfer/` 为例）。Metor 应已启动并完成 Flyway，MySQL 已健康。先核对 SQL 摘要，并暂停规则编辑及新诊断／巡检任务，Metor 和前端保持运行。

确认已有可用备份；若尚未备份，在维护窗口先执行以下命令。现有一致性备份工具会短暂停止并自动恢复写入服务；这属于备份动作，不是规则导入／快照生效的要求。已经完成本次导入前备份时，无需重复执行：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" backup /opt/icp-diag/runtime/backups/before-customer-rules-001
```

只读检查目标六表行数，确认全部为 0 后再继续；若不为空，停止并按已有规则合并流程评审，不删除或清空数据：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T mysql sh -c 'MYSQL_PWD="$METOR_DB_PASSWORD" exec mysql --default-character-set=utf8mb4 -u"$METOR_DB_USER" "$METOR_DATABASE"' <<'SQL'
SELECT 'diag_bit_event_dict' AS table_name, COUNT(*) AS row_count FROM diag_bit_event_dict
UNION ALL SELECT 'diag_fault_event_dict', COUNT(*) FROM diag_fault_event_dict
UNION ALL SELECT 'diag_syscall_dict', COUNT(*) FROM diag_syscall_dict
UNION ALL SELECT 'diag_running_state_dict', COUNT(*) FROM diag_running_state_dict
UNION ALL SELECT 'diag_running_state_rule', COUNT(*) FROM diag_running_state_rule
UNION ALL SELECT 'diag_special_dict', COUNT(*) FROM diag_special_dict;
SQL
```

明确指定 Metor 业务账号和目标库导入，不能连接客户旧库，也不要使用 mysql 的 `--force` 忽略错误：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T mysql sh -c 'MYSQL_PWD="$METOR_DB_PASSWORD" exec mysql --default-character-set=utf8mb4 -u"$METOR_DB_USER" "$METOR_DATABASE"' < /opt/icp-rule-transfer/rules-upsert.sql
```

SQL 在一个事务中按主键新增／更新全部六表，不修改表结构，不删除目标额外记录，也不属于 Flyway。末尾输出六表 source_rows 和 target_rows，**本次空库首次导入必须逐表完全相等**，并与 report.json 对上。失败时保持业务暂停，保留输出查明原因，确认原因后再决定是否重新导入。

### 4. 页面刷新规则快照并验收

导入事务提交、六表行数核对完成后，使用具备规则操作权限的账号进入规则界面，点击一次“刷新规则快照”。该按钮调用 `POST /aerospace/rules/refresh`，重新读取全部六类规则，不只是当前标签页；规则生效不需要重启 Metor 或前端。

确认页面提示“规则刷新完成”，没有失败类别；可同时检查服务端日志：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose logs --tail=100 metor
```

确认最新一次刷新日志中的 `Diagnosis dictionary refresh finished`、`failedCount=0`、`failedCategories=[]`，且没有快照转换失败。出现失败类别时，相关类别会保留旧快照，不能仅凭 HTTP 200 判断全部生效；保持业务暂停并排查。诊断缓存会按 is_fault 等条件筛选、按匹配键分组，缓存数量不要求等于数据库总行数；数据库六表行数仍须与导出报告逐表相等。

刷新成功后再恢复业务。SQL 是在页面外导入的，如规则列表仍显示旧查询结果，使用表格刷新或重新加载页面，再抽查客户本次新增／修改的规则；列表查询与诊断快照刷新是两个操作。随后用对应 DAT 新建诊断任务验证故障／巡检。已经开始的诊断继续使用开始时固定的快照，已生成报告不会因刷新而重新计算。行数一致不能代替具体规则内容与业务结果核对。后续向非空库导入时，upsert 不会同步源端删除，必须另行确认合并范围；不得为凑行数删除客户数据。

按范围准备知识库原文、图谱、DAT／ZIP／报告样本、期望结果、普通用户及系统 API Key／scope。以真实 DAT 完成 JNI 解密、解析和事件入库，再验证故障／巡检、报告及原始文件导出。JNI 文件存在与健康检查通过不能替代这些业务操作。

客户凭据、模型 API Key、业务样本和备份通过约定的安全渠道保存与交接，不进入公共日志或截图。
