# 本机 Docker 授权人工验收环境（2026-10-23）

本次已构建并运行独立验收栈。它使用真实模式前端、固定 `CUSTOMER_REQUIRED` 服务镜像和验收专用签发密钥，使用合成 machine-id；不代表客户 Linux 宿主身份验收。已有 `icp-diag-local` 栈继续运行。历史 `restore-check` 数据卷保留，本安装使用新的独立命名数据卷。

## 访问与账号

| 服务 | 地址 | 镜像 |
| --- | --- | --- |
| 前端 / 软件授权 | http://127.0.0.1:18181/platform/settings/license | `metor-platform-frontend:manual-settings-2b7dfdc9cf21` |
| Metor | http://127.0.0.1:18081 | `metor-service:manual-db221a2` |
| AI Runtime | http://127.0.0.1:18093 | `ai-runtime-service:manual-b2675e3` |
| MySQL | 仅容器网络 | `mysql:8.4` |

管理员用户名 `license-admin`，普通用户名 `license-user`。密码见工作区 `runtime/license-manual/accounts.json`，该私有文件权限为 `0600`，未纳入 Git。登录时选择真实模式。

当前两个服务均为 `ACTIVE / TERM / HOST_INSTALL`，同一商业许可有效至 **2026-11-22 01:02:08 UTC**（北京时间 09:02:08）。页面只管理 Metor 的时间恢复，AI 独立校验、独立恢复。

数据库为空白验收库，仅初始化测试账号；未复制原安装的单据、模型服务凭据或业务数据。AI 已加载现有本地 embedding 模型。实际大模型推理、业务诊断验收需另行配置模型服务与测试数据。

## 开始人工验收

希望亲自执行签发、不使用预签发样例或自动签发脚本时，按 [license-issuer 完整签发与时间恢复实操](license-issuer-hands-on.md) 操作。该手册包含手抄码签发、验签、页面导入、独立异常注入及签名恢复。

按 [软件授权页面人工验收清单](../../frontend/docs/acceptance/software-license.md) 操作。本次仅做了健康检查、API 和静态资源检查，页面布局、复制/下载、文件选择及交互仍由人工确认。

所有下列命令在工作区根目录执行：

```sh
cd /Users/sloong/Workspace/github/icp_diag
python3 runtime/license-manual/manual.py status
```

使用浏览器登录管理员，进入“设置 → 软件授权”。核对绑定、限时、机器码、到期时间，测试取得机器码和下载申请。

然后选择 `runtime/license-manual/fixtures/` 内文件：

| 文件 | 用途 / 预期 |
| --- | --- |
| `valid-bound-term.json` | 本验收安装的有效绑定限时许可 |
| `valid-unbound-perpetual.json` | 有效无绑定无限期许可 |
| `wrong-machine.json` | 有效签名但机器绑定不匹配，导入拒绝 |
| `expired.json` | 已过期，导入拒绝 |
| `not-yet-valid.json` | 尚未生效，导入拒绝 |
| `invalid.json` | 无效格式/无签名，拒绝 |
| `empty.json` / `oversized.json` | 本地文件检查 |
| `license-request.json` / `machine-code.txt` | API 取得的原始申请 / 机器码，对照页面下载与复制 |

普通用户在另一浏览器会话登录，确认没有管理员入口、直接访问无权限；授权拒绝不应自动退出登录。

### 显示未授权、到期等当前状态

产品正常导入 API 会拒绝已过期等候选。为检查页面的**当前状态**文案，专用工具可直接切换本隔离安装的共享商业许可文件：

```sh
python3 runtime/license-manual/manual.py license-unlicensed
python3 runtime/license-manual/manual.py license-expired
python3 runtime/license-manual/manual.py license-not-yet-valid
python3 runtime/license-manual/manual.py license-wrong-machine
python3 runtime/license-manual/manual.py license-invalid
python3 runtime/license-manual/manual.py license-valid-unbound-perpetual
# 每次执行后在页面点刷新；以上命令任选一条，不需顺序全部执行。
# 恢复正常基线：
python3 runtime/license-manual/manual.py license-valid-bound-term
```

这些命令只定位固定验收容器及固定安装 UUID，不会重置时间记录；通过容器服务身份写入，保持共享文件权限。切换商业许可会同时被 Metor 和 AI 各自读取并独立判定。

### 人工验证时间恢复

先保持有效许可，然后：

```sh
python3 runtime/license-manual/manual.py prepare-metor-recovery
```

工具会：停止本验收 Metor → 保存本次 clock 快照 → 写入时间记录异常样例 → 启动并等待 Metor 健康 → 通过管理员 API 取得恢复申请 → 使用本安装验收私钥签发恢复文件。

1. 记录终端输出的恢复文件路径和 UTC 应用窗口。**窗口开始约为签发后一分钟**，开始前拒绝属于预期。
2. 刷新页面，当前状态应为时间记录异常。点击“取得恢复申请”，应取得同一仍适用申请；可核对 `fixtures/metor-recovery-request.json`。
3. 窗口开始后，在页面选择终端刚输出的 `metor-recovery-<UUID>.json` 并应用，应确认恢复成功、状态回到有效。
4. 重复应用同一文件，应返回已经应用；新一轮注入必须使用新输出的恢复文件。目录中旧文件不能用于新申请。
5. 运行 `python3 runtime/license-manual/manual.py ai-status`，AI 应保持独立状态。工具没有修改 AI 时间记录或真实宿主时钟。

该工具注入的是 `CLOCK_STATE_INVALID`，用于页面恢复闭环；未修改真实时间来模拟回拨。`202 OUTCOME_UNKNOWN`、磁盘故障、策略破坏等故障注入场景未随本环境自动配置；清单中这些项目不能视为已人工验收。

## 生命周期与资料位置

```sh
python3 runtime/license-manual/manual.py status
python3 runtime/license-manual/manual.py ai-status
python3 runtime/license-manual/manual.py stop
python3 runtime/license-manual/manual.py start
```

不要用默认部署命令启动本环境。它使用 `runtime/license-manual/compose/` 内的配置快照和固定新卷名，必须使用上述专用入口，避免误用历史验收卷。

| 路径 | 内容 |
| --- | --- |
| `runtime/license-manual/config/docker.env` | 私有数据库 / JWT / 镜像 / 端口配置 |
| `runtime/license-manual/install/license/identity/` | 本安装身份与服务密钥 |
| `runtime/license-manual/install/license/shared/active.license.json` | 两服务读取的共享商业许可 |
| `runtime/license-manual/install/license/state/metor/` | Metor 时间及恢复状态 |
| `runtime/license-manual/install/license/state/ai/` | AI 独立时间及恢复状态 |
| `runtime/license-manual/vendor/` | 仅本次验收签发私钥、口令、签发记录 |
| `runtime/license-manual/snapshots/` | 注入前的 Metor 时间记录快照；不能靠手工还原代替签名恢复 |
| `runtime/license-manual/api-verification.json` | 商业许可 API 与静态资源检查结果 |
| `runtime/license-manual/recovery-verification.json` | 恢复成功、重复应用幂等的 API 结果 |

新卷名均以 `icp-license-manual-20261023-` 开头（mysql、metor、documents、chroma）。私有材料均不进入 Git 或客户交付包。验收镜像不用于客户正式发行。

## 本次已完成的检查

- 三个当前服务与独立 MySQL 均健康，前端路由及静态资源 HTTP 可访问。
- 管理员/普通用户鉴权，未授权关键操作返回 `LICENSE_REQUIRED` 且用户保持登录。
- 有效绑定限时、无绑定无限期导入；坏文件、错机、过期、未生效拒绝且原许可不变；旧摘要返回 409。
- Metor 在线签名恢复 `CLOCK_STATE_INVALID → ACTIVE`；重复应用 `ALREADY_APPLIED`。
- AI 固定策略有效，独立验签同一绑定限时许可为 `ACTIVE`。
- 发现并修正 `compose.ai.yaml` 机器标识变量名：`AI_LICENSE_MACHINE_ID_PATH`，与 `app/config.py` 对应。

构建说明：AI 使用项目 Dockerfile 和离线 wheelhouse；前端打包此前通过完整检查的当前 `dist`；Metor 将当前源码构建的 CUSTOMER_REQUIRED JAR 放入本机缓存 Java 运行层，并调整 UID/GID 符合当前部署约定、限制验收 JVM 堆内存。客户正式发行仍按正式发行流程重新构建和验收。

## 2026-10-23 前端体验更新

验收前端已更新为本轮工作区构建：授权操作反馈按设计系统 §5.11 使用共享 Toast；软件授权和平台外观内容最大宽度 1480px 并居中；设置入口为齿轮，子项带图标和分隔线；齿轮及系统信息图标为 16×16px，顶栏工具区间距为 `--space-1`；环境信息收进顶栏系统信息弹窗，并显示前端版本。

完整前端检查通过（230 passed，8 skipped），容器健康及 HTTP 静态资源与当前 dist 一致。新增界面交互仍按[人工验收清单](../../frontend/docs/acceptance/platform-settings-feedback.md)复查。授权资料和数据库未改动。版本/环境展示的公开构建变量见 frontend README，当前镜像由前端提交 `f8b94b9` 对应工作区构建。
