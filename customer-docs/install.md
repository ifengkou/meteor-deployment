# 安装

仅用于全新 Linux AMD64 主机。已有安装请使用[运维指南](operations.md)的更新流程，保留原配置、数据库卷和授权目录。以下命令在具有 Docker 权限的 root 运维会话执行，可先用 sudo -i 进入。

## 1. 检查环境

```bash
uname -m
docker version
python3 --version
```

目标版本：架构 x86_64、Docker Engine 24.0.7、Python 3.8.10 或更高版本。部署脚本使用本包 deployment/bin/docker-compose-v2（固定 v2.33.0），无需安装 Python 依赖、另装 Python 3.12 或修改系统 docker-compose 1.25.0。后续操作统一通过 local-stack.py 执行。

准备足够的镜像、模型和业务数据空间，并确认时钟同步、DNS、客户访问入口和 Chat 模型服务网络。Docker 版本的最终兼容性以客户主机的镜像导入与运行检查为准。

## 2. 校验、解压、导入

在收到的归档所在目录，将下方文件名替换成实际发行包文件名。归档旁的 .sha256 必须与发行记录一致。

```bash
sha256sum -c icp-diag-linux-amd64.tar.gz.sha256
mkdir -p /opt/icp-diag
tar --no-same-owner -xzf icp-diag-linux-amd64.tar.gz --strip-components=1 -C /opt/icp-diag
cd /opt/icp-diag
./deployment/bin/docker-compose-v2 version
sh deployment/scripts/import-images.sh .
```

解压目标必须是空目录。脚本检查包内 SHA256SUMS、许可 SDK、模型与清单，导入后再检查镜像 ID 和架构。任一步失败即停止，不手工替换 tag 或跳过校验。缺少镜像时不会自动从公网拉取。

## 3. 准备目录与配置

```bash
python3 deployment/scripts/prepare-runtime.py
```

脚本自动选择本包镜像，填写目标主机路径，复用包内三项数据库密码与 JWT，生成 runtime/config/docker.env（0600）及 Embedding 清单；创建数据、日志、工作、备份目录并设置数值权限。完整模型已在 models/embedding，无需另传权重，运行时只读挂载。

Metor UID/GID 为 21001，AI 为 21002，共同许可组为 21000。脚本检查实际镜像账号和主机数值账号冲突；不得使用 chmod 777 或对整个安装目录递归改属主。SELinux 主机由运维落实相应挂载策略。

相同配置下可重复执行；已有不同配置、软链接或非空目录属主不符会拒绝覆盖。准备完成后人工修改过配置时，按更新流程维护，不重新运行脚本来重置已有安装。

前端默认绑定 `0.0.0.0:18180`，允许通过宿主机局域网 IP 访问；Metor 18080、AI 18092、MySQL 13306 仍仅绑定本机。需要变更端口时，启动前修改生成的私有 env，避免与已有服务冲突。默认开启 AMD64 DAT 解密，航空 AI 先关闭，业务配置完成后再开启。

## 4. 初始化安装授权资料

确认本安装 Metor／AI、源码进程和旧初始化任务均未运行，确认真实稳定的 /etc/machine-id 可用，再执行：

```bash
python3 deployment/scripts/local-stack.py license-init
python3 deployment/scripts/local-stack.py license-init
```

首次应为 INITIALIZED，再次为 ALREADY_INITIALIZED。SDK 在固定镜像内断网生成安装身份、主密钥和两端初始时间记录；不要手写、复制其他安装的身份或删除 clock 重试。授权目录为 /opt/icp-diag/runtime/license，升级时整体保留。

若结果为 OUTCOME_UNKNOWN，停止写入后用同命令核对；已完成资料损坏或缺件时保留现场，联系实施人员按备份规程处理，不删除后重建。

## 5. 迁移与启动

```bash
python3 deployment/scripts/local-stack.py compose config --quiet
python3 deployment/scripts/local-stack.py compose up -d --wait mysql
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
python3 deployment/scripts/local-stack.py compose ps
curl --fail http://127.0.0.1:18180/healthz
curl --fail http://127.0.0.1:18080/actuator/health/readiness
curl --fail http://127.0.0.1:18092/internal/health/ready
```

逐条确认成功后再继续。AI 显式运行 Alembic，Metor 启动执行 Flyway。MySQL 使用命名卷，数据库为 metor_service 和 metor_ai；修改 env 不会给已有 MySQL 用户改密，也不会重放初始化 SQL。

## 6. 访问与开通

全新空用户库的第一次有效登录会创建首管理员；由授权实施人员先通过受控入口完成，使用客户约定的强口令，再开放业务入口。没有默认客户密码。

局域网浏览器访问 `http://客户主机IP:18180/`，并在主机防火墙／云安全组中允许实际客户端来源访问此前端端口。也可使用 SSH 隧道，在操作电脑运行：

```bash
ssh -N -L 18180:127.0.0.1:18180 operator@customer-host
```

使用上述隧道时，浏览器打开 http://127.0.0.1:18180/。需要域名／TLS 时可配置反向代理，将入口转发至前端 18180 端口，并验证上传大小、长任务超时和下载。同宿主代理可使用 127.0.0.1:18180。不要直接开放数据库和 AI 管理端口。

按[软件授权](license.md)取得申请并导入许可，再完成[业务配置](business-config.md)。健康检查通过不代表商业许可、Chat 服务或航空业务已经可用。
