# 本地与 Docker 配置位置

当前已验收的完整环境为 Docker 项目 `icp-diag-local`，页面入口为
<http://127.0.0.1:18180/>。本文中的路径以工作区 `icp_diag/` 为起点；操作命令见
[源码运行手册](../../ai-runtime-service/docs/operations/running.md) 和 [Docker 整体/单服务更新](updates.md)。

## 配置归属

| 配置 | 本地进程 | 当前完整 Docker 栈 |
|---|---|---|
| 前端 | `frontend/.env.local`，模板 `.env.example`；Vite 启动时加载 | 前端镜像内的生产资源、`frontend/deploy/default.conf.template`；Compose 设置 `JAVA_UPSTREAM=metor:8080` |
| AI 数据库、监听端口、存储路径 | 工作区 `runtime/config/ai.local.env`，模板 `ai-runtime-service/config/runtime.env.example`；由 `tools/local.sh` 显式加载 | 工作区 `runtime/config/docker.env`；Compose 映射至进程变量 |
| Embedding 模型 | 工作区 `runtime/config/embedding/local.json` | 工作区 `runtime/config/embedding/docker.json`，只读挂载到 `/config/embedding-models.json` |
| Metor 数据库、JWT、AI 网关及业务配置 | `metor-service/.env.local`，模板 `.env.local.example`；Spring `local` profile 使用 | 同一 `runtime/config/docker.env` + `deployment/compose.metor.yaml`、`compose.full-local.yaml` |
| 统一部署拓扑 | 开发进程独立启动 | `deployment/compose.ai.yaml` + `compose.metor.yaml` + `compose.full-local.yaml`，由 `local-stack.py` 统一选择 |
| 数据与文件 | 按各私有配置指定的宿主目录和 MySQL 连接 | MySQL 保留命名卷；Metor 文件、AI documents/Chroma 由共享目录配置挂载到宿主 runtime |
| 备份 | `ai-runtime-service/runtime/backups/` 或另行指定的私有目录 | `runtime/knowledge-graph-p6/full-stack-backup/` 为交付时备份；日常备份指定新的受保护目录 |

模型权重位于 `ai-runtime-service/models/`，不打入应用镜像，也不提交 Git。Docker 中的
`modelPath` 填容器内路径；宿主挂载源由 `AI_EMBEDDING_MODEL_HOST_PATH` 指定。
当前完整栈启用 BGE，容器路径为 `/models/embedding`；多模型须同时配置清单和对应挂载。

## 当前共享开发测试环境

工作区 `runtime/` 为统一私有运行目录，当前数据库为 Docker 项目 `icp-diag-local`。local 与 Docker 共用业务数据，切换时停止同名 AI/Metor 实例，禁止同时使用同一 Chroma 目录。

| 内容 | 当前位置 |
|---|---|
| Docker 配置 | 工作区 `runtime/config/docker.env` |
| AI local 配置 | 工作区 `runtime/config/ai.local.env` |
| Metor local 配置 | 工作区 `runtime/config/metor.local.env` |
| 模型清单 | 工作区 `runtime/config/embedding/local.json`、`docker.json` |
| 持久文件 | 工作区 `runtime/data/metor`、`runtime/data/ai/documents`、`runtime/data/ai/chroma` |
| Embedding 权重 | 工作区 `runtime/models/embedding/<model-id>`，只读挂载 |
| 日志 | 工作区 `runtime/logs/{local,docker}/{ai,metor}` |
| 临时工作目录 | 工作区 `runtime/work/{ai,metor}` |
| MySQL | `127.0.0.1:13306`；`metor_service` / `metor_ai`，继续使用原命名数据卷 |

Metor `.env.local` 保留为共享源码配置的链接。旧阶段配置和独立 Docker 入口不再使用；用户已有 `.env.docker` 不删除但不读取。前端 Vite 代理指向源码 Metor 8080，Docker 通过内部服务名访问。航空 AI 是否启用以当前私有配置为准。

切换与 CLI 见 [工作区 README](../../README.md)。AI `AI_LOG_PATH` 启用轮转文件日志；`AI_CHAT_HOST_ALIASES` 可配置 local 对 `host.docker.internal` 的映射，模型记录不随运行方式修改。本地请求通过 `NO_PROXY` 排除 localhost，避免进入系统代理。

## Docker 当前入口与内部地址

| 用途 | 宿主入口 | 容器间地址 |
|---|---|---|
| 页面 | `127.0.0.1:18180` | `frontend:8080` |
| Metor | `127.0.0.1:18080` | `metor:8080` |
| AI Runtime | `127.0.0.1:18092` | `ai-runtime:8090` |
| MySQL | `127.0.0.1:13306` | `mysql:3306`；业务库 `metor_service`、AI 库 `metor_ai`，各用独立账号 |

原独立/开发环境的 3307、13307、18090 不再作为当前 local 默认依赖。旧环境未删除。

浏览器管理请求的链路为前端 → Metor JWT 认证授权 → AI Runtime。18092 用于本机运维和
健康检查；不要将直连 AI 管理接口当作对外平台认证入口。

私有 `runtime/config/docker.env` 保存镜像标签、端口、数据库密码、JWT 密钥和挂载源。配置文件为 0600，
所在目录为 0700。修改它后按更新手册重新创建相关服务；普通 `restart` 不会重新加载 Compose
环境。不要重新执行 `init` 覆盖现有配置，也不要将密码改动等同于既有 MySQL 用户已完成改密。

## 进程配置与业务配置的边界

- 进程配置：数据库、存储路径、模型清单位置、端口、网关地址，通过环境和 Compose 管理。
- Embedding 配置：模型 ID、启用状态、权重路径、normalize 等，在模型清单中管理，修改后重启 AI。
- Chat endpoint、模型名称、API Key、调用参数：通过平台“模型服务”维护，存储在 `metor_ai` 的 `ai_model_service`，不是进程 `.env`。
- 知识库、图谱和场景提示词/绑定/检索参数：通过平台配置，保存于业务表；保存即生效，无须重建镜像。

AI 在宿主运行时可用 `http://127.0.0.1:11434` 访问宿主 Ollama；在 Docker 中应改为
`http://host.docker.internal:11434` 或实际模型服务地址。容器中的 `localhost` 指向容器本身。

## 过期配置与恢复资料

过期私有配置归档至工作区 `runtime/backups/retired-configs-20261015.tar.gz`，同名 JSON 记录原路径与校验值。归档、完整备份和离线制品中的配置仅用于恢复，不是运行入口。

旧 `icp-diag-m7` 仍挂载 `ai-runtime-service/runtime/docker/embedding-models.json`，这份文件保留，待旧容器停用后再清理。工程独立 Compose 已归档，不再作为发布入口；只使用 `runtime/config/docker.env`。
