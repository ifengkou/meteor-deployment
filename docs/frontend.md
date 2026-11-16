# 前端构建、部署与运维

知识图谱 P6 全套 Docker 已通过人工验收。当前入口为 <http://127.0.0.1:18180>，Compose 项目为 `icp-diag-local`。

整栈配置以 [配置索引](configuration.md) 为准，发布、单服务更新和回退统一执行 [Docker 更新手册](updates.md)。部署资产统一位于同级独立 `deployment/` 工程，不由 AI 工程管理。

## 构建

```sh
cd frontend
nvm use
corepack enable
pnpm install --frozen-lockfile
pnpm check
docker build -t metor-platform-frontend:<release> .
```

`pnpm check` 执行 Tokens、类型、lint、格式、测试、生产构建、制品完整性和 Storybook 构建。Dockerfile 生成生产静态制品并以 Nginx 提供服务，容器不运行 Vite。

### 依赖下载超时

`@fontsource/noto-sans-sc` 的锁定包约 73 MB，下载超时发生在依赖安装阶段，尚未执行 Vite 编译。前端配置将单次请求超时设为 10 分钟、最多重试 5 次、并发降为 8；Docker 使用 BuildKit pnpm store 缓存，失败后再次构建可复用已完整下载的包，但未完成的大包仍需重新下载。保留现有构建缓存即可，不必清空 Docker 缓存或删除锁文件。

默认使用 npm 官方源。若该源持续缓慢，可在工作区根目录为本次构建显式指定镜像源：

```sh
FRONTEND_NPM_REGISTRY=https://registry.npmmirror.com \
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261029-1-amd64/build.env \
  build --service frontend
```

`FRONTEND_NPM_REGISTRY` 也可写入选定的 `build.env`；Shell 环境优先。该配置仅作用于 frontend 构建，映射为 Docker build arg `NPM_REGISTRY`，不改变运行配置。直接调用 Docker 时使用 `--build-arg NPM_REGISTRY=https://registry.npmmirror.com`。依赖版本及完整性仍按现有 `pnpm-lock.yaml` 校验。

生产构建读取 `.env.production`，默认 `VITE_DATA_MODE=real`。所有 `VITE_*` 都进入浏览器包，禁止放置密码、Token 或模型密钥。修改后需重新构建前端镜像；容器环境变量无法修改已构建 JS。脚本、图标、字体和样式本地发布，不依赖 CDN。

## 配置生效方式

| 配置位置                         | 职责                                                        | 生效方式                            |
| -------------------------------- | ----------------------------------------------------------- | ----------------------------------- |
| `.env.local`                     | 本机 Vite 的 `JAVA_PROXY_TARGET`、`AI_RUNTIME_PROXY_TARGET` | 重启 Vite                           |
| `.env.production`、`VITE_*`      | 前端构建选项                                                | 重新构建并替换镜像                  |
| `deploy/default.conf.template`   | Nginx 路由、上传大小、代理超时及缓存                        | 重新构建并替换镜像                  |
| Docker 的 `JAVA_UPSTREAM`        | Nginx Java 上游，格式为不带协议的 `host:port`               | 通过 Compose 重新创建 frontend 容器 |
| 平台设置、模型服务、知识库及场景 | 数据库中的业务配置                                          | 通过页面/API 保存，按业务规则生效   |

推荐本地代理链为 `5173 → Metor 8080 → AI 8090`。当前本机的私有联调配置可能覆盖 AI 为 `18091`，不能作为共享默认值。直连 AI 只用于隔离本机联调。`.env.local` 是本机配置，不作为过期构件删除。

Docker 中 `JAVA_UPSTREAM=metor:8080`，Metor 再通过 `METOR_PLATFORM_AI_RUNTIME_BASE_URL=http://ai-runtime:8090` 访问 AI。修改 Compose 环境变量后使用 `up -d` 重新创建受影响容器；`restart` 不读取新的环境变量。

## 平台外观设置

用平台管理员账号登录，从右上角齿轮菜单进入「平台外观」。设置平台名称，上传登录页 Logo、平台内 Logo、favicon 和登录背景图，选择布局并设置配色。保存后检查登录页、浏览器标签页和登录后的菜单布局。

2026 年 10 月 27 日 AMD64 人工验收使用了以下配置，图片和截图收录在当次「外观设置和业务数据配置」验收包中。

| 设置项 | 验收值 |
| --- | --- |
| 平台名称 | 外场巡检巡修平台 |
| 登录页 Logo | `avic-login-logo.png` |
| 平台内 Logo 和 favicon | `avic_logo.png` |
| 登录背景图 | `backgroup.png` |
| 布局 | 顶部加通栏侧边菜单 |
| 主色、Header 背景色和菜单字体颜色 | `#0081CC` |
| Header 文字与图标颜色 | `#FFFFFF` |

## 路由与认证

| 路径                          | 行为                                     |
| ----------------------------- | ---------------------------------------- |
| `/healthz`                    | Nginx 和静态制品存活检查                 |
| `/index.html`                 | 禁止缓存                                 |
| `/assets/<hash>`              | 一年 immutable；不存在资源返回 404       |
| SPA 深链接                    | history fallback 到 `index.html`         |
| `/platform/*`、`/aerospace/*` | 代理 Metor，错误不回退 SPA               |
| `/platform/settings/*`        | HTML 导航走 SPA，JSON/API 请求代理 Metor |
| `/api/ai/*`                   | 代理 Metor 平台网关，再转发 AI Runtime   |
| 其他 `/api/*`                 | JSON 404，不进入 SPA fallback            |

网关校验有效平台 JWT 和当前用户 ACTIVE 状态，生成可信用户 ID，不向 AI 透传平台 Token；浏览器不能以 `X-Actor-Id` 伪造身份。当前活跃平台用户可管理 AI 资源，系统 API Key 未开放 AI scope。AI Runtime 只对受信任网络开放；Nginx 路由本身不承担用户授权。

`/api/ai/*` 的 Nginx 上传上限为 32 MiB，Metor 网关及 AI 接口仍执行各自校验。代理失败、业务错误和 traceId 原样保留；写请求不自动重试，超时后应先核实写入结果。

## 发布验收与回退

镜像使用不可变版本号，记录源码版本、镜像 ID、架构和配置版本。整栈与单服务更新按统一手册执行，发布前备份数据库和文件，禁止通过删除数据卷完成更新。

发布后检查前端健康、真实深链接、登录、哈希资源缓存及不存在资源 404，确认 API 错误不返回 HTML。分别检查 Metor readiness 与 AI readiness；前端健康不能证明其依赖可用。AI 入口还需验证匿名拒绝及登录后的管理、检索、上传和下载。

回退时恢复上一已验收镜像并重新创建容器。前端回退不回退 Java、AI 或数据库，涉及契约变化时须一起评估兼容性。不得在运行容器内替换单个 JS/CSS 文件。

`dist/`、`storybook-static/`、`coverage/` 可重新生成。保留依赖缓存、私有配置、当前运行目录及数据卷。历史 M9 镜像和网关关闭记录保留在 [M9 验收记录](../../frontend/docs/acceptance/m9.md)，不作为当前部署操作指南。
