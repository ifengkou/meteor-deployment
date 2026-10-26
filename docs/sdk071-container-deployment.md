# SDK 0.7.1 独立容器部署记录（2026-10-25）

本次按用户要求实际部署新 ICP Diag 环境，保留原有两个 ICP 容器项目及数据。平台是本机 Docker Desktop 的 **Linux arm64**，不是客户 Linux AMD64 验收。未执行人工 UI 验收。

## 访问和管理

| 项目 | 地址／位置 |
| --- | --- |
| 前端 | http://127.0.0.1:18182/ |
| 软件授权页 | http://127.0.0.1:18182/platform/settings/license |
| Java 后端 | 仅内部网络 metor:8080；前端统一代理，不开放宿主端口 |
| AI 服务 | 仅内部网络 ai-runtime:8090；前端经 Java 鉴权代理，不开放宿主端口 |
| 管理员 | sdk071-admin；随机密码见工作区 runtime/sdk071-container-deploy/accounts.json（0600） |
| Compose 项目 | icp-diag-sdk071-20261025 |
| 私有配置／操作入口 | runtime/sdk071-container-deploy/config/docker.env、manage.py |
| 签发配置 | runtime/sdk071-container-deploy/vendor/issuer.toml |

从工作区根目录执行：

```bash
python3 runtime/sdk071-container-deploy/manage.py status
python3 runtime/sdk071-container-deploy/manage.py logs ai-runtime
python3 runtime/sdk071-container-deploy/manage.py logs metor
python3 runtime/sdk071-container-deploy/manage.py check-license
python3 runtime/sdk071-container-deploy/manage.py stop
python3 runtime/sdk071-container-deploy/manage.py start
```

manage.py 只操作这个固定项目和其配置快照，stop 保留数据卷。它是本次复现辅助入口，不替代 [标准 Linux 安装入口](license-sdk-upgrade.md)。不要用默认 local-stack 项目命令操作这套环境。

## 实际部署内容

四个常驻服务为 mysql、ai-runtime、metor、frontend；ai-migrate 执行数据库迁移后退出 0，属于正常结果。MySQL 不映射宿主端口。应用文件／数据库／Chroma 使用全新项目卷，不复用旧库或旧授权资料。

| 制品 | 本次选择 |
| --- | --- |
| AI | ai-runtime-service:sdk071-deploy-20261025 |
| Java | metor-service:sdk071-deploy-20261025 |
| 前端 | metor-platform-frontend:license-v071-migration-20261025 |
| SDK | 正式 0.7.1，Java JAR／Python wheel 摘要仍为此前已验收的发行摘要 |
| 公开配置 | 同一份 Issuer ProductConfig 原始字节分别进入两个客户镜像 |
| 签发身份 | 本次新生成 deployment-20261025，不读取原有 vendor 私钥 |
| 许可 | 独立测试签发的 UNBOUND／TERM，截止 2027-10-25T07:12:22Z |
| 授权卷 | icp-sdk071-20261025-license，独立 Linux 原生卷 |
| Embedding | 已存在的完整 BGE Small 中文 v1.5 模型，只读挂载；本次未下载模型 |

本套镜像是实际 Dockerfile 生成的 CUSTOMER_REQUIRED 构建，不靠启动变量关闭授权或临时覆盖信任资源。测试签发身份只属于这套独立环境，不能用其许可替换旧环境许可。加密私钥和口令只位于本次私有 runtime/vendor 目录，没有进入客户镜像或 Git。

初始化由固定 AI 镜像内的 SDK 完成：INITIALIZED → ALREADY_INITIALIZED → readonly VALID。操作者没有手工制作 installation.json、service.key 或 clock。身份卷通过 subpath 分别挂载 identity、shared 和本服务 state；Metor UID 21001、AI UID 21002、共享 GID 21000。共享商业文件由 SDK 发布为 0640，AI 只读。

## 已完成的自动检查

1. 新环境数据库迁移成功，前端／Java／AI／MySQL 健康；AI readiness 的 database、embeddingModel、chroma 均 UP。
2. 空数据库首登录创建独立管理员。没有读取旧账号、复制旧数据库或内置固定口令。
3. 无商业许可时，Java 与 AI 受控接口均返回 403／LICENSE_REQUIRED，登录和维护仍可用。
4. 真实 Issuer 签发本环境许可，经前端代理的管理员 API 导入，返回 APPLIED；同文件再次导入返回 ALREADY_APPLIED，两端 ACTIVE。
5. AI 状态从其正在运行的 Runtime 的内部认证 API 取得；临时凭据未写入日志或报告。真实 Linux 共享文件 GID 21000／0640，AI UID 21002 可读。
6. 经前端 → Java 鉴权代理 → AI 创建“SDK 0.7.1 部署验证”知识库，上传示例文本；索引任务 SUCCEEDED。真实 BGE 向量检索命中文档，首次相似度约 0.626。
7. 仅重建本项目容器、保留全部数据卷，许可仍 ACTIVE 且文件摘要不变，知识库与索引继续可用；旧环境容器一直运行。
8. 后端网络设为 internal，Java／AI 到公网 IP 的 TCP 连接均被拒绝，数据库／模型／Chroma 仍就绪，重启后经前端的真实向量检索继续成功。只有前端另接 entry 网络以开放 18182，不给两个后端公网出口。

重建容器与禁止出网的最终结果记录在私有 runtime/sdk071-container-deploy/deployment-verification.json。构建、启动和 API 检查日志同目录保存；报告不保存 JWT、ControlProof、密码或密钥内容。

## 实际复杂、麻烦的点

| 实际步骤／现象 | 麻烦在哪里 | 后续可简化方向 |
| --- | --- | --- |
| 先准备 Issuer 配置和独立公钥，再构建两端 | 信任固化在制品里；仅有 SDK 包无法签出被已有镜像信任的新许可。本次为完整体验新建签发身份，因而重建两个客户镜像 | 保持固化规则，提供一份清晰的制作方清单；公开配置从一处导出后由构建工具统一分发 |
| CLI 无 SDK 配置导出子命令 | Web 可下载；本次自动部署使用与 Web 相同的 ProductConfig.to_bytes 生成，自动化需要调用 Python API | 增加薄的公开配置导出 CLI，复用已有配置验证和序列化 |
| 两端各有 license-build 构建输入 | 必须保证原始字节一致，还要选择正确 Docker 参数；配置路径和 key ID 不匹配时需要重建 | 制作工具接收一份公开配置和版本，自动校验、分发、构建、输出摘要 |
| 完整 AI 依赖／模型需提前备齐 | SDK 离线包不能代替 torch、Chroma 和 BGE；只有模型 config.json 不能证明权重齐全 | 交付预制镜像，并在制作期检查完整 wheel 闭包、权重／tokenizer 和模型 manifest |
| 新建一套项目，现有包装器不接受新项目名 | local-stack 只允许 icp-diag-local／restore-check。本次额外保存 Compose 快照并编写固定项目的 manage.py，才能不碰现有环境 | 支持经校验的独立实例名，统一派生卷、网络、端口和私有配置目录 |
| 默认 init 生成历史 p6-local 镜像 tag 和固定端口 | 新版本或并行安装必须逐项改镜像和端口；容易改漏或撞到旧容器 | init 直接接收发布 manifest／实例配置，自动选择正确镜像和未占用端口 |
| 宿主 root + 数值 UID/GID 检查偏向 Linux | 本机是 Mac，不能把 Mac bind mount 所有权当 Linux 授权目录权限；直接套 sudo 并不能证明容器权限正确 | 安装工具支持受审的 Docker volume 模式；首次 root 容器执行 SDK init 后按服务 subpath 挂载 |
| 授权卷必须先初始化，业务容器才能挂载子目录 | Compose 不负责创建 SDK 身份；空卷直接启动会在 subpath／缺件处失败。预建卷还需声明 external，避免“不是 Compose 创建”警告 | 提供单一 prepare 步骤，自动创建卷、SDK init、readonly check，成功后才启动服务 |
| 原生卷与标准宿主目录备份入口不同 | 现有 local-stack backup 接收宿主 LICENSE_ROOT；本次原生卷不能直接冒充宿主路径。本次没有执行整栈备份 | 原生卷安装能力与备份／恢复一起适配，复用既有 SDK check 和归档模块，不新增协议实现 |
| Linux machine-id 在 Mac 上不天然存在 | HOST_INSTALL 需要真实稳定机器标识，不能为了演示伪造；本次选择协议已有的 UNBOUND | 安装前检查绑定条件；界面明确无绑定签发不需要机器码。目标 Linux 再测真实 HOST_INSTALL |
| 空库没有默认账号 | 必须先完成首登录，才能成为管理员并导入许可；只等健康检查还不等于可以操作授权 | 首次部署说明明确首登录规则；保留随机独立账号而非硬编码通用密码 |
| 冷／热构建仍有明显成本 | 本次 Java 依赖离线缓存可用，bootJar 阶段约 31 秒；AI 镜像导出层约 84 秒、解包约 15 秒。网络拉取、完整依赖准备会另增加时间 | 客户只加载制作方镜像；制作方复用已验证基础镜像与依赖缓存，避免每次接入重建依赖 |
| 禁止出网后，健康容器的宿主端口也不再开放 | 本次将唯一 backend 网络设为 internal 后，Docker 不再公开对应端口；四服务健康但浏览器无法访问 | 前端独接 entry 网络发布 18182，后端仅留内部网络。本套已这样配置；以后接入外部 Chat 模型须明确调整出网策略 |
| 应用就绪和完整航空业务可用是两件事 | 本次真实文档入库／检索已通；新空库仍需配置外部 Chat 模型、场景／业务资料。arm64 镜像不包含 AMD64 JNI 解密库 | 安装检查分清模型／数据库就绪与业务配置；AMD64 的真实 DAT/JNI 和外部模型另列必验项 |

优先建议补三项：**按 manifest 初始化实例、安装工具支持原生卷、新增公开配置导出 CLI**。本次只记录实际部署与缺口，没有为演示再增加一套授权机制。

## 验证范围

这是可供本机使用的独立演示环境，使用真实 SDK、数据库、模型与向量库。尚不包含人工 UI、客户 AMD64／真实 DAT/JNI、外部 Chat 模型和真实航空样本的验收。签名恢复未在这套保留环境中注入异常；此前的隔离升级驱动已有两服务恢复证据，未将其冒充本次操作。

本套默认禁止后端出网，适合本地知识检索和授权体验；配置外部 Chat 模型时需先调整网络并提供真实服务地址／凭据。没有复制旧环境的业务配置或 API key。当前原生卷的整栈备份尚未做，不能将重启保留数据等同于备份验收。
