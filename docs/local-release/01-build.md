# build：本机 Linux ARM64 镜像

范围：在 Apple Silicon 的 Docker Desktop 中制作本机镜像。构建不更新运行容器，也不创建授权资料；部署接着执行 [02-deploy.md](02-deploy.md)。本机使用 CUSTOMER_REQUIRED，不能用 IDE JAR／默认 bootJar 替代此入口。

## 1. 准备正式构建输入

需要三个源码工程、Docker Desktop、Python 3.9+，以及忽略于 Git 的 SDK 输入：

- Java 正式 SDK 0.7.1 Maven 制品：`metor-service/vendor/license-maven/`，见 [Java 构建输入](../../../metor-service/license-build/README.md)。
- Python 正式 SDK 0.7.1 wheel：`ai-runtime-service/wheelhouse/`，见 [AI 构建输入](../../../ai-runtime-service/license-build/README.md)。
- Issuer 导出的同一份公开配置，分别放在 `ai-runtime-service/license-build/license-product.json` 和 `metor-service/license-build/license-product.json`。

```bash
unset MYSQL_IMAGE AI_RUNTIME_IMAGE METOR_IMAGE FRONTEND_IMAGE METOR_PLATFORM
unset LICENSE_PRODUCT_CONFIG
cmp ai-runtime-service/license-build/license-product.json metor-service/license-build/license-product.json
python3 deployment/scripts/license_artifacts.py --workspace .
docker context show
```

本流程使用 `desktop-linux` context。SDK 和公开配置是构建输入；`license-product.json` 不是待导入的商业许可。

默认配置路径分别相对于两个业务工程，不相对于 deployment。若要选其他配置，先在两个工程都放好同一份 `license-build/customer-product.json`，再对那条 build 命令加进程变量：

```bash
LICENSE_PRODUCT_CONFIG=license-build/customer-product.json \
  python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build
```

路径只能在各工程 `license-build/` 内；两份原始字节须一致。**该值只从进程环境读取，不读取 build.env／docker.env 中的同名字段**。改公开配置／SDK 后重建受影响的两个后端；运行时改 env 不能替换镜像内信任。

## 2. 单独保存制作配置

每次源码变化使用新 tag，避免覆盖回退镜像。以下以 `release-20261028-1-arm64` 为例，实际制作时填写本次唯一版本。创建私有目录和 `build.env`：

```bash
mkdir -p runtime/release/release-20261028-1-arm64
chmod 700 runtime/release/release-20261028-1-arm64
```

文件 `runtime/release/release-20261028-1-arm64/build.env`：

```dotenv
MYSQL_IMAGE=mysql:8.4
AI_RUNTIME_IMAGE=ai-runtime-service:release-20261028-1-arm64
METOR_IMAGE=metor-service:release-20261028-1-arm64
FRONTEND_IMAGE=metor-platform-frontend:release-20261028-1-arm64
METOR_PLATFORM=linux/arm64
```

MYSQL_IMAGE 保持已有、已验收的 ARM64 版本；普通 build 不制作 MySQL。不要用这个精简文件覆盖 `runtime/config/docker.env`。

## 3. 制作全套或指定服务

```bash
chmod 600 runtime/release/release-20261028-1-arm64/build.env
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build
```

仅制作某个服务时，任选对应命令：

```bash
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build --service frontend
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build --service metor
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build --service ai
```

`--service` 可重复，例如 `build --service ai --service metor`。AI 镜像同时用于 `ai-runtime` 和一次性 `ai-migrate`。AI 离线制作先准备完整 ARM64 wheelhouse：

```bash
TARGET_PLATFORM=linux/arm64 deployment/scripts/prepare-wheelhouse.sh
python3 deployment/scripts/local-stack.py \
  --env-file runtime/release/release-20261028-1-arm64/build.env build --service ai --offline
```

Java／前端无网源码重建不在 `--offline` 支持范围。

## 4. 核对产物，转入 deploy

```bash
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  mysql:8.4 ai-runtime-service:release-20261028-1-arm64 \
  metor-service:release-20261028-1-arm64 metor-platform-frontend:release-20261028-1-arm64
```

四项应为 `linux/arm64`。普通 build 的产物直接在当前 Docker 镜像库，**不生成 dist 文件，不需要 docker load**。这时旧容器仍使用旧镜像；下一步到 [deploy](02-deploy.md) 备份并切换运行版本。

`--env-file` 必须放在子命令前，只改变本条命令读取的文件，不会自动合并或记住 build.env。省略它时 build 改读 `runtime/config/docker.env`，可能覆盖该文件里的旧 tag；因此本机制作统一推荐显式指定 build.env。不要把 build.env 传给 compose。

ARM64 镜像移除了 x86-64 JNI，deploy 需设置 `METOR_AEROSPACE_DECRYPTION_ENABLED=false`。客户 AMD64 制作、dist 归档和 export 组包见 [客户 build](../customer-release/01-build.md)。
