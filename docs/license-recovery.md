# 离线时间异常恢复

适用 SDK 0.6.0、issuer 0.3.0。只在回拨或时间记录异常时操作；商业许可到期需要续期，普通导入不会重置时间状态。Metor 和 AI 各自独立恢复，只恢复发生异常的服务。若两个服务都异常，各自取得申请和应用对应文件。

## 前置条件

- 已加载本次产品镜像及完整依赖，服务正在运行；无需客户联网、安装 SDK 或停止服务。
- 运维先核实并校正宿主 UTC。不要通过删除 clock、重新初始化安装或反复调时间处理异常。
- Metor 使用平台管理员登录凭据；AI 客户端使用容器内现有安装凭据，不新增账号体系。
- 我方签发私钥、签发工具和签发记录留在我方，不交付客户。

## 1. 取得申请

Metor：管理员登录后调用 `POST /platform/admin/license/recovery/request`，空请求体；按部署现有认证方式传递登录凭据。例如在安全终端设置 `METOR_ORIGIN` 和 `METOR_ADMIN_TOKEN` 后：

```sh
umask 077
curl --fail-with-body --request POST \
  --header "Authorization: Bearer $METOR_ADMIN_TOKEN" \
  "$METOR_ORIGIN/platform/admin/license/recovery/request" \
  --output metor-recovery-response.json
```

响应沿用平台信封，签发申请为其中的 `data` 对象；可单独保存 `data` 为 `metor-recovery-request.json`，也可抄写该对象的产品、安装 UUID、服务和恢复码。

AI：从工作区或交付包根目录执行，替换配置和输出绝对路径：

```sh
python3 deployment/scripts/local-stack.py --env-file /absolute/docker.env \
  license-recovery request --output /absolute/ai-recovery-request.json
```

脚本通过 `compose exec -T ai-runtime` 调用容器内维护客户端；客户端生成短期 ControlProof，直接请求本 AI 服务，不经过 Metor、不直接修改 clock。宿主只需 Python 标准库和 Docker。申请文件以 0600 创建，不覆盖已有文件。

已有申请仍适用时返回同一申请。只有 APPLIED/ALREADY_APPLIED 是确认完成；HTTP 202 或 OUTCOME_UNKNOWN 表示持久性尚未确认，请重试同一操作，取得申请尚未确认时不要交给签发方。

## 2. 我方签发恢复文件

允许文件出网时，将申请对象文件交给我方。禁止出网时，抄写 `product_id`、`installation_id`、`service` 和 `recovery_code`；Metor 是 RC1J、AI 是 RC1A，IC1 机器码不可替代恢复码。

在我方签发环境调用：

```sh
license-issuer sign-recovery --product icp-diag \
  --key-id vendor-key-id --private-key /absolute/vendor/private.pem \
  --request-file /absolute/vendor/ai-recovery-request.json \
  --window-start "$RECOVERY_START_UTC" --window-end "$RECOVERY_END_UTC" \
  --records-dir /absolute/vendor/records --output /absolute/vendor/recovery.json \
  --issuance-id "$ISSUANCE_UUID"
```

`RECOVERY_START_UTC` 和 `RECOVERY_END_UTC` 使用当前约定的 UTC，格式如 `2026-10-23T10:00:00Z`；签发时刻不得晚于窗口开始，窗口结束不得晚于签发时刻七天。为文件入网和客户操作预留时间。`ISSUANCE_UUID` 使用本次唯一 UUID，同申请同参数重试必须复用原编号及记录目录，避免重复签发。

手抄模式把 `--request-file` 替换为：

```sh
--installation-id "$INSTALLATION_UUID" --service ai --recovery-code "$RECOVERY_CODE"
```

Metor 的 service 改为 `metor`。完整参数及重复签发行为见 [issuer 中文说明](../../license-issuer/README_cn.md)。

## 3. 应用恢复

将我方恢复文件入网。Metor 管理员以 multipart 单个 `file` 上传：

```sh
curl --fail-with-body --request POST \
  --header "Authorization: Bearer $METOR_ADMIN_TOKEN" \
  --form file=@/absolute/recovery.json \
  "$METOR_ORIGIN/platform/admin/license/recovery/apply"
```

AI：

```sh
python3 deployment/scripts/local-stack.py --env-file /absolute/docker.env \
  license-recovery apply --file /absolute/recovery.json
```

文件最大 64KiB。AI 脚本通过标准输入传给容器客户端，无需复制到容器或挂载目录。SDK 在同一 Runtime 中校验、原子提交并刷新内存，无需重启。不要把恢复文件 copy 成 `license.json`；它必须由应用恢复 API 消费。

## 4. 判断结果

- `APPLIED`：首次确认完成；`ALREADY_APPLIED`：同文件此前已完成。再次提交不会降低高水位或重复增加 epoch。
- `OUTCOME_UNKNOWN` / HTTP 202：保留文件并用同文件重试，不当作成功。若持续异常，检查本服务 state 目录磁盘和写权限。
- `LICENSE_RECOVERY_TARGET_MISMATCH`：申请已不适用，重新取得当前申请交我方签发；不要更改安装 ID。
- 无需恢复、窗口无效、签名或格式错误：按响应检查目标服务、UTC、文件及公钥版本。恢复窗口精确比较，不使用一天回拨容差。
- 恢复成功后的商业状态仍可能为 EXPIRED、NOT_YET_VALID 或 MISSING，需要另行处理商业许可。

最后重新查询本服务授权状态，并重试一个受控操作。恢复不改商业许可字节、期限或机器绑定，不读取或修改另一服务时间文件。

## 包内策略异常

POLICY_INVALID 表示包内 API 清单或构建摘要异常。用同版本正确发行包或镜像恢复并重启服务；运行中不重载文件，不支持以外部空清单关闭检查。固定关键方法也会检查该状态。时间恢复只修复时间状态，不能修复策略异常。

## 验证边界

本阶段自动验证覆盖合成时钟、申请复用、在线恢复并发、未知持久性、两个语言互通、策略损坏和重启行为，均使用临时目录与合成密钥，不调整真实机器时钟。客户 Linux 的实际 UID/GID、挂载和最终镜像验收仍按交付阶段执行。
