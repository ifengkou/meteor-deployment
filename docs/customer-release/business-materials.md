# 另行准备的模型、业务资料与凭据

本页与镜像制作并行执行。通用包明确不包含模型权重、业务数据和客户凭据；镜像加载成功不意味着这些资料已存在。由实施负责人维护客户专用清单，记录来源、版本／摘要、存放位置、配置映射及验收结果。

## 1. Embedding 完整制品

默认使用 `bge-small-zh-v1.5`。我方制作人员从已批准的完整模型副本取得权重，记录上游模型标识／revision、配置、tokenizer、权重及全部运行所需文件；交付真实文件，不保留指向制作机缓存的悬空链接，不交付 Git LFS 指针当权重。

在一个独立 staging 目录内整理为 `model/`，其根下直接可见 `config.json`、权重、tokenizer 等文件。写入 `model-manifest.json` 记录模型 ID、来源 revision、归一化选择、制品日期和文件说明，再生成模型目录内的 SHA256SUMS。例如从 staging 根目录执行：

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib
root = Path('model')
files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
if not files or any(p.is_symlink() for p in root.rglob('*')):
    raise SystemExit('请先准备完整、无软链接的模型文件')
with (root / 'SHA256SUMS').open('x') as out:
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.write(f'{digest}  {path.relative_to(root)}\n')
PY
tar -czf embedding-bge-small-zh-v1.5.tar.gz model
sha256sum embedding-bge-small-zh-v1.5.tar.gz
```

目录已有 SHA256SUMS 时先核对来源，不覆盖它伪造新基线。打包前在匹配本次运行依赖的环境中，以离线方式真正加载模型与 tokenizer 并编码一段中文，记录实际向量维数和检索结果；仅检查 config.json 或文件列表不算加载通过。模型使用／再分发条件由制作方按取得渠道核对并随专用资料保留。

客户将获准模型包和独立交接的归档摘要核对后，在 `/opt/icp-diag` 执行：

```bash
sh deployment/scripts/install-model.sh /absolute/embedding-bge-small-zh-v1.5.tar.gz \
  /opt/icp-diag/runtime/models/embedding
```

目标目录必须不存在；脚本验证包内模型 manifest 和 SHA256SUMS，再将模型设为只读。运行时清单 `runtime/config/embedding/docker.json` 应使用稳定 ID `bge-small-zh-v1.5`、容器路径 `/models/embedding`，宿主路径通过 env 只读挂载。未准备的其他模型保持 disabled。

AI 启动后 readiness 的 embeddingModel 应为 UP，再创建知识库、上传获准文本、等待索引成功并检索命中。更换模型权重、tokenizer、normalize 或模型身份时不能沿用不兼容旧向量；新建知识库重建索引后再切换场景绑定。

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

六场景与模型就绪后设置 `METOR_AEROSPACE_AI_ENABLED=true`，执行：

```bash
python3 deployment/scripts/local-stack.py compose \
  up -d --no-deps --force-recreate --wait metor
```

分别跑真实故障和巡检；关闭 AI 的解析成功不等于最终业务成功。

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

数据库密码与 JWT 密钥由首次 init 随机生成，env 权限 0600；首管理员由授权人员先完成初始化，不设置通用默认客户口令。另行准备普通操作员、所需系统 API Key／scope、模型凭据、入口域名证书及其负责人。

凭据通过客户约定的安全渠道交接，不放通用包、Git、发行 manifest、截图或验收日志。备份中的私有 env、数据库和安装主密钥也按敏感资料保护。

客户专用清单逐项标明“我方交付／客户提供／本次不启用”、版本／摘要、路径或业务 ID、配置关系、完成日期和验收结果。最终保留与本次镜像兼容的模型副本、场景／规则清单、业务备份及恢复步骤。
