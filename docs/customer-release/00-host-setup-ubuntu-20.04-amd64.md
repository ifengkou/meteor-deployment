# ECS 人工验收：环境准备

适用范围：全新 Ubuntu 20.04 x86_64 测试机。命令在 ECS 的同一个 Bash 会话中按顺序执行，使用具有 sudo 权限的账号；任一步报错先停止后续操作。

验收基线：系统自带 Python 3.8.10、Docker Engine 24.0.7、containerd.io 1.6.24-1。Docker 软件包使用阿里云镜像源。安装命令包含系统 Buildx 和 Compose 插件，ICP Diag 部署仍统一使用交付包内固定的 Compose v2.33.0。

## 1. 确认系统与已有 Python

Ubuntu 20.04 使用已有的系统 Python，无需另行安装 python3.8、Python 3.12、pip 或 Python 业务依赖。

```bash
cat /etc/os-release
uname -m
dpkg --print-architecture
python3 --version
python3 -c 'import sys; assert sys.version_info[:3] == (3, 8, 10), sys.version'
```

应为 Ubuntu 20.04（focal）、x86_64／amd64、Python 3.8.10。若检查不符，先核对系统镜像及软件源，不替换系统 Python，也不继续套用以下安装命令。

## 2. 安装基础工具

保留系统现有软件配置，仅更新软件包索引并安装环境准备所需工具。gnupg 用于下一步的 `gpg --dearmor`。

```bash
sudo apt-get update
sudo apt-get -y install \
  apt-transport-https ca-certificates curl software-properties-common gnupg
```

## 3. 配置阿里云 Docker 源并安装指定版本

以下版本变量和仓库变量在同一个会话使用。

```bash
# 版本定义
ICP_DOCKER_VERSION='5:24.0.7-1~ubuntu.20.04~focal'
ICP_CONTAINERD_VERSION='1.6.24-1'

# 添加 Docker 软件包源，使用 keyrings 管理 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL http://mirrors.cloud.aliyuncs.com/docker-ce/linux/ubuntu/gpg \
  | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

ARCH=$(dpkg --print-architecture)
DISTRO=$(. /etc/os-release && echo "$VERSION_CODENAME")

sudo tee /etc/apt/sources.list.d/docker.list > /dev/null <<EOF
deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] http://mirrors.cloud.aliyuncs.com/docker-ce/linux/ubuntu ${DISTRO} stable
EOF

sudo apt-get update

# 按指定版本安装 Engine、CLI 和 containerd；插件使用源内可用版本
sudo apt-get -y install \
  "docker-ce=${ICP_DOCKER_VERSION}" \
  "docker-ce-cli=${ICP_DOCKER_VERSION}" \
  "containerd.io=${ICP_CONTAINERD_VERSION}" \
  docker-buildx-plugin \
  docker-compose-plugin
```

若出现版本找不到或依赖冲突，保留报错及以下查询结果，不改成无版本限制安装：

```bash
apt-cache madison docker-ce docker-ce-cli containerd.io
```

## 4. 启动、固定版本并检查

```bash
sudo systemctl enable --now docker

# 验收期间固定这三项，避免系统更新改变测试基线
sudo apt-mark hold docker-ce docker-ce-cli containerd.io

sudo docker version
sudo docker info --format '架构={{.Architecture}} 存储驱动={{.Driver}}'
sudo docker buildx version
sudo docker compose version
dpkg-query -W -f='${Package} ${Version}\n' docker-ce docker-ce-cli containerd.io
```

`docker version` 的 Client 和 Server 均应为 24.0.7，containerd.io 软件包版本应为 1.6.24-1。系统插件的版本记录到人工验收结果中；其版本不作为 ICP Diag 部署入口的 Compose 版本。

## 5. 核验交付包内 Compose

交付包按安装指引校验并解压到 `/opt/icp-diag` 后，再执行本节。此时仅核验部署资产，不启动业务服务。

```bash
cd /opt/icp-diag

sudo sh deployment/scripts/verify-bundle.sh .
sudo ./deployment/bin/docker-compose-v2 version
```

包内校验应通过，工具版本应为 `Docker Compose version v2.33.0`。无需另外安装 docker-compose V1 或将包内工具复制到系统目录。

环境准备完成后，按交付包 `deployment/docs/install.md` 继续镜像导入、目录权限准备、单独的 license-init、迁移和启动。部署和运维统一使用 `sudo python3 deployment/scripts/local-stack.py ...`，入口自动调用并校验包内 Compose；不直接使用系统 `docker compose` 启动本次验收栈。
