# 部署故障处理

Linux 客户使用 `python3 deployment/scripts/local-stack.py compose ...`，macOS Docker Desktop 使用 `python3 deployment/scripts/desktop-stack.py compose ...`，分别从安装根目录或源码工作区根目录执行。
配置位置见 [配置索引](configuration.md)，更新方法见 [更新手册](updates.md)。

| 现象 | 诊断 | 处理 |
|---|---|---|
| 导入许可后时间记录异常，取得恢复申请返回 LICENSE_STORAGE_FAILED | 以真实服务用户检查 clock 和锁文件；尤其核对迁移后是否有 root:root／0600 的 clock.json.lock 或 clock.lock | 按[授权存储权限检查](#授权存储权限检查)停写、保留现场并只修锁权限，重启后核对；不删除 clock 或直接重新初始化 |
| bind source path does not exist，指向 runtime/license/shared | 核对 LICENSE_ROOT、实际卷和挂载源路径 | 本机按[部署配置](local-release/02-deploy.md)核对授权卷；客户首次安装按[部署流程](customer-release/02-deploy.md)准备。使用完整 docker.env |
| 授权备份报数值 owner／mode 不符 | Mac 宿主与 Docker Desktop 容器内看到的 owner 不同 | 本机使用专用 Docker Linux 授权卷与 desktop-stack.py；仅改用 Linux 运维容器仍无法保证 Mac bind 中原子替换文件的跨挂载 owner 一致，不在 Mac 上 sudo 套用 Linux 宿主命令 |
| MySQL 长期 unhealthy | `docker compose logs mysql`；检查 Volume、磁盘和 root 密码 | 修复后重启；既有 Volume 密码与 `.env` 必须一致 |
| `ai-migrate` 非 0 退出 | 查看 migration 日志与 `alembic current/heads` | 保留现场；修复 migration 或恢复升级前备份，禁止改 `alembic_version` 绕过 |
| AI Runtime 不启动 | 检查模型目录挂载、权限、manifest 与环境变量 | 重新校验/安装同一模型制品；保持只读挂载 |
| readiness=503 | 查看响应中的 database、embeddingModel、chroma 分项和容器日志 | 只修复失败分项；liveness=200 不代表可接流量 |
| 外部 Chat 调用失败 | 使用模型服务 test API，检查 endpoint、协议和密钥 | 修复项目外 Chat 服务或内网路由；不会影响全局 readiness |
| 离线构建尝试联网 | 检查 wheelhouse 完整性和 `AI_OFFLINE_BUILD=1` | 在联网制品机重新生成 wheelhouse；不要在目标机临时下载 |
| 出现 CUDA/NVIDIA 包 | 检查 `uv.lock`、wheelhouse 文件名和 `pip list` | 拒绝发布，重新生成 CPU-only 锁与 wheelhouse |
| Chroma 损坏/丢失 | 确认 MySQL、原文档、模型 fingerprint 完整 | 恢复 Chroma 快照，或清空派生数据后运行重建脚本 |
| Metor 报 AI服务未启用，AI 无对应场景请求 | 检查容器内 METOR_AEROSPACE_AI_ENABLED；此报错在发送 HTTP 前由业务客户端抛出 | 核对原 docker.env 为 true，重建 Metor 和前端，按[业务配置步骤](../customer-docs/business-config.md#航空业务-ai-配置)验收 |
| metor 无法调用 AI | 按[配置与连通检查](#metor-访问-ai-的检查)核对业务开关、两个 BASE_URL、服务名解析与 AI readiness | 容器间使用 http://ai-runtime:8090，区分平台代理与航空业务调用 |
| 前端 API 返回 502，但 metor healthy | 比较 frontend 日志中的 upstream IP 与容器内 `getent hosts metor`；旧前端镜像可能仍缓存后端重建前的 IP | 临时执行 `python3 deployment/scripts/local-stack.py compose exec frontend sh -c 'nginx -t && nginx -s reload'`；更新到支持 Docker DNS 动态解析的前端镜像后，IP 变化将自动恢复。`/healthz` 仅检查前端存活 |
| 构建在 load metadata 阶段报 content descriptor/config not found | 检查构建目标平台、当前镜像源及被引用的 blob；索引 HTTP 200 不代表配置／证明文件完整 | 先补齐对应平台基础镜像；镜像源缺 blob 时修复源或从可用代理取得同一不可变摘要，再仅续跑失败组件。不要先清空所有构建缓存 |

## Metor 访问 AI 的检查

在客户主机 root 运维终端选择实际脚本和完整运行 env。首次安装默认路径如下，已有更新按当前完整发行包位置填写 ICP_STACK：

```bash
ICP_STACK=/opt/icp-diag/deployment/scripts/local-stack.py
ICP_ENV=/opt/icp-diag/runtime/config/docker.env
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T metor sh -c \
  'env | grep -E "^(METOR_AEROSPACE_AI_ENABLED|METOR_PLATFORM_AI_RUNTIME_BASE_URL|METOR_AEROSPACE_AI_BASE_URL)="'
```

| 变量 | 作用 | 航空 AI 启用时的预期值 |
| --- | --- | --- |
| METOR_AEROSPACE_AI_ENABLED | 航空业务场景调用开关 | true |
| METOR_PLATFORM_AI_RUNTIME_BASE_URL | 页面 AI 管理、调试的平台代理地址 | http://ai-runtime:8090 |
| METOR_AEROSPACE_AI_BASE_URL | 航空诊断服务的 AI 调用地址 | http://ai-runtime:8090 |

平台调试和航空业务使用独立配置；航空业务的正常值为 true。若运行 env 显式填写 false，会覆盖 Compose 的 true 缺省值。调整配置后用 up --force-recreate 重建服务，restart 不重新载入变量；若变量已为 true 仍出现同一提示，再核对实际容器、启动参数和更高优先级配置。

从 Metor 容器检查 DNS 和 HTTP 连通性：

```bash
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T metor getent hosts ai-runtime
python3 "$ICP_STACK" --env-file "$ICP_ENV" compose exec -T metor \
  curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  http://ai-runtime:8090/internal/health/ready
```

readiness 返回 200 只确认当前连接及 AI 基础依赖；最后以实际航空场景调用验收。前端 502 单独检查前端到 Metor 的连接；旧前端在后端地址变更后需重新解析上游，可在 Metor 重建后重建前端。

## 基础镜像元数据缺失时续跑

错误停在 Dockerfile 的 FROM／load metadata 时，尚未执行产品编译。先确认 `docker info --format '{{json .RegistryConfig.Mirrors}}'` 和镜像真实架构；镜像源可能返回可读的多架构索引，却对其引用的配置文件或 attestation blob 返回 404。此时改变 METOR_PLATFORM 或关闭构建缓存不能补齐远端内容。

以 ARM64 Metor 为例，先预取两个官方基础镜像。AMD64 制作时同步替换平台参数：

```bash
docker pull --platform linux/arm64 eclipse-temurin:21-jdk-jammy
docker pull --platform linux/arm64 eclipse-temurin:21-jre-jammy
```

若按 tag 拉取仍因证明文件缺失而失败，可从可信索引取出 **linux/arm64 平台子清单摘要**，按 `eclipse-temurin@sha256:...` 拉取并核验实际平台，再标记为 Dockerfile 使用的本地 tag。配置或层本身缺失时，需要先恢复镜像源，或从可用代理取得同一个已确认摘要；不能随意换 Java 版本或使用其他架构摘要。此操作只准备制作机基础镜像，不重建运行容器。

AI 已制作成功、Metor 失败且前端尚未制作时，可使用原 build.env 续跑：

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/local-arm64-102801/build.env \
  build --service metor --service frontend
```

上面的 env 路径是本机示例，替换为实际制作配置；只失败一个组件时仅保留对应 --service。基础镜像解析恢复后，apt、Gradle 或前端依赖源仍可能有独立网络错误，按后续日志单独处理，不把它们当作同一次元数据错误。

收集诊断信息时可以保存 `docker compose ps`、最近 200 行日志、镜像 RepoDigest、Compose config 摘要和
健康响应，但必须先脱敏；不要收集 `.env`、API Key、JWT secret、完整提示词或文档正文。

## 授权存储权限检查

以实际服务用户检查授权目录、clock 及锁文件的读写权限，并检查磁盘与挂载模式。Metor 使用 UID/GID 21001，AI 使用 21002；服务锁为 0600，分别属于对应服务。

进行权限维护前停止应用写入并保留授权现场。只修正实际不符的元数据，保留身份、密钥、许可和 clock 原字节；维护后重启受影响服务，核对 ACTIVE 与持续 checkpoint。需要签名时间恢复时使用[恢复流程](license-recovery.md)。
