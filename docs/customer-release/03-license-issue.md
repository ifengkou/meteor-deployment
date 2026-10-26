# 阶段三：我方授权签发

执行方：我方签发人员。Issuer 0.4.0 留在我方运行，不部署到客户服务器。使用已经与客户镜像公开配置匹配的正式密钥；本次核查 key ID 为 `vendor-icp-2026`。不要使用 `deployment-20261025` 或旧 `manual-*` 演示身份，也不在发版时临时 keygen。

## 1. 客户取得商业申请

客户完成[首次部署](02-deploy.md)，由平台管理员打开“设置 → 软件授权”（`/platform/settings/license`），刷新并取得机器申请。允许文件传输时下载申请 JSON；不能传文件时完整抄写 IC1 申请码，核对安装、客户和版本后交我方。

商业申请是 SDK 返回的对象；若通过 API 获取，取响应中的 `data`，不能把整个平台 API 信封当申请文件。申请不是商业许可，也不是 RC1J／RC1A 时间恢复码。

交接信息：客户名称／内部编号、产品、发行版本、目标安装、绑定方式、限期或无限期、生效与到期约定、申请文件或完整机器码。默认优先按实际合同选择 HOST_INSTALL + TERM，不自行决定无绑定或无限期。

## 2. 核对正式 Issuer

我方签发机提前安装好 Issuer 0.4.0 及其依赖。配置使用真实绝对路径，保存现有加密私钥、公钥、records 和 outputs。日常运行不要求客户联网。

从本产品 Issuer 的“SDK 接入配置”下载公开配置，与本次发行留存文件／manifest 摘要核对；产品、服务、域、前缀、key ID、公钥均须匹配。仅 key ID 相同不足以证明同一公钥。

原产品已有密钥时不重新生成。若不匹配，停止签发并找回正确配置／密钥；不能靠改客户运行环境信任或重新初始化安装解决。

## 3. 推荐使用本机 Web

在我方签发机执行，路径按实际替换：

```bash
/absolute/license-issuer/.venv/bin/license-issuer-web \
  --config /absolute/vendor/issuer.toml
```

浏览器打开启动输出的 `http://127.0.0.1:18200`（若配置另有端口，以实际为准），保持该进程运行：

1. 核对产品、key ID 和公钥指纹，以原私钥口令解锁。
2. 打开“商业签发”，填写客户名称；选择绑定机器并上传申请 JSON 或粘贴 IC1 码。无绑定按合同选择，且不填机器申请。
3. 选择 30 天、1 年、无限期或约定日期。自定义日期按北京时间填写，页面转换为 UTC；最终记录同时保存原始 UTC。
4. 点击“检查并预览”，核对客户、目标、绑定与期限，再“确认签发”。预览不会签名。
5. 在详情确认“已签发”，下载签名许可文件；记录签发编号、license_id、制品 SHA256、客户、发行配置摘要和期限。

签发超时或显示待核对时，查询／重试原签发，保留原编号和参数；不要新签一份冒充原操作重试。历史重新下载不重新签名，也不延长期限。

## 4. 可选 CLI：当前参数入口

在已经安装的 Issuer 上先运行 `license-issuer sign-license --help`。当前产品／密钥／记录路径统一来自 TOML；不再接收旧 `--product`、`--key-id`、`--private-key`、`--records-dir` 参数。

下面示例的五个变量需先按合同填写并保存在我方受保护的本次签发记录中；`ISSUANCE_UUID` 为本次规范 UUID，同一次重试不重新生成。起止时间格式为 `YYYY-MM-DDTHH:MM:SSZ`，不得照抄过期示例日期：

```bash
license-issuer sign-license --config /absolute/vendor/issuer.toml \
  --customer-id "$CUSTOMER_ID" --customer-name "$CUSTOMER_NAME" \
  --binding HOST_INSTALL --request-file /absolute/vendor/incoming/license-request.json \
  --validity TERM --not-before "$NOT_BEFORE_UTC" --expires-at "$EXPIRES_AT_UTC" \
  --output /absolute/vendor/outputs/customer-license.json \
  --issuance-id "$ISSUANCE_UUID"
```

口令由终端安全提示输入。手抄模式将 `--request-file` 换为 `--request-code "$REQUEST_CODE"`，两者互斥。UNBOUND 省略申请；PERPETUAL 省略 expires-at。输出目录预先存在，输出文件不覆盖其他签发。

HOST_INSTALL 验签时，`BINDING_ID` 取自已经核对的本次申请 `binding_id`：

```bash
license-issuer verify --config /absolute/vendor/issuer.toml \
  --license /absolute/vendor/outputs/customer-license.json --binding-id "$BINDING_ID"
sha256sum /absolute/vendor/outputs/customer-license.json
```

未来生效的文件会显示 NOT_YET_VALID；当前生效的应为 ACTIVE。核对摘要与签发记录一致。签发机传入 binding_id 的验签不能替代客户实际宿主校验。macOS 可用 `shasum -a 256`。

## 5. 交付与留存

只将签名商业许可 JSON 及约定的摘要／生效说明交客户，通过[授权导入](04-license-import.md)应用。两端使用同一商业许可，AI 不另签一份。不要交付 Issuer、TOML、私钥、口令、records 或安装主密钥。

我方保管原配置、密钥与口令、完整 records（含隐藏记录和 artifact）及 outputs；这些不进入通用客户包。续期属于新商业签发，仍绑定客户当前安装；原签发的重复下载／重试不续期。

时间异常另按[恢复手册](../license-recovery.md)取得单服务申请并签发恢复文件。普通到期需续签商业许可，恢复文件不延长商业期限。
