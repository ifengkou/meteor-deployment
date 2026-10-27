# 软件授权

Metor 与 AI 使用同一份商业许可，各自本地校验。客户无需签发工具、私钥或宿主 SDK。首次安装先按[安装指南](install.md)显式完成 license-init；已有安装不重复初始化。

## 申请与导入

1. 核对宿主 UTC 正确，管理员登录“设置 → 软件授权”。页面管理当前 Metor 状态，不聚合 AI 状态。
2. 取得机器申请，下载原始申请 JSON 或完整抄写 IC1 机器码，连同客户信息、发行版本和约定期限交服务方。绑定许可需要当前真实宿主及安装身份；不要发送安装主密钥。
3. 收到商业许可 JSON 后核对文件摘要、客户、绑定方式及 UTC 生效／到期时间，在同一页面刷新详情后选择原文件导入。
4. 首次确认应为 APPLIED，重复同文件应为 ALREADY_APPLIED。当前应生效的许可状态须为 ACTIVE，再验证一个受控业务操作。

只有 Metor 通过 SDK 发布共享商业文件，AI 只读并独立验证；不要手工 copy 文件至 active.license.json。Metor 显示有效后，实施人员还应确认 AI 本地状态及真实摄取／检索正常。没有商业许可时登录、健康和原权限下的维护仍可用，受控操作被拒绝。

普通账号或系统 API Key 无导入权限。HTTP 202、OUTCOME_UNKNOWN 或超时不代表成功或失败：保留同文件，刷新状态并重试核对，不重新初始化，也不删除共享文件来判断结果。

## 续期与迁机

商业到期需办理新许可并通过原页面导入；重复下载或重试原文件不续期。迁机、更换安装身份或恢复不同宿主前，先与服务方确认绑定处理，不能复制另一安装的身份或修改签名文件。

升级或镜像回退保留整个最新 runtime/license，包括 identity、主密钥、共享商业许可、两服务 clock 和恢复挑战。不要用旧 clock 覆盖当前状态。

## 时间异常恢复

仅在时间回拨、时间记录损坏或持久化异常时使用，普通到期不通过时间恢复解决。先核实并校正宿主 UTC；会话因校时失效时重新登录。两个服务独立恢复，只操作异常的服务。

Metor 管理员在授权页面取得恢复申请，将申请对象或安装 UUID、服务 metor 与 RC1J 恢复码交服务方；收到签名恢复文件后在约定窗口内从同页应用。

AI 由运维从安装根目录取得申请：

```bash
python3 deployment/scripts/local-stack.py license-recovery request --output /absolute/private/ai-recovery-request.json
```

输出路径必须尚不存在。服务方使用申请对象签出针对 ai 的恢复文件；无法传申请文件时，按受控渠道提供安装 UUID、服务 ai 和 RC1A 恢复码。文件入网后在窗口内执行：

```bash
python3 deployment/scripts/local-stack.py license-recovery apply --file /absolute/private/ai-recovery.json
```

APPLIED／ALREADY_APPLIED 表示本次恢复已确认；OUTCOME_UNKNOWN 仍保留同文件重试核对。恢复不修改商业期限、绑定或另一服务状态，无需手工编辑 JSON，也不删除 clock 或更换安装身份。

## 常见结果

| 状态 | 操作 |
| --- | --- |
| UNLICENSED／MISSING | 完成申请、签发与导入 |
| NOT_YET_VALID／EXPIRED | 核对 UTC，等待生效或办理续期 |
| INVALID／绑定不符 | 核对当前宿主、安装和原签名文件，联系服务方 |
| POLICY_INVALID | 恢复正确发行镜像，不以环境变量替换包内信任 |
| CLOCK_ROLLBACK／CLOCK_STATE_INVALID | 校正 UTC 后办理对应服务的签名恢复 |
| OUTCOME_UNKNOWN | 保留文件，刷新并重试；检查磁盘、共享目录和状态目录权限 |
