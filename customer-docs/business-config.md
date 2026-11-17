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
| 巡检汇总复核 | inspection-summary-review |
| 单据关键词 | ticket-keyword |

通过平台创建获准的模型服务、提示词、检索参数、知识库／图谱及场景绑定，逐项用真实输入验证。自定义 ID 时同步修改私有 env 对应的 METOR_AEROSPACE_AI_SCENES_ 配置。

巡检汇总复核默认关闭。启用时设置 `METOR_AEROSPACE_AI_INSPECTION_SUMMARY_REVIEW_ENABLED=true`，为复核场景绑定可用模型并重新创建 Metor 容器。已有巡检汇总场景的环境可在 AI 数据库执行 `deployment/migrations/ai-runtime/inspection-summary-review.sql`（随部署仓库提供），也可在平台手工建立该场景。执行 SQL 后，查询应返回一条复核场景记录。复核校验原始数据与候选总结，未通过的模块结论不写入报告。

## 航空业务 AI 配置

航空诊断默认调用 AI Runtime，准备脚本生成的 METOR_AEROSPACE_AI_ENABLED=true。完成模型服务和场景配置后进行业务验收。该开关仅用于显式禁用航空业务的 AI 调用；平台模型服务和场景调试使用独立的平台 AI 代理。

先按[运维命令入口](operations.md#命令入口)选定 ICP_STACK 和原 ICP_ENV，核对运行配置中的正常业务值：

```dotenv
METOR_AEROSPACE_AI_ENABLED=true
```

通过平台保存模型、提示词和场景绑定后可直接调用。只有修改了原 runtime/config/docker.env 中的业务开关、场景映射或调用参数，才需先备份配置，在维护窗口暂停新业务、等待任务结束后重建 Metor 和前端：

```bash
ICP_STACK=/opt/icp-diag/deployment/scripts/local-stack.py
ICP_ENV=/opt/icp-diag/runtime/config/docker.env

python3 "$ICP_STACK" --env-file "$ICP_ENV" compose stop frontend metor
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --force-recreate --wait metor
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose up -d --no-deps --force-recreate --wait frontend
```

核对容器内实际变量：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T metor sh -c \
  'env | grep -E "^(METOR_AEROSPACE_AI_ENABLED|METOR_PLATFORM_AI_RUNTIME_BASE_URL|METOR_AEROSPACE_AI_BASE_URL)="'
```

预期 METOR_AEROSPACE_AI_ENABLED=true，两个 BASE_URL 均为 http://ai-runtime:8090。前者地址用于平台 AI 代理，后者用于航空业务场景调用。容器间使用服务名和内部端口，端口映射的 18092 供宿主维护使用。

完成后跑真实故障与巡检，确认 AI Runtime 收到相应场景请求并返回业务结果。

## 规则与业务资料

更新规则后，在规则界面点击“刷新规则快照”。该操作会重新加载全部六类规则。确认页面提示“规则刷新完成”，并检查 Metor 日志中的 `failedCount=0`。随后使用真实 DAT 新建诊断任务，抽查规则命中和业务结果。

按范围准备知识库原文、图谱、DAT／ZIP／报告样本、期望结果、普通用户及系统 API Key／scope。以真实 DAT 完成 JNI 解密、解析和事件入库，再验证故障／巡检、报告及原始文件导出。JNI 文件存在与健康检查通过不能替代这些业务操作。

客户凭据、模型 API Key、业务样本和备份通过约定的安全渠道保存与交接，不进入公共日志或截图。

## 航空诊断文件配置

Compose 首次创建 Metor 容器时会自动准备宿主机目录 `/data/metor/ai631/conf`，并只读挂载到容器的 `/opt/metor/ai631/conf`。如需变更宿主机位置，在原运行 env 中设置 `METOR_RULES_CONFIG_HOST_PATH` 为绝对路径，再重建 Metor。

Metor 启动时分别检查 `fault_scene.json`、`readArg.json`、`event_seq.json` 和 `event_pair.json`。目录中有同名文件时使用该文件，缺少的文件使用应用随附默认值。只放需要调整的文件即可。现场文件不可读或格式错误时，按启动日志修正对应文件。原先缺少事件序列或事件对文件的环境，更新后会按内置默认规则运行对应检查。

替换现场配置前，暂停新诊断、等待在途任务结束并备份宿主机配置目录。以可被 Metor 读取的权限保存文件，然后用当前部署入口重启服务：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose restart metor
```

检查 readiness 和日志中的各文件来源，并完成实际诊断验收。切换挂载路径时用 `compose up -d --no-deps --force-recreate --wait metor` 重建容器。宿主机配置目录需单独纳入备份。
