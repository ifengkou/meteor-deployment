# SDK 0.7.1 制作、安装与既有客户升级

当前产品统一使用正式 License SDK **0.7.1**。Java 和 Python 各自本地校验，共享一份商业许可；不运行授权服务器。旧 SDK 0.6.0 镜像只用于已验证的故障回退，不能继续制作第二套接入实现。

## 谁准备哪些资料

| 资料 | 提供者／来源 | 客户需要手工制作吗 |
| --- | --- | --- |
| SDK 和 SHA256SUMS | 制作方从 [v0.7.1 Release](https://github.com/ifengkou/license-sdk/releases/tag/v0.7.1) 获取并校验 | 不需要，已进入产品镜像 |
| license-product.json | 我方产品 Issuer 的 SDK 接入配置导出，包含公开产品、服务、协议参数和公钥 | 不需要，制作方以同一份原始字节构建两端 |
| 完整业务运行依赖、模型 | 制作方准备，模型按部署约定另行交付 | 不在客户启动时联网安装 |
| identity/installation.json、service.key、两份 clock | 客户显式执行 license-init，由镜像内 SDK 生成 | 不需要编辑 JSON 或生成主密钥 |
| active.license.json | 客户取得商业申请交我方，Issuer 签发；管理员在软件授权页面导入 | 只交付签名成品，不交付签发私钥 |
| 恢复挑战、锁和后续 clock | SDK 在对应服务的 state 中按需维护 | 不需要；不能删除 clock 绕过异常 |

Issuer 固定后的产品、服务、域、前缀和信任是客户兼容契约。不要为简化配置更换既有 key ID、遗漏旧公钥或修改域／前缀；新旧发行公开信任必须逐项核对。成功构建不证明历史客户信任已经匹配。

## 制作方：准备和构建

在三个业务工程及 deployment 同级的源码工作区操作：

1. 按 [Java 构建输入](../../metor-service/license-build/README.md) 校验完整 Maven 包并解压到构建仓库；按 [Python 构建输入](../../ai-runtime-service/license-build/README.md) 准备正式 wheel 及锁定依赖。
2. 将 Issuer 导出的同一文件分别复制为两工程的 license-build/license-product.json。不要另写 DER／公钥配置。核对旧发行的全部信任和协议参数后再制作客户镜像。

```bash
cmp ai-runtime-service/license-build/license-product.json \
    metor-service/license-build/license-product.json
python3 deployment/scripts/license_artifacts.py --workspace .

# 联网制作阶段准备完整 AMD64 Python 3.12 依赖闭包。
TARGET_PLATFORM=linux/amd64 deployment/scripts/prepare-wheelhouse.sh

# 在配置中选择最终架构和本次唯一镜像 tag 后构建。
python3 deployment/scripts/local-stack.py --env-file /absolute/private/docker.env build
```

两个构建入口均显式固定 CUSTOMER_REQUIRED；LICENSE_PRODUCT_CONFIG 可在制作进程环境中指定两个工程内相同的 license-build/ 相对文件路径。单独制作 DEVELOPMENT 镜像见产品 README，开发镜像不能导出为客户交付包。

离线构建需要完整业务依赖、基础镜像和相同 builder 的缓存。AI 可执行 build --service ai --offline；AMD64 归档制作见 [AMD64 文档](amd64.md)。SDK 平台包只解决 SDK 的依赖，不替代 torch／Chroma 等产品依赖闭包。Java Maven 包也不包含 Spring 等产品依赖。

选定已完成自动／目标平台验收的新 AI 镜像，将其不可变 ID 写入制作方私有 docker.env 的 LICENSE_TOOLS_IMAGE。该值必须是完整 sha256 ID，不接受浮动 tag：

```bash
docker image inspect ai-runtime-service:<release> --format '{{.Id}}'
python3 deployment/scripts/local-stack.py --env-file /absolute/private/docker.env \
  export /absolute/new-customer-bundle
sh deployment/scripts/verify-bundle.sh /absolute/new-customer-bundle
```

export 要求四个镜像同属 Linux amd64 或 arm64，核验 AI 实际安装的 SDK 每个文件与正式 wheel 一致、BootJar 只有正式 core JAR、两端固定客户模式、API 清单摘要正确，以及公开配置原字节相同。manifest.json 的 licensing 记录 SDK 版本、正式制品摘要和公开配置 SHA256；images 记录镜像 ID／平台；licenseToolsImage 固定引用本包 AI 镜像。源码 HEAD 及未提交变更列表另记在 repos。正式交付前仍需发布提交并记录目标 Linux 验收。

包内没有源码、Issuer、签发私钥、口令、客户身份、商业许可、业务数据或模型权重。不要手抄旧版复制清单组装新包，以免遗漏 SDK 工具或 manifest。客户包校验和只能检测传输损坏；交付介质和清单来源仍须受控。

## 客户：首次安装

前提：匹配架构的 Docker／Compose、Python 3.9+、模型及已校验交付包。以下从解包根目录执行：

```bash
# 先验证并加载全部镜像；此时无需业务服务运行。
sh deployment/scripts/import-images.sh .

# 仅首次生成业务私有配置；替换模型绝对路径。
python3 deployment/scripts/local-stack.py init --model-path /absolute/models/embedding
```

核对 runtime/config/docker.env 的镜像 tag、METOR_PLATFORM、LICENSE_ROOT 和真实模型路径。新包自动使用 manifest 中的固定工具镜像；源码部署需要显式填写 LICENSE_TOOLS_IMAGE。machine-id 只挂载实际宿主文件，不生成替代标识。

`init` 仍生成历史 `p6-local` 应用 tag，不会从 manifest 自动选择业务镜像。必须先按[首次部署](customer-release/02-deploy.md)将三个应用镜像与 MySQL 引用、平台替换成 manifest 中的实际值，并配置宿主目录与权限，再初始化授权和启动。

```bash
# 新环境尚未启动业务。若有旧安装任务或源码服务，先全部停止。
sudo python3 deployment/scripts/local-stack.py license-init
# 同命令再次执行应为 ALREADY_INITIALIZED，UUID/key/clock 原字节不变。
sudo python3 deployment/scripts/local-stack.py license-init

python3 deployment/scripts/local-stack.py compose up -d --wait mysql
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

license-init 使用固定 AI 镜像内 SDK，一次性容器无网络、不启动数据库／模型／AI 应用。宿主仅检查路径、数值账号及分配权限，不安装 SDK。工具可检测本项目 Compose 服务和默认本机业务端口，不能发现所有外部写入进程；停止旧初始化任务和其他写入者是操作前提。

首次返回 INITIALIZED；重复返回 ALREADY_INITIALIZED。权限或同步失败会报告 LICENSE_STORAGE_OUTCOME_UNKNOWN，SDK 完成资料保留，停止写入并重试同一命令。完成身份缺 key／clock、损坏状态或旧 .identity-stage-* 不会补造；保留现场按备份／恢复规程处理。

没有商业许可时健康与原鉴权下的维护入口仍可用，受控业务被拒绝。管理员打开软件授权页面，下载申请或抄 IC1 码交我方。导入签名文件后刷新状态，再测试一个受控操作。APPLIED／ALREADY_APPLIED 表示导入已确认，OUTCOME_UNKNOWN 保留文件并核对后重试；同文件已过期仍显示 EXPIRED。详细 UI 操作见 [人工清单](../../frontend/docs/acceptance/software-license.md)，Issuer 见 [签发说明](../../license-issuer/README_cn.md)。

## 既有 0.6.0 安装：停机升级

前提：先在独立目录／项目演练，确认同宿主、同授权根、相同公开协议和全部旧信任，准备获准旧镜像及完整备份。不要对真实安装直接运行隔离验收驱动。

1. 导入新镜像并更新 deployment 工具和公开 manifest。业务镜像尚可保持旧 tag；工具固定使用新版 AI 镜像。源码部署先更新 LICENSE_TOOLS_IMAGE。停止所有旧初始化任务及源码业务写入。
2. 暂停业务入口、等待任务结束。用 [备份手册](backup-restore.md) 执行一致性备份并保持写入停止：

```bash
sudo python3 deployment/scripts/local-stack.py backup --keep-stopped /absolute/protected/before-sdk-upgrade
```

3. 保留原 LICENSE_ROOT；核对 identity、service.key、商业许可、两份 clock、已有 recovery-challenge 的 SHA256 和 owner／mode。不得重新 init、删除 clock、覆盖旧快照或重新签发正常旧许可来让升级通过。新版 backup 在停止写入后以 SDK 只读核验安装；商业缺失／到期不会被误判为安装资料不完整。
4. 只更换私有 env 中两端新镜像 tag，先确认 compose config --quiet，再启动服务。启动前授权资料应与快照逐字节相同；启动后 SDK 正常 checkpoint 可增加 clock，高水位不能因升级倒退。identity／key／商业许可不因升级变化。
5. 核对两端商业状态、管理员申请／导入／同文件重复、普通账号拒绝，以及受控操作。停止 AI 时，Metor 的本地商业导入仍应可完成；重启 AI 后应读取新共享文件。时间异常按 [单服务恢复](license-recovery.md) 处理，不手动修 JSON。

## 故障回退与灾难恢复

停止新两端写入后，只回退已验收的业务镜像 tag，保留**当前最新** identity／key／商业许可／clock／挑战原文件及权限。不得覆盖升级前旧 clock 来冒充回退，不重新 init。固定新版 licenseToolsImage 和新版 deployment 工具继续用于 check／backup，不随 AI_RUNTIME_IMAGE 回退旧 SDK。

备份恢复另按 [同宿主、空目标恢复](backup-restore.md) 操作；不是常规镜像回退。恢复工具在 staging 保留原字节和权限，用只读 SDK check 确认后才发布。过旧快照可能需要单服务签名时间恢复，不能以删除状态规避。

## 自动与人工验收

隔离驱动及其参数见 scripts/verify-license-sdk-upgrade.py --help；使用明确的旧／新镜像、临时测试信任和全新 Linux 卷，不能指向业务授权根。驱动输出不包含私钥、主密钥、完整客户资料或维护凭据。arm64 证据只作补充，不替代客户 AMD64 环境。

研发工作区的复现命令如下。需要已安装 Issuer 的 Python、JDK 21 编译器、同一目标架构的四个真实镜像和可写临时目录；所有路径自行替换。历史初始化器仅作为摘要固定的测试输入导出，不进入客户包或成为生产回退入口：

```bash
git -C deployment show 240b21a06c0a23dcb9f9356c14215be8177c407b:scripts/license_init.py \
  > /absolute/test/baseline-initializer.py
python3 deployment/scripts/verify-license-sdk-upgrade.py \
  --baseline-ai-image "$BASELINE_AI_IMAGE" \
  --baseline-metor-image "$BASELINE_METOR_IMAGE" \
  --ai-image "$NEW_AI_IMAGE" --metor-image "$NEW_METOR_IMAGE" \
  --baseline-initializer /absolute/test/baseline-initializer.py \
  --issuer-python /absolute/license-issuer/.venv/bin/python \
  --javac /absolute/jdk21/bin/javac --platform linux/amd64 \
  --report /absolute/test/upgrade-report.json
```

预期 result=PASS；RUNNING／FAIL 及部分 checks 不能作为整体验收通过。报告记录原镜像、SDK、公开配置与执行脚本／夹具摘要；运行使用临时测试信任覆盖，不能证明真实客户旧公钥与新公开配置相同。

本轮按用户要求不执行人工验收。日后验收按以下顺序，每项记录操作者、日期、平台、镜像 ID、配置摘要及结果：

1. **构建／信任**：准备旧发行公开信任、新公开配置及两端客户镜像。逐项核对 key ID、公钥、产品、服务、域与前缀；对照 manifest 摘要，确认不丢旧信任。参考本页“谁准备哪些资料”。
2. **首次安装／资料恢复**：使用客户目标 Linux 的全新隔离根和端口，按“客户：首次安装”执行两次 init，再按备份手册在同宿主空目标恢复。预期 UUID/key/clock 原字节与数值权限保持；不需手工制作文件。
3. **页面／权限**：准备管理员、普通账号和签名许可，按 UI 清单完成状态、复制／下载、导入、同文件重复及未知结果核对。预期服务端状态为准，普通用户无导入权，受控拒绝后没有业务副作用，健康／登录／维护仍按原权限工作。
4. **升级／回退**：以真实旧发行隔离安装按本页停机升级，再保持最新状态回退。预期正常旧许可不重签、身份不变、高水位不降低；核对实际 UID/GID 和只读挂载。
5. **两端恢复／生命周期**：在隔离异常资料上按恢复手册分别申请、签发、应用、重复并重启；预期只修改目标服务时间状态，另一端及商业许可不变。关闭应用后无遗留授权任务。
6. **交付易用性**：由未参与实现的操作者仅按新包手册完成以上流程。预期客户无联网安装、无宿主 SDK、无手写身份/clock；维护者确认只保留 SDK 通用协议实现，产品薄适配仅承担权限、鉴权、策略和响应职责。
