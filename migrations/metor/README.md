# AI631 规则数据迁移

`ai631-rules-upsert.sql` 保存从旧 MySQL 导出的六类诊断规则数据。它是需要部署人员显式执行的数据迁移，不属于 Flyway，也不会在应用启动时自动运行。

## 表映射与导出行数

| 旧表 | 目标表 | 行数 |
|---|---|---:|
| `ace_bit_event_dictionary` | `diag_bit_event_dict` | 252 |
| `ace_fault_event_dictionary` | `diag_fault_event_dict` | 407 |
| `ace_sys_call_dictionary` | `diag_syscall_dict` | 38,869 |
| `ace_running_state_dictionary` | `diag_running_state_dict` | 0 |
| `ace_running_state_rule` | `diag_running_state_rule` | 0 |
| `ace_special_dictionary` | `diag_special_dict` | 71 |

## 执行

先由 Metor 启动执行已发布的 Flyway 表结构迁移，再从工作区或安装根目录明确指定目标数据库执行：

```bash
mysql --default-character-set=utf8mb4 \
  -h <target-host> -P <target-port> -u <target-user> -p <target-database> \
  < deployment/migrations/metor/ai631-rules-upsert.sql
```

脚本保留旧库主键，并使用 `INSERT ... ON DUPLICATE KEY UPDATE` 更新同主键的全部非主键字段；它不删除目标库额外数据，可以重复执行。全部写入位于同一事务中，末尾会输出六张目标表的当前行数。

执行完成后，核对目标行数不低于上表导出行数。两个 Running State 表在本次旧库导出时为空，预期行数为 0。
