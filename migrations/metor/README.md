# AI631 规则数据迁移

客户旧库规则更新后，使用 [ai631-rules.py](../../scripts/ai631-rules.py) 重新只读导出六张旧表，再离线生成新表 SQL 和行数／SHA256 报告。工具兼容 Python 3.8，使用标准库；导出机器另需 mysql 客户端，转换机器不需要数据库或 SDK。

**本次客户场景：旧库六表已有数据，新部署 ICP Diag 六表为空，首次导入。** 按[客户指南：规则与业务资料](../../customer-docs/business-config.md#规则与业务资料)执行完整的连接配置、导出、传输校验、转换、目标空表核对、导入和缓存刷新步骤。

```bash
# 在能访问客户旧库的机器执行；source.cnf 使用 0600 权限，内含实际连接信息
python3 deployment/scripts/ai631-rules.py export \
  --defaults-file /secure/source.cnf --database phoenix \
  --output /secure/rules-source.json

# 离线转换，不连接目标库
python3 deployment/scripts/ai631-rules.py convert \
  --input /secure/rules-source.json --output /secure/rules-upsert.sql
```

phoenix 只是旧库名示例，执行前替换为实际客户库名。生成文件为 rules-upsert.sql 和 rules-upsert.report.json，不覆盖旧文件。原始快照、生成 SQL 和报告都按客户私有资料交接，不提交 Git，不覆盖本目录历史文件，也不自动纳入通用交付包。

## 映射与历史快照

本目录 `ai631-rules-upsert.sql` 只是之前本机旧库的一次快照，用于明确获准使用该基线的场景。它不属于 Flyway，也不会在应用启动时自动运行。**客户当前迁移不能执行这个旧快照来代替重新导出。** 下列行数仅说明历史文件的来源，不是新客户快照的验收值；两个 Running State 表当时为空，不代表客户现在为空。

| 旧表 | 目标表 | 行数 |
|---|---|---:|
| `ace_bit_event_dictionary` | `diag_bit_event_dict` | 252 |
| `ace_fault_event_dictionary` | `diag_fault_event_dict` | 407 |
| `ace_sys_call_dictionary` | `diag_syscall_dict` | 38,869 |
| `ace_running_state_dictionary` | `diag_running_state_dict` | 0 |
| `ace_running_state_rule` | `diag_running_state_rule` | 0 |
| `ace_special_dictionary` | `diag_special_dict` | 71 |

## 新生成 SQL 的导入与验收

先由 Metor 启动执行已发布的 Flyway 表结构迁移，再从工作区或安装根目录明确指定目标数据库执行。以下宿主 mysql 客户端示例中的 TARGET_HOST、TARGET_USER 和端口需要替换为实际值；整栈 Docker 部署优先使用客户指南里的容器内业务账号命令：

```bash
mysql --default-character-set=utf8mb4 \
  -h TARGET_HOST -P 13306 -u TARGET_USER -p metor_service \
  < /secure/rules-upsert.sql
```

脚本保留旧库主键，并使用 `INSERT ... ON DUPLICATE KEY UPDATE` 更新同主键的全部非主键字段；它不删除目标库额外数据，可以重复执行。全部写入位于同一事务中，末尾会输出六张目标表的当前行数。

本次空目标首次导入必须逐表核对报告里的实际源行数与目标行数完全一致，再到规则界面点击“刷新规则快照”，确认六类规则刷新成功后，抽查新增／修改规则并用真实 DAT 新建任务验收。此操作不需要重启 Metor；已有诊断使用原快照。导入及刷新期间暂停规则编辑与新业务任务即可；一致性备份工具自身的短暂停止／恢复行为另计。不要先导入历史快照，不删除目标额外规则来凑行数。已有规则库另行评审合并范围，upsert 不会同步源端删除。

## 工具边界与验证

导出只运行元数据查询和一致性只读事务内的 SELECT，要求六张旧表均为 InnoDB 且字段／类型与已评审映射相符。导出期间不调整旧表结构。缺表、字段变化、非事务引擎、数值溢出、重复主键、必填字段缺失或目标字段容量不足都会拒绝继续；不尝试自动修补客户旧库。

SQL 仅写六张目标规则表，保留主键，对相同主键更新非主键字段，不包含建表、删表、清表或跨库语句。严格模式防止静默截断；文本用 UTF8 十六进制表达式生成，保留引号、反斜杠、换行、NULL 和空字符串。转换本身不执行 SQL。

可在本地一次性 MySQL 容器中重跑真实合成数据验证（不访问开发库，完成后清理自身容器与匿名卷）：

```bash
python3 deployment/tests/verify_ai631_rules_mysql.py
```

源账号仅 SELECT，覆盖六表非空、BIT 布尔值、latin1→UTF8、控制字符／中文、整数边界、首次导入与重复 upsert、逐字段内容和行数一致性。该验证不代替客户实际数据验收。
