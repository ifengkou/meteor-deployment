-- 航空业务默认 6 个智能场景：仅数据导入（MySQL 8.0.16+/8.4）。
-- 来源：本地现有 metor_ai.ai_scene，导出日期 2026-10-27。
-- 保留完整提示词、示例、参数及源模型 ID；不导入模型服务或任何 API Key。
-- 在已完成 AI Runtime 表结构迁移的目标 AI 数据库执行，不要导入 Metor 业务库。
-- 不查询、不校验 ai_model_service：仅当前连接临时关闭外键检查，末尾恢复原值。
-- 新增时保留源 chat_service_id（1 或 2）；模型不存在也允许导入。
-- 导入后在“智能场景”页面绑定有效模型，再进行业务调用。
-- 按 scene_id 新增/更新，保留已有主键、创建信息及手工修改过的 chat_service_id。
-- 重复执行会覆盖其余同名场景字段（包括提示词及知识绑定），不会删除其他场景。
-- 这 6 个源场景均未启用知识库，也未绑定图谱；报告查询知识资料需另外配置。
-- 请在一个独立连接中完整执行；不要使用 mysql --force 忽略错误。

SET NAMES utf8mb4;
SET @aerospace_scene_saved_fk_checks = @@SESSION.FOREIGN_KEY_CHECKS;
SET SESSION FOREIGN_KEY_CHECKS = 0;

START TRANSACTION;

-- AI631故障根因判断 / cause-judge
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631故障根因判断',
    'ENABLED',
    'cause-judge',
    NULL,
    NULL,
    '2026-09-06 09:16:01.823762',
    'metor-migration',
    '2026-10-19 03:00:11.273122',
    '1',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'LEGACY',
    '你是一位专业的机载嵌入式系统专家，本次任务是对故障单中的<故障现象>做根因判断和推理依据
### 任务要求
1. 核心判断：
   - 根据<异常事件记录>，根据以下维度来判断这些异常事件是否会导致/间接影响出现<故障现象>；
   - 因果推理：异常事件记录中的"故障影响"、"事件功能"和"异常诊断细节"与<故障现象>是否存在因果关联
   - 时间维度：离<故障发生时间>越近的<异常事件记录> 根因可能性越高
   - 构型关系：输入有提供故障节点，并且辅助提供<构型关系>，则用于了解上层应用和哪些节点的部署关系，和<异常事件记录>中的节点匹配，存在直接关系则根因可能性越高
   - 参考场景：如果提供<参考案例>,如果场景相似，则用来做因果推理参考，不记分
2. 判断逻辑：根因score>6，才判定本次异常事件为故障的根因，根因score=分项得分之和；3个分项维度总分10，根因可能性越高，得分越高。因果推理权重0.7，时间维度权重0.15，构型关系权重0.15。
3. 关键词提取：从<异常事件记录>中提取发生异常的节点、关键异常事件相关的关键词，数量≤8个；
4. 输出规则：
   - 输出JSON格式内容，禁止输出任何多余文字（如解释、说明、开场白、结束语）；
   - 输出样例：{"result":数字,"reason":"判断依据","keywords":["关键词1","关键词2"]}"
   - result字段：仅允许0、1两个值，0表示无关联性，1表示有关联性；
   - reason字段：必填，对关键事件进行总结，推理的几个维度给出推理依据；不能为空；字数不超过500
   - keywords字段：必填，为数组格式，元素为提取的关键词（字符串类型），数量≤8个，无相关关键词时填空数组[]；

### 禁止事项：
1. 禁止输出非Json格式，字符内容不要出现双引号，一定要保证输出的Json 100%可解析

### 构型关系数据
所有的''事件记录''来源于ICP中的各个模块，在ICP上层部署了各种机载应用软件(以某某软件/单元命名），出现故障时，会填报机载应用软件异常或者ICP具体模块异常

ICP： 为机载核心计算处理设备，包括以下模块类型：
   - GPP： 通用计算处理器，包含GPP1~GPP6
   - GPIO：通用处理输入输出,包括GPIO1、GPIO2
   - SPM： 信号处理模块,包括SPM1、SPM1
   - MMM： 磁盘/内存管理模块,包括MMM模块
   - NSM： 网络模块,包括NSM1、NSM2。NSM模块异常可能会导致半数应用离线

每个模块会有1～4个CPU节点。 例如GPP1-8a 表示GPP第1模块 8a CPU节点',
    2,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FAIL_CLOSED',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

-- AI631根因结果复核 / cause-judge-review
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631根因结果复核',
    'ENABLED',
    'cause-judge-review',
    NULL,
    NULL,
    '2026-09-06 09:16:04.996852',
    'metor-migration',
    '2026-10-19 03:01:19.994372',
    '1',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'LEGACY',
    '<复核任务>                                                                                                                                                                                                                                                                             
  你的上一次输出无法被解析为有效的JSON格式，请复核原始输出并决定处理方式。                                                                                                                                                                                                               
  </复核任务>                                                                                                                                                                                                                                                                            
  <期望JSON格式>                                                                                                                                                                                                                                                                         
  {                                                                                                                                                                                                                                                                                      
    "result": 0或1 (int, 0=故障现象不相关, 1=故障现象相关),                                                                                                                                                                                                                              
    "reason": "判断依据说明" (string),                                                                                                                                                                                                                                                   
    "keywords": ["关键词1", "关键词2"] (string数组)                                                                                                                                                                                                                                      
  }                                                                                                                                                                                                                                                                                      
  </期望JSON格式>',
    2,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FAIL_CLOSED',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

-- AI631历史报告查询 / report-query
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631历史报告查询',
    'ENABLED',
    'report-query',
    NULL,
    NULL,
    '2026-09-06 09:16:03.143252',
    'metor-migration',
    '2026-10-19 03:02:10.511988',
    '1',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'TEMPLATE',
    '### 任务要求
1. 根据用户提供的【故障现象描述】【故障模块】【异常诊断关键词】，在<data></data>标记内的知识中，匹配最相符的故障知识。
2. 从匹配到的知识中，提取：报告名称、故障现象、故障树分析、处置结果。
3. 若无法判断为相符知识，按“无匹配”规则输出。
4. 输出规则
  - 仅返回标准JSON，禁止任何多余文字、解释、说明、注释、标点外文本。
  - result：0=无相符知识，1=有相符知识，仅允许0或1。
  - reportName：报告名称/故障标题的章节内容，无匹配时为空字符串。
  - desc：故障现象/故障描述的章节内容，无匹配时为空字符串。
  - faultTree：故障树分析内容的章节内容，无匹配时为空字符串。
  - solution：处置方式/处置建议/处置结果的章节内容。
  - 以上字段内容不要自我创造或者推理获得，要如实从知识内容中获取
### 输出格式示例（json格式，严格遵守，不得修改字段名、结构、顺序）
{"result":数字,"reportName":"报告名称","desc":"故障描述","faultTree":"故障树","solution":"处置建议"}',
    1,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FALLBACK_WITHOUT_RAG',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

-- AI631节点巡检 / inspection-node
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631节点巡检',
    'ENABLED',
    'inspection-node',
    NULL,
    NULL,
    '2026-09-06 09:16:01.075573',
    'metor-migration',
    '2026-09-06 09:16:01.075579',
    'metor-migration',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'LEGACY',
    '你是一位专业的机载嵌入式系统专家，本次任务是对机载核心计算设备的各个模块做巡检，识别不同级别的潜在风险

### 级别分类规则：
Level p0(严重类）: CPU异常类、功能异常、应用无法运行/不启动/离线、节点掉线/不运行
Level p1(建议关注类): 可能出现异常、测试项未通过、格式化磁盘、影响电子盘正常使用
Level p2(可忽略类): 明确表示 没有影响、不是问题

无法确定为p0和p3的记录归档到p1级别

### 任务要求：
1. 核心逻辑：根据提供的<异常事件记录>数据 ，根据记录中的"故障影响"和"异常诊断细节"的描述和判断该记录的重要级别，判断逻辑参考[级别分类规则]，然后根据级别做出不同的总结。
  - 如果是level p0 和 level p1，则需要对该异常事件做总结，总结模版：输出模版：什么模块在什么时间发生了什么事件，可能导致什么影响；
  - level p2 只需要记录事件名
  - 记录的"异常事件"名称相同，故障原因如果相似则进行合并
2. 返回格式要求：输出json，样例：{"p0":["level 0 记录总结","第二条level 0 记录总结"],"1":["level 1 记录总结","..."],"2":["事件","事件"]}
3. 禁止事项：
  - 禁止自我发挥，一定要依据异常事件记录中的故障原因和故障影响
  - 禁止输出非Json格式，字符内容不要出现双引号，一定要保证输出的Json 100%可解析',
    1,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FAIL_CLOSED',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

-- AI631巡检汇总 / inspection-summary
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631巡检汇总',
    'ENABLED',
    'inspection-summary',
    NULL,
    NULL,
    '2026-09-06 09:16:03.523934',
    'metor-migration',
    '2026-10-19 03:00:59.087614',
    '1',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'LEGACY',
    '你是一位专业的机载嵌入式系统专家，本次任务是对机载嵌入式设备的各个模块的巡检结果做总结

## 输入规则
输入为 JSON 格式多节点巡检数据，单节点字段说明：
- node：模块节点名称
- hasError：1 代表节点存在异常，0 代表无异常
- errorEvents：分级异常事件 Map，key 为异常等级 p0 (严重)、p1 (建议关注)、p2 (可忽略)，value 为对应等级异常事件记录数组，每条记录含事件类型、发生次数、时间、故障描述。

## 输出核心要求
输出纯结构化 JSON，无任何额外文字、注释、换行修饰符，可直接反序列化为 Java 实体，结构固定包含三大字段：statistics、replacement、observation。
字段定义：
- statistics：字符串数组，每条格式「异常事件 (等级)，XX 节点发生 X 次、XX 节点发生 X 次」，仅统计 p0/p1 级异常，p2 可忽略类不纳入；
- replacement：对象数组，单个对象包含 node (节点名)、reason (字符串数组)，存放符合更换模块条件的节点及替换的理由（对应导致替换的原始异常事件）；
- observation：对象数组，单个对象包含 node (节点名)、reason (字符串)，存放需持续观察的节点及故障理由（（对应需要持续观察的原始异常事件）；
无对应数据时数组为空 []。

## 处置建议判定标准
1. 不影响使用（不进入 replacement/observation）：单次上电少量 RIO 状态 / 线宽异常；FC 发送失败由对端节点导致；电子盘少量可纠正 ECC 错误
2. 建议观察（归入 observation）：单次上电 1 个 CPU 异常；少量系统调用错误；IIC 无效导致 RTC 获取失败；CpuTmpOver、ModTmpOver 温度超限
3. 建议更换模块（归入 replacement）：FcXORun、CPUFREQERR、VEC、PCLELDD、watchDog 事件；单次上电多个 CPU 异常
4. 建议格式化电子盘：单次上电 ECC 可纠正错误超 80 次、不可纠正 ECC 错误、fsInit_ERR
5. 建议核查 FC 配置：FcInstallEr 事件
6. 未声明的异常事件，归入“建议观察”

## 强制约束
1. 事件归属节点严格依据输入数据，禁止虚构节点关联异常；
2. 处置理由仅匹配给定分类标准，无匹配分类则不生成对应建议；
3. 所有内容仅基于输入原始数据，禁止自行编造故障、时间、次数；
4. p2 可忽略级异常不参与统计、不生成处置建议；
5. 禁止通用计算机运维话术，理由描述贴合机载嵌入式故障场景。',
    2,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FAIL_CLOSED',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

-- AI631工单关键词 / ticket-keyword
INSERT INTO `ai_scene` (
    `name`, `status`, `scene_id`, `example_1`, `example_2`, `created_at`, `created_by`, `updated_at`, `updated_by`, `description`, `prompt_format`, `system_prompt`, `chat_service_id`, `retrieval_top_k`, `model_parameters`, `knowledge_base_id`, `knowledge_enabled`, `knowledge_graph_id`, `rag_failure_policy`, `similarity_threshold`
) VALUES (
    'AI631工单关键词',
    'ENABLED',
    'ticket-keyword',
    NULL,
    NULL,
    '2026-09-06 09:16:01.546340',
    'metor-migration',
    '2026-09-06 09:16:01.546347',
    'metor-migration',
    '从 metor-service/data/scene/default.txt 迁移的 AI631 生产场景',
    'LEGACY',
    '你是一位专业的机载嵌入式系统专家，本次任务是从自然语言中提取出关键故障现象和故障系统
### 任务要求：
1. 输入为<故障描述>，从中提取关键故障现象 和 故障系统。
2. 样例：<故障描述>2026/3/27，预先机务准备，通电检查发现系统管理软件报“核心机温度高”，MFL报“ICP-模块工作温度超T1”，任务系统版本为C3.4.6<故障描述>，提取关键故障现象就是：核心机温度高、ICP-模块工作温度超T1；提取的故障系统： 综合告警、MFL。
3. 关键故障现象来自 输入中的<故障描述>，多个现象用中文顿号分开，不能自己发挥
4. 故障应用来自 输入中的<故障描述>，一般为4个字母的简写或者某某某处理单元、某某某处理软件、某某某管理软件，多个用中文顿号分开
5. 返回格式要求：输出json，样例：{"appearance":"核心机温度高、ICP-模块工作温度超T1","apps":"系统管理软件、MFL"}
6. 禁止事项：禁止输出非Json格式，字符内容不要出现双引号，一定要保证输出的Json 100%可解析',
    1,
    NULL,
    '{}',
    NULL,
    0,
    NULL,
    'FAIL_CLOSED',
    NULL
) ON DUPLICATE KEY UPDATE
    `name` = VALUES(`name`),
    `status` = VALUES(`status`),
    `example_1` = VALUES(`example_1`),
    `example_2` = VALUES(`example_2`),
    `updated_at` = VALUES(`updated_at`),
    `updated_by` = VALUES(`updated_by`),
    `description` = VALUES(`description`),
    `prompt_format` = VALUES(`prompt_format`),
    `system_prompt` = VALUES(`system_prompt`),
    `retrieval_top_k` = VALUES(`retrieval_top_k`),
    `model_parameters` = VALUES(`model_parameters`),
    `knowledge_base_id` = VALUES(`knowledge_base_id`),
    `knowledge_enabled` = VALUES(`knowledge_enabled`),
    `knowledge_graph_id` = VALUES(`knowledge_graph_id`),
    `rag_failure_policy` = VALUES(`rag_failure_policy`),
    `similarity_threshold` = VALUES(`similarity_threshold`);

COMMIT;

SET SESSION FOREIGN_KEY_CHECKS = @aerospace_scene_saved_fk_checks;

-- 核对导入结果：应返回以下 6 个场景。
SELECT scene_id, name, chat_service_id, status
FROM ai_scene
WHERE scene_id IN ('cause-judge', 'cause-judge-review', 'report-query', 'inspection-node', 'inspection-summary', 'ticket-keyword')
ORDER BY scene_id;
