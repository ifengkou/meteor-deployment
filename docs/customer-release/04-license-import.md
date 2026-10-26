# 阶段四：授权导入与最终验收

执行方：客户平台管理员／我方实施。前提是完成[部署](02-deploy.md)，取得针对当前安装、由匹配正式公钥签出的[商业许可](03-license-issue.md)。本阶段不需要联网安装依赖。

## 1. 导入前确认

核对文件交付摘要、客户名称、产品、绑定方式及约定 UTC 生效／到期时间。先确认宿主时钟正确；校时导致会话失效时重新登录。

由管理员打开“设置 → 软件授权”，刷新当前详情与文件摘要。普通账号或 API Key 没有导入权限。页面管理的是 Metor 本地状态，不能把它当作 AI 聚合状态。

## 2. 通过页面导入

1. 选择我方交付的原始商业许可 JSON，执行导入，不编辑 JSON、不解包重写字段。
2. 确认 `APPLIED` 后刷新详情，检查客户、类型、绑定、期限与实际状态。重复提交同文件应为 `ALREADY_APPLIED`。
3. 当前应生效的文件必须显示 `ACTIVE`。导入动作已确认不代表商业有效：到期、未生效或时间异常仍按实际状态处理。
4. HTTP 202／`OUTCOME_UNKNOWN` 或网络超时只代表结果未确认。保留同一文件，刷新核对并用同文件重试；不要靠删除共享文件、重新初始化或新签许可判断结果。

只有 Metor 经 SDK 共享发布商业许可，SDK 在原子替换前确认 GID 21000／0640；AI 对共享目录只读并独立验证。不要手工 copy 文件到 `shared/active.license.json` 绕过导入 API。AI 停机不阻止 Metor 本地导入；启动 AI 后仍须确认它能读取和接受新文件。

若用运维 API，管理员详情是 `GET /platform/admin/license`，商业申请是 `GET /platform/admin/license/request?format=json|file`，导入是 `POST /platform/admin/license/import`，multipart 字段为 `file` 和 `expectedFileDigest`。摘要必须取刚读取的当前文件摘要，无当前文件时传 `NONE`；日常实施优先使用已配套的页面完成摘要核对及导入。

## 3. 独立核对 AI 状态

从安装根目录执行下面的只读查询。它在运行中的 AI 容器内，通过现有安装凭据生成短期 ControlProof，调用本服务内部状态接口；不输出凭据、不读写 clock、不经 Metor：

```bash
python3 deployment/scripts/local-stack.py compose exec -T ai-runtime python - <<'PY'
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from license_sdk.proofs import ICP_CONTROL
from app.licensing import create_license_resource

runtime = create_license_resource(Path('/run/icp-license'), Path('/run/icp-host/machine-id')).runtime
if runtime is None:
    raise SystemExit('客户模式 Runtime 不可用，检查本次发行配置')
path = '/internal/license/status'
try:
    token = runtime.control_proof(config=ICP_CONTROL).issue(
        scope='LICENSE_STATUS', method='GET', path=path, body=b'',
        now=datetime.now(timezone.utc),
    )
finally:
    runtime.close()
request = urllib.request.Request('http://127.0.0.1:8090' + path,
                                 headers={'Authorization': 'Bearer ' + token})
with urllib.request.urlopen(request, timeout=10) as response:
    print(json.dumps(json.load(response), ensure_ascii=False))
PY
```

响应 `data.state` 应为 `ACTIVE`，`data.policyState` 为 `VALID`。调用失败时检查对应日志及真实安装凭据，不用 readiness 冒充授权状态。Metor 与 AI 都确认后，分别验证一个获准受控操作。真实向量检索验证 AI 受控业务，故障／巡检验证整条链路。

## 4. 最终验收清单

以下在原生客户目标平台上使用本次最终镜像和配置执行，记录版本、镜像 ID、时间、执行人与结果：

- [ ] 无商业许可时，登录和有鉴权的维护可用；受控接口拒绝且没有业务副作用。普通账号不能导入或恢复。
- [ ] 当前正式许可首次导入、同文件重复、详情刷新均正确；Metor 与 AI 独立 ACTIVE，重启后仍有效。
- [ ] 由人工按软件授权页面清单验证复制、下载、上传、错误、未知结果及新增交互；不以 API 测试代替人工页面结果。
- [ ] 完成[业务资料准备](business-materials.md)，核对模型与六场景真实调用，不以固定响应或关闭航空 AI 替代。
- [ ] AMD64 交付核对 JNI 动态依赖，再以获准 DAT 样本真实解密、解析和入库；检验故障／巡检、源复用、报告及全部原根导出。
- [ ] 若交付多文件前端能力，实际验证多选／多根操作与数量边界；否则明确本发行范围。
- [ ] 用客户最终入口完成登录、上传、长任务及报告下载；断开公网后验证按合同应离线的功能。客户内网 Chat 仍需保持可达。
- [ ] 执行一致性备份和同宿主隔离空目标恢复，核对数据库、业务文件、向量索引、许可字节和权限；旧安装另验升级／回退兼容。

备份入口（新目录，具有许可备份所需权限）：

```bash
sudo python3 deployment/scripts/local-stack.py \
  --env-file /opt/icp-diag/runtime/config/docker.env \
  backup /opt/icp-diag/runtime/backups/acceptance-release-20261026-1
```

这会短暂停写并恢复原运行状态；此前先等待业务任务结束。隔离恢复步骤按[备份恢复](../backup-restore.md)，不要覆盖正在运行的目录。备份不包含模型权重和镜像，二者另行保留；备份含私有配置和安装主密钥，存放受保护介质并留异机副本。

## 5. 常见状态

| 状态／结果 | 处理 |
| --- | --- |
| MISSING／LICENSE_REQUIRED | 取得当前申请，完成签发与页面导入 |
| NOT_YET_VALID／EXPIRED | 核对 UTC 和合同期限，等待生效或办理续期 |
| INVALID／错机 | 核对文件、正式信任、宿主与安装，重新取得当前申请；不改身份绕过绑定 |
| POLICY_INVALID | 恢复正确发行镜像；运行环境不能替换包内策略和信任 |
| CLOCK_ROLLBACK／CLOCK_STATE_INVALID／时间持久化异常 | 先校正宿主 UTC，按[单服务恢复](../license-recovery.md)操作 |
| OUTCOME_UNKNOWN | 保留同文件、刷新并重试核对，检查共享／state 存储权限和磁盘 |

Metor 恢复从页面申请 RC1J；AI 使用 `local-stack.py license-recovery request/apply`，详见恢复手册。两端状态独立，商业文件共用。恢复不续期、不换机；升级与镜像回退保留最新授权状态，不用旧 clock 覆盖。

验收完成后归档发行清单、商业文件摘要、各端状态、业务对账和备份恢复记录，由验收负责人确认后交付。
