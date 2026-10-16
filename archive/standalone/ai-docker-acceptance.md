# 本机独立 Docker 验收

本文验证工程自身的 `compose.yaml`，不依赖 Java 服务、工作区 gateway 或工作区生产 Compose。
验收结果应针对当前代码和镜像重新生成，不沿用历史容器名称或一次性日志。

## 准备与启动

从 `ai-runtime-service/` 执行：

```sh
docker build -t ai-runtime-service:local .
mkdir -p runtime/config
cp config/docker.env.example runtime/config/standalone.env
cp config/embedding-models.example.json runtime/config/embedding.standalone.json
# 按本机路径和镜像标签修改两个私有文件
export AI_DOCKER_ENV_FILE="$PWD/runtime/config/standalone.env"
tools/docker-local.sh up -d
tools/docker-local.sh ps
```

Compose 应启动 MySQL、一次性 migration 和 AI Runtime。MySQL 不发布宿主端口；API 默认映射为
`127.0.0.1:18090 → 8090`。私有环境文件、模型权重和运行数据均不得提交。

## 验收清单

```sh
curl --fail http://127.0.0.1:18090/internal/health/live
curl --fail http://127.0.0.1:18090/internal/health/ready
curl --fail http://127.0.0.1:18090/api/ai/admin/embedding-models
curl --fail http://127.0.0.1:18090/api/ai/admin/knowledge-bases
curl --fail http://127.0.0.1:18090/docs
```

通过标准：

- migration 容器退出码为 0，MySQL 与 AI Runtime 状态 healthy；
- readiness 中 database、已启用的 embedding model 和 Chroma 均为 UP；
- 管理 API 返回统一 `OK` envelope，Swagger UI 可从宿主机访问；
- 重启 AI Runtime 后知识库元数据、原始文档和 Chroma 数据仍存在；
- 默认网络可访问配置的外部 Chat endpoint。

完整功能验收还应执行代码门禁，并完成一次真实的 `上传 → READY → 检索 → 场景调用 → 删除`
闭环。Chat fixture 只验证协议和编排，不代表真实模型效果或性能。启用 acceptance profile 后可使用
fixture；生产配置应指向可达的真实 OpenAI-compatible 或 Ollama 服务。

## 停止与清理

```sh
tools/docker-local.sh stop
```

普通停止不要执行 `down -v`，否则会删除 MySQL、原始文档和 Chroma 命名卷。备份、恢复和生产部署
分别见 [备份恢复](../operations/backup-restore.md) 与
[离线部署](../operations/offline-deployment.md)。
