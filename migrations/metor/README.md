# AI631 规则基线

`ai631-rules-upsert.sql` 为六张诊断规则表的固定基线。Metor 完成 Flyway 建表后，可在获准使用该基线的环境显式执行。SQL 在单个事务内按主键新增或更新规则，保留目标表中的其他记录。

| 目标表 | 基线行数 |
| --- | ---: |
| `diag_bit_event_dict` | 252 |
| `diag_fault_event_dict` | 407 |
| `diag_syscall_dict` | 38,869 |
| `diag_running_state_dict` | 0 |
| `diag_running_state_rule` | 0 |
| `diag_special_dict` | 71 |

执行后核对行数，按[规则与业务资料](../../customer-docs/business-config.md#规则与业务资料)刷新快照并验证诊断。客户 ZIP 回归也使用此固定基线。
