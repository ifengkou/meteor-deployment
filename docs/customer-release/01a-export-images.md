# 从本机 Docker 镜像库导出 tar.gz

适用于 Mac 上已经构建完成的镜像。在工作区 `icp_diag/` 根目录执行；镜像名和 tag 替换为本次 `build.env` 中的实际值。

## 导出单个服务

以前端为例：

```bash
mkdir -p dist
docker image save --output dist/frontend-release-20261029-1-amd64.tar \
  metor-platform-frontend:release-20261029-1-amd64
gzip dist/frontend-release-20261029-1-amd64.tar
```

得到可发送的文件：`dist/frontend-release-20261029-1-amd64.tar.gz`。

导出 Metor 或 AI 时，替换上述镜像引用和输出文件名即可。

## 多个镜像合并导出

例如将四个已构建的镜像放进同一个文件：

```bash
mkdir -p dist
docker image save --output dist/images-release-20261029-1-amd64.tar \
  icp-diag-mysql:8.4-amd64-20261029-1 \
  ai-runtime-service:release-20261029-1-amd64 \
  metor-service:release-20261029-1-amd64 \
  metor-platform-frontend:release-20261029-1-amd64
gzip dist/images-release-20261029-1-amd64.tar
```

得到可发送的文件：`dist/images-release-20261029-1-amd64.tar.gz`。

`gzip` 成功后会删除中间 `.tar`，保留 `.tar.gz`。已有同名文件时换一个输出文件名。这里导出的仅是镜像，不包含模型或部署配置。
