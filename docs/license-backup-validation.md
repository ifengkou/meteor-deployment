# 隔离验证授权初始化、备份与恢复（SDK 0.7.1）

当前专项测试直接使用客户 AI 镜像里已安装的 SDK，调用同一份 init/check 和 license_backup 模块。宿主不安装 SDK，不引用相邻 SDK 源码，不运行旧初始化器。旧 Phase 5.5 文档里的 initialize_license／canonical 调用已删除；历史结果不能代替本轮升级验收。

## 前提

准备同架构、已加载的 CUSTOMER_REQUIRED AI 镜像，含正式 SDK 0.7.1 与完整公开产品配置。所有测试根位于一个全新、专用 Linux Docker 卷。不要挂载 runtime、真实授权目录或 Docker socket。测试无需数据库、模型、商业私钥或公网，不修改系统时间。

下面在源码工作区根目录执行；AI_IMAGE 替换为已核对的完整 sha256 ID。卷名必须尚未存在；示例增加唯一后缀，不复用业务卷。

```bash
AI_IMAGE=sha256:<reviewed-ai-image-id>
PROOF_VOLUME=icp-sdk071-proof-<unique-suffix>
docker volume create "$PROOF_VOLUME"
docker run --rm --pull=never --network=none --user 0:0 \
  --mount "type=volume,src=$PROOF_VOLUME,dst=/proof" \
  --mount "type=bind,src=$PWD/deployment/scripts,dst=/opt/license-tools,readonly" \
  --mount "type=bind,src=$PWD/deployment/tests/verify_license_tools_linux.py,dst=/verify.py,readonly" \
  --env PYTHONPATH=/opt/license-tools:/app \
  --entrypoint /app/.venv/bin/python "$AI_IMAGE" /verify.py
```

预期退出码 0，并输出 8 组已通过的 JSON 结果：

1. SDK 首次安装与重复核对；重复不改 UUID、key、clock、owner/mode。
2. SDK 合法 draft 在身份发布前中断，重试保留原身份与主密钥完成。
3. 权限阶段失败后的同命令重试，保留 SDK 已完成资料。
4. 商业文件缺失或无效不阻止只读完整安装 check，check 不改 clock。
5. 真实 UID 21001／21002、共享 GID 21000：两端读身份和商业文件，只写本服务 state，AI 无商业写权，Metor 无 AI state 权限。
6. 同宿主空目标备份恢复，UUID、全部协议文件及 owner/mode 保持；锁不入包，非空或异宿主目标拒绝。
7. 损坏或缺失 clock 拒绝且不修复；未知文件、链接、特殊文件及非法归档另由宿主单测覆盖。
8. SDK 版本或包内公开配置不符在写入目标前拒绝。

## 真正只读挂载

使用上一步相同的专用卷，卷中 /license 为测试初始化目录。以下把整卷挂成只读，仍应返回 state=VALID；即使存在锁文件也不打开或创建锁，不改变任何授权资料：

```bash
docker run --rm --pull=never --network=none --read-only --user 0:0 \
  --mount "type=volume,src=$PROOF_VOLUME,dst=/proof,readonly" \
  --mount "type=bind,src=$PWD/deployment/scripts,dst=/opt/license-tools,readonly" \
  --env PYTHONPATH=/opt/license-tools:/app \
  --entrypoint /app/.venv/bin/python "$AI_IMAGE" \
  /opt/license-tools/license_init.py check --root /proof/license

# 只删除本次创建、已退出容器不再使用的测试卷。
docker volume rm "$PROOF_VOLUME"
```

## 宿主边界检查

在没有宿主 SDK 的环境运行标准库测试；资产补充检查需要研发 pytest，不是客户运行依赖：

```bash
python3 -m unittest discover -s deployment/tests -p 'test_*.py'
python3 -m pytest deployment/tests
```

保存镜像 ID、实际 Linux 架构、执行命令和通过／跳过结果，不记录主密钥、私钥或维护凭据。Mac 上 Docker 的 Linux arm64 卷可验证数值权限，Mac bind mount 的所有者显示不能当作 Linux 权限证据。客户 AMD64 仍需单独执行。

本专项没有验证全部业务启动、UI、真实客户信任或旧新产品升级；另见 [SDK 制作与升级](license-sdk-upgrade.md)、[整栈备份恢复](backup-restore.md)和 [页面人工清单](../../frontend/docs/acceptance/software-license.md)。
