# 使用 license-issuer 完成商业签发与时间恢复

本手册以当前本机 Docker 验收安装为例，直接执行 `license-issuer` CLI。不会调用 `manual.py` 的签发封装，也不复用预签发的 fixtures。你将亲自取得申请、签发、验签、导入，再取得时间恢复申请、签发恢复文件和应用。

客户操作和我方签发在本次演练中位于同一台电脑、不同目录；实际交付时分别位于客户内网和我方签发机。双方只交换申请信息和签名结果文件，私钥、口令及签发记录留在我方。

## 1. 两个状态与联网要求

| 情况 | 当前服务状态 | 含义 |
| --- | --- | --- |
| `license-wrong-machine` | `INVALID` | 签名可有效，但绑定与本安装不符 |
| `license-invalid` | `INVALID` | 文件格式、协议、信任或签名等校验失败；当前样例为无效格式/无签名 |
| 普通导入错误/错机候选 | HTTP 400 / `LICENSE_IMPORT_INVALID` | 拒绝候选，保留当前许可；不会把当前有效许可改为 INVALID |

前两项同为 INVALID 是当前 SDK 的统一状态设计。底层验签有 `BINDING_MISMATCH`、`INVALID_SIGNATURE` 等具体原因，运行状态将这类失败合并为“授权无效”。这不表示两份测试文件具有相同的问题，也不需要为了显示不同状态而修改授权逻辑。

“取得恢复申请”调用 `POST /platform/admin/license/recovery/request`，在当前 Metor 的 SDK Runtime 内检查异常、生成并持久保存本地申请。它不访问互联网、不调用我方签发服务、不要求 AI 在线。浏览器需能访问本机/内网 Metor，服务需能读取安装身份并写入自己的 state 目录。

```text
客户浏览器 ──本机/内网 HTTP──> Metor ──本地文件──> 恢复申请
                                   无公网调用
申请文件或手抄信息 ──人工交接──> 我方离线 license-issuer
签名恢复文件       <──允许的文件入网── 我方签发机
```

商业许可申请、CLI 签发、验签和恢复应用也不依赖公网。前提是我方 CLI 及依赖已安装，客户使用已打包的服务镜像；本手册调用现有 `.venv/bin/license-issuer`，不会运行 uv/pip 安装。客户禁止文件导出时，使用下面的手抄模式即可。正常时间状态下取得恢复申请会返回“无需恢复”，属于预期。

## 2. 准备当前演练目录和已有受信任密钥

在终端执行一次，后续步骤沿用同一终端：

```sh
cd /Users/sloong/Workspace/github/icp_diag
ROOT=/Users/sloong/Workspace/github/icp_diag
ISSUER="$ROOT/license-issuer/.venv/bin/license-issuer"
VENDOR="$ROOT/runtime/license-manual/vendor"
SESSION="$ROOT/runtime/license-manual/hands-on/$(date -u +%Y%m%dT%H%M%SZ)"
export SESSION
umask 077
mkdir -p "$SESSION"
"$ISSUER" --help
```

本次使用现有 key ID **`manual-20261023`**：

| 材料 | 路径 |
| --- | --- |
| 加密私钥 | `$VENDOR/private.pem` |
| 公钥 | `$VENDOR/public.pem` |
| 私钥口令文件（0600） | `$VENDOR/passphrase.txt` |
| 原有签发记录目录 | `$VENDOR/records` |
| 本次输入、参数和输出 | `$SESSION/` |

当前验收镜像已固定信任该公钥。**不要为这次演练重新 keygen 或换 key ID**，新密钥签出的文件不会被现有镜像信任。首次建立新产品信任时才使用 issuer 的 keygen，再把公钥作为构建输入制作镜像；操作见 [issuer 中文说明](../../license-issuer/README_cn.md)。

现有管理员与普通账号见 `runtime/license-manual/accounts.json`。所有签发材料仅供本机验收，不作为客户正式发行密钥。

## 3. 客户取得机器申请码

1. 打开 <http://127.0.0.1:18181/platform/settings/license>，使用 `license-admin` 登录真实模式。
2. 点击“取得机器码”。抄写/复制页面显示的完整 `IC1-...`，保留全部字符和连字符。
3. 在模拟我方签发的终端，将下面引号内内容替换为完整机器码后执行：

```sh
REQUEST_CODE='在此粘贴页面的完整IC1机器码'
"$ISSUER" inspect-request-code --product icp-diag \
  --request-code "$REQUEST_CODE" > "$SESSION/machine-code-inspected.json"
cat "$SESSION/machine-code-inspected.json"
```

预期返回 product_id、binding_scheme、binding_id、normalized_code。这一步只检查输入，不签发、不修改客户端。

允许导出申请文件时，也可在页面下载 `license-request.json` 并交给我方。本演练将其另存为 `$SESSION/license-request.json`。禁止导出时无需此文件，后续主流程使用手抄码。

## 4. 我方签发一份绑定、限时商业许可

### 4.1 保存本次参数

下列代码从第 3 步已保存的 machine-code-inspected.json 读取机器码，不依赖 REQUEST_CODE 是否 export。SESSION 通过命令参数显式传入；成功后才加载参数文件。已有参数原样复用，不生成新 UUID。

```sh
if python3 - "$SESSION" <<'PY'
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
import json, shlex, sys

if len(sys.argv) != 2 or not sys.argv[1]:
    raise SystemExit('请先设置 SESSION 为第 2 步的演练目录。')
session = Path(sys.argv[1])
if not session.is_dir():
    raise SystemExit(f'演练目录不存在：{session}')
output = session / 'license-params.env'
if output.exists():
    print(f'沿用已有参数：{output}')
    raise SystemExit(0)
source = session / 'machine-code-inspected.json'
try:
    inspected = json.loads(source.read_text())
    code = inspected['normalized_code']
    if inspected['product_id'] != 'icp-diag' or not code.startswith('IC1-'):
        raise ValueError('不是有效的机器码检查结果')
except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
    raise SystemExit(f'请先完成第 3 步 inspect-request-code，确认 {source} 有 normalized_code：{error}')
now = datetime.now(timezone.utc).replace(microsecond=0)
fmt = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
values = {
    'REQUEST_CODE': code,
    'LICENSE_NOT_BEFORE': fmt(now - timedelta(minutes=1)),
    'LICENSE_EXPIRES_AT': fmt(now + timedelta(days=30)),
    'LICENSE_ISSUANCE_ID': str(uuid4()),
}
with output.open('x') as f:
    f.write(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
output.chmod(0o600)
print(output)
PY
then
  . "$SESSION/license-params.env"
fi
```

这里将 not_before 设为当前 UTC 前一分钟，是本次签发明确选择的生效时间；产品本身没有提前/延后生效宽限。

### 4.2 直接调用 issuer

```sh
"$ISSUER" sign-license --product icp-diag \
  --key-id manual-20261023 \
  --private-key "$VENDOR/private.pem" \
  --passphrase-file "$VENDOR/passphrase.txt" \
  --customer-id hands-on-customer --customer-name '手工签发演练客户' \
  --binding HOST_INSTALL --request-code "$REQUEST_CODE" \
  --validity TERM \
  --not-before "$LICENSE_NOT_BEFORE" --expires-at "$LICENSE_EXPIRES_AT" \
  --records-dir "$VENDOR/records" \
  --output "$SESSION/commercial.license.json" \
  --issuance-id "$LICENSE_ISSUANCE_ID"
```

预期退出码 0，返回 `state: ISSUED`、license_id、issuance_id 和 artifact_digest。输出文件是 `$SESSION/commercial.license.json`。

文件模式：在同一条命令中，把 `--request-code "$REQUEST_CODE"` 替换为 `--request-file "$SESSION/license-request.json"`，二者只能选一个。

后续需要重试时，重新 `. "$SESSION/license-params.env"`，沿用同一编号、参数、输出和原记录目录；不要每次生成新 UUID。新的一次商业签发则新建 SESSION 和参数。

### 4.3 我方验签

绑定摘要来自刚才检查过的客户机器码：

```sh
BINDING_ID=$(python3 - "$SESSION/machine-code-inspected.json" <<'PY'
from pathlib import Path
import json, sys
print(json.loads(Path(sys.argv[1]).read_text())['binding_id'])
PY
)
"$ISSUER" verify --product icp-diag \
  --key-id manual-20261023 --public-key "$VENDOR/public.pem" \
  --license "$SESSION/commercial.license.json" --binding-id "$BINDING_ID"
shasum -a 256 "$SESSION/commercial.license.json"
```

预期 `status: ACTIVE`，文件 SHA256 与 sign-license 输出的 artifact_digest 一致。此处是我方核对输入和文件；产品运行时仍按实际宿主、安装身份重新计算绑定，不能以我方传入的 binding_id 代替。

## 5. 客户导入商业许可

1. 将 **commercial.license.json** 送入客户内网；不要交付私钥、口令或 records。
2. 在软件授权页面刷新当前摘要，选择本次 `$SESSION/commercial.license.json`，点击导入。
3. 确认 `APPLIED` 后刷新：有效、TERM、HOST_INSTALL、客户名“手工签发演练客户”，时间与本次参数一致。
4. 本次页面导入会将商业文件发布到共享目录，Metor 和 AI 各自独立校验这一份文件。页面不替 AI 执行时间恢复。

这就是产品的“导入”：通过管理 API 验证候选、检查当前摘要、原子发布。此演练不需要手工 copy 商业文件到映射目录。

可选组合：UNBOUND 时省略机器申请输入；PERPETUAL 时省略 expires_at。每个新签发使用新参数和编号。首次演练建议先走上述 HOST_INSTALL + TERM 完整流程。

## 6. 为演练准备一次真实可恢复的异常

已有 `CLOCK_ROLLBACK` 或 `CLOCK_STATE_INVALID` 时跳过本节。若当前为 INVALID/EXPIRED，先处理商业许可；那不是时间异常，不能靠恢复文件修复。

实际客户：先核实并校正宿主 UTC，然后直接取得申请。**不执行下面的注入命令**。

本机隔离验收：下面只损坏验收 Metor 的时间记录，完整保留身份、服务密钥、商业许可和 AI 状态。它不会签发，也不修改宿主时钟。停止服务仅用于布置异常样例，正式申请和恢复应用均在服务运行中完成。

先备份并核对目标：

```sh
METOR_CONTAINER=icp-diag-local-restore-check-metor-1
CLOCK_DIR="$ROOT/runtime/license-manual/install/license/state/metor"
docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$METOR_CONTAINER"
# 输出必须是 icp-diag-local-restore-check，否则不要继续。
docker cp "$METOR_CONTAINER:/run/icp-license/state/metor/clock.json" \
  "$SESSION/metor-clock-before.json"
chmod 600 "$SESSION/metor-clock-before.json"
docker stop "$METOR_CONTAINER"
```

确认已停止，向该验收 state 目录写入异常样例：

```sh
docker run --rm -i --network none --user 21001:21001 \
  --mount "type=bind,src=$CLOCK_DIR,dst=/state" \
  python:3.12.14-slim-bookworm python - <<'PY'
from pathlib import Path
Path('/state/clock.json').write_bytes(b'{"manual_fixture":"invalid-clock-state"}\n')
PY
docker start "$METOR_CONTAINER"
curl --fail --retry 20 --retry-delay 2 --retry-connrefused \
  http://127.0.0.1:18081/actuator/health/readiness
```

该 Python 镜像已缓存；此命令不安装依赖，容器内部禁网。逐条确认成功再继续。不要对旧业务栈或其他 state 目录执行。

回页面点击刷新，应为“时间记录异常 / CLOCK_STATE_INVALID”。后续只通过签名恢复处理，不用备份 clock 覆盖现状，也不删除身份文件或重新初始化安装。

## 7. 客户取得恢复申请

1. 确认宿主 UTC 正确。本演练未调过实际时钟，无需改时间。
2. 页面点击“取得恢复申请”。这一步仅通过本机/内网 HTTP 到 Metor，SDK 本地持久保存申请。
3. 核对 product_id=`icp-diag`、service=`metor`、异常原因，以及安装 ID 和 `RC1J-...` 恢复码。
4. 在我方终端填写从页面抄写的两项值：

```sh
INSTALLATION_ID='替换为本次恢复申请中的安装UUID'
RECOVERY_CODE='替换为本次完整RC1J恢复码'
```

允许文件出网时，下载申请 JSON，交我方保存为 `$SESSION/metor-recovery-request.json`。申请顶层 kind 应为 `clock-recovery-request`；通过 curl 保存的 API 信封需先提取 data，不能直接交 sign-recovery。

已有申请仍适用时，再次取得应返回同一申请。若返回 202/OUTCOME_UNKNOWN，重复取得确认后再签发。IC1 机器码不能代替 RC1J 恢复码。

## 8. 我方直接签发时间恢复文件

### 8.1 约定并保存窗口

恢复文件首次应用必须满足 `window_start <= 客户实际UTC < window_end`。签发时要求 `issued_at <= window_start < window_end <= issued_at + 7天`。窗口约束的是**客户应用恢复的时间**，不改变商业期限。

注意：商业许可的 not_before 可以早于签发时间；恢复文件的 window_start 不可以。例如当前已过北京时间 10:00，就不能给新恢复文件填写“今天 10:00 开始”；应选择尚未到达的开始时间。旧版 issuer 此时可能误报 invalid commercial license fields，实际原因是恢复窗口不符合上述规则。

下面安排当前 UTC 一分钟后开始、一天后结束。现在生成参数后立即签发，等到窗口开始再应用；为真实文件入网可改为更晚的开始时间。

```sh
if python3 - "$SESSION" "$INSTALLATION_ID" "$RECOVERY_CODE" <<'PY'
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import UUID, uuid4
import shlex, sys

if len(sys.argv) != 4 or not sys.argv[1]:
    raise SystemExit('请先设置 SESSION 为本次演练目录。')
session = Path(sys.argv[1])
if not session.is_dir():
    raise SystemExit(f'演练目录不存在：{session}')
output = session / 'recovery-params.env'
if output.exists():
    print(f'沿用已有参数：{output}')
    raise SystemExit(0)
installation_id, recovery_code = sys.argv[2:]
try:
    parsed = UUID(installation_id)
    if str(parsed) != installation_id or parsed.version != 4:
        raise ValueError('需要规范 UUIDv4')
except ValueError:
    raise SystemExit('请先在第 7 步设置 INSTALLATION_ID 为恢复申请中的安装 UUID。')
if not recovery_code.startswith('RC1J-'):
    raise SystemExit('请先在第 7 步设置 RECOVERY_CODE 为 Metor 的完整 RC1J 恢复码。')
now = datetime.now(timezone.utc).replace(microsecond=0)
fmt = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
values = {
    'INSTALLATION_ID': installation_id,
    'RECOVERY_CODE': recovery_code,
    'RECOVERY_START_UTC': fmt(now + timedelta(minutes=1)),
    'RECOVERY_END_UTC': fmt(now + timedelta(days=1)),
    'RECOVERY_ISSUANCE_ID': str(uuid4()),
}
with output.open('x') as f:
    f.write(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
output.chmod(0o600)
print('应用窗口：', values['RECOVERY_START_UTC'], '至', values['RECOVERY_END_UTC'])
PY
then
  . "$SESSION/recovery-params.env"
fi
```

SESSION、INSTALLATION_ID、RECOVERY_CODE 均通过命令参数传入，不需要 export。缺少输入时只显示补充步骤，不生成文件、不继续加载。恢复签发编号与商业签发编号不同；安装 UUID 又是另一种身份。不要混用三者。

### 8.2 手抄模式签发（无需导出申请文件）

```sh
"$ISSUER" sign-recovery --product icp-diag \
  --key-id manual-20261023 \
  --private-key "$VENDOR/private.pem" \
  --passphrase-file "$VENDOR/passphrase.txt" \
  --installation-id "$INSTALLATION_ID" --service metor \
  --recovery-code "$RECOVERY_CODE" \
  --window-start "$RECOVERY_START_UTC" --window-end "$RECOVERY_END_UTC" \
  --records-dir "$VENDOR/records" \
  --output "$SESSION/metor.recovery-$RECOVERY_ISSUANCE_ID.json" \
  --issuance-id "$RECOVERY_ISSUANCE_ID"
shasum -a 256 "$SESSION/metor.recovery-$RECOVERY_ISSUANCE_ID.json"
```

预期 `ISSUED`，recovery_id 等于本次 RECOVERY_ISSUANCE_ID，摘要一致。

输出名包含签发编号，避免新签发复用旧文件名。已有不同内容的文件不会被覆盖。若旧命令已因输出文件被占用而返回 OUTPUT_FAILED，保留原 UUID、窗口、目标和 records，仅将 --output 改为一个未占用路径重试；输出路径不参与签发参数指纹，不会重新生成签名或改变 issued_at。此类重试即使已过窗口开始，仍复用原签发时刻；不要因此更改窗口或换编号。

文件模式：在同一命令中，把 installation-id、service、recovery-code 这三项输入替换为 `--request-file "$SESSION/metor-recovery-request.json"`。文件自带目标安装和服务，不额外手填。

sign-recovery 完全在我方本地运行，不连接客户，也不需要客户服务在线。`verify` 子命令只用于商业许可；恢复文件最终由目标服务 SDK 严格校验和应用。

## 9. 客户应用恢复并确认

1. 只将 `$SESSION/metor.recovery-$RECOVERY_ISSUANCE_ID.json` 送入客户内网。
2. 等到 RECOVERY_START_UTC；在页面选择此文件并应用时间恢复。
3. 预期 `APPLIED`，页面确认恢复成功，商业许可仍有效。应用无需重启；SDK 在同一 Runtime 内原子写入并刷新内存。
4. 再应用同一文件，预期 `ALREADY_APPLIED`，不再次重置时间高水位。
5. 核对商业许可文件摘要与恢复前一致。恢复改变 Metor 的时间状态及恢复申请，不改商业许可文件、期限、机器绑定或 AI 时间状态。

若恢复成功但商业状态是 EXPIRED，仍需另行商业续期。若有多种失败同时存在，先解决对应问题；恢复签名不能把错机许可变成有效许可。

## 10. 常见结果与重试

| 结果 | 操作 |
| --- | --- |
| 无需恢复 / LICENSE_RECOVERY_NOT_REQUIRED | 当前没有可恢复的时间异常；不要为正常安装签恢复文件 |
| LICENSE_RECOVERY_WINDOW_INVALID | 核对客户 UTC、窗口开始/结束；未到开始则等待，已过结束则新签发 |
| 目标改变/不匹配 | 取得当前恢复申请，新签发用新编号和输出路径，不编辑旧恢复文件 |
| OUTPUT_FAILED | 若输出路径已有其他签发的文件，保留原 UUID 与签名参数，改用未占用输出路径重试；保留旧文件 |
| ISSUANCE_CONFLICT | 同编号参数/用途不一致；找回原参数，不以覆盖文件方式处理 |
| HTTP 202 / OUTCOME_UNKNOWN | 结果未确认，保留同一文件并重试核对；不能当成功 |
| INVALID 或 LICENSE_IMPORT_INVALID | 核对产品信任、公钥版本、文件、签名和机器绑定；时间恢复不能修复这些问题 |

同一次签发重试沿用参数文件、UUID、records 和输出；不重新规划窗口。新的恢复目标/窗口则使用新的签发 UUID、参数文件名和输出文件名。参数文件使用 `open('x')` 创建，已有文件直接复用；这是为了避免误改已签发参数。

若中途换终端，重新设置 ROOT、ISSUER、VENDOR、原 SESSION，并 `. "$SESSION/license-params.env"` 或 `. "$SESSION/recovery-params.env"` 恢复本次参数；不要再新建会话目录冒充原重试。

## 11. AI 服务的相同流程

商业许可仍使用同一份，不为 AI 额外签一份。只有 AI 自己发生时间异常时，才从 AI 取得申请并单独恢复。

在已有 AI 时间异常时，取得申请可直接使用镜像内自带的维护客户端；它使用本安装 ControlProof 调用自己的本地 API，不经过 Metor，不自动签发：

```sh
docker exec icp-diag-local-restore-check-ai-runtime-1 \
  python -m app.operations.license_recovery request \
  > "$SESSION/ai-recovery-request.json"
```

确认退出码 0、申请 kind 正确后，为 AI 单独生成并保存窗口和编号：

```sh
if python3 - "$SESSION" <<'PYAI'
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
import shlex, sys

if len(sys.argv) != 2 or not sys.argv[1]:
    raise SystemExit('请先设置 SESSION 为本次演练目录。')
session = Path(sys.argv[1])
if not session.is_dir():
    raise SystemExit(f'演练目录不存在：{session}')
output = session / 'ai-recovery-params.env'
if output.exists():
    print(f'沿用已有参数：{output}')
    raise SystemExit(0)
now = datetime.now(timezone.utc).replace(microsecond=0)
fmt = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
values = {
    'AI_RECOVERY_START_UTC': fmt(now + timedelta(minutes=5)),
    'AI_RECOVERY_END_UTC': fmt(now + timedelta(days=1)),
    'AI_RECOVERY_ISSUANCE_ID': str(uuid4()),
}
with output.open('x') as f:
    f.write(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
output.chmod(0o600)
print('AI 应用窗口：', values['AI_RECOVERY_START_UTC'], '至', values['AI_RECOVERY_END_UTC'])
PYAI
then
  . "$SESSION/ai-recovery-params.env"
fi
```

直接签发：

```sh
"$ISSUER" sign-recovery --product icp-diag \
  --key-id manual-20261023 \
  --private-key "$VENDOR/private.pem" \
  --passphrase-file "$VENDOR/passphrase.txt" \
  --request-file "$SESSION/ai-recovery-request.json" \
  --window-start "$AI_RECOVERY_START_UTC" --window-end "$AI_RECOVERY_END_UTC" \
  --records-dir "$VENDOR/records" --output "$SESSION/ai.recovery-$AI_RECOVERY_ISSUANCE_ID.json" \
  --issuance-id "$AI_RECOVERY_ISSUANCE_ID"
```

文件入网后，在窗口内应用：

```sh
docker exec -i icp-diag-local-restore-check-ai-runtime-1 \
  python -m app.operations.license_recovery apply --file - \
  < "$SESSION/ai.recovery-$AI_RECOVERY_ISSUANCE_ID.json"
```

禁止申请文件出网时，改传安装 UUID、service=`ai` 和 RC1A 恢复码，签发命令改用三项手抄输入。不要给 AI 应用 Metor 的 RC1J 恢复文件。

## 参考

- [本机 Docker 访问、账号和启停](license-manual-docker.md)
- [issuer 通用中文使用说明](../../license-issuer/README_cn.md)
- [issuer 时间恢复签发参数与重试](../../license-issuer/docs/recovery-cn.md)
- [客户侧时间恢复操作](license-recovery.md)
- [软件授权页面人工验收清单](../../frontend/docs/acceptance/software-license.md)
