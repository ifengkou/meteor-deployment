# 运维

以下在 /opt/icp-diag 的 root 运维会话执行。日常使用同一 runtime/config/docker.env，保留项目名 icp-diag-local、数据库卷、业务目录、模型与授权目录。不要重新 init，不执行 down -v 或 volume prune。

## 状态与日志

```bash
python3 deployment/scripts/local-stack.py compose ps
python3 deployment/scripts/local-stack.py compose logs --tail=150 metor
python3 deployment/scripts/local-stack.py compose logs --tail=150 ai-runtime
python3 deployment/scripts/local-stack.py compose config --quiet
```

日志与备份可能包含客户资料，按私有数据保管；不要输出完整 Compose 展开配置。共享目录模式下应用数据、日志和工作文件位于 runtime，MySQL 使用命名卷。禁止多个 AI 实例并发写同一 Chroma。

## 一致性备份

暂停新业务并等待运行任务结束，使用一个尚不存在的新备份目录：

```bash
python3 deployment/scripts/local-stack.py backup /opt/icp-diag/runtime/backups/before-update-001
cd /opt/icp-diag/runtime/backups/before-update-001
sha256sum -c SHA256SUMS
```

工具暂时停止写入服务，备份两业务库、业务文件、向量索引、配置和 SDK 授权状态，再按依赖顺序恢复原运行服务。需要维护期间保持停止时用 backup --keep-stopped。备份不包含模型权重和镜像，另保留发行包、原镜像和对应模型。备份含密码与安装主密钥，保存到受保护的异机介质。

恢复必须先停止写入并保留现场，在空目标按已评审方案执行；不得直接覆盖正在运行的数据库或 runtime。由实施人员核对授权宿主绑定、安装身份、UID/GID、迁移版本及模型后，使用 local-stack.py 的 restore-stack 入口恢复，再完成数据对账。跨架构使用逻辑 SQL 和文件备份，不复制运行中的 MySQL 物理目录。过旧时间记录可能需要[单服务恢复](license.md)，不删除 clock 绕过。

## 更新与配置变更

先校验新包，保留备份及旧版本，按新包指引更新部署资产和导入镜像。已有 runtime 不被新包覆盖，不重新生成密码或安装身份。检查新旧版本兼容关系，再修改私有 env 的相应镜像引用。

前端代码更新：

```bash
cd /opt/icp-diag
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

Java 更新前暂停入口并完成备份，停止前端／Java，更换镜像后恢复 Java，再恢复前端：

```bash
python3 deployment/scripts/local-stack.py compose stop frontend metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

AI 更新前暂停调用并完成备份，按顺序执行：

```bash
python3 deployment/scripts/local-stack.py compose stop frontend metor ai-runtime
python3 deployment/scripts/local-stack.py compose run --rm --no-deps ai-migrate
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait ai-runtime
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait metor
python3 deployment/scripts/local-stack.py compose up -d --no-deps --wait frontend
```

任何迁移失败都停止后续操作。MySQL 版本更新单独安排，不混入普通应用更新。环境变量或挂载变化需重新创建对应容器，例如：

```bash
python3 deployment/scripts/local-stack.py compose up -d --no-deps --force-recreate --wait metor
```

restart 不读取新环境变量。纯镜像且数据兼容的回退可恢复旧 tag 后按同样顺序重建；有不兼容数据迁移时需隔离恢复与对账，不能只回退镜像。始终保留最新许可身份和 clock，不能用升级前旧 clock 冒充镜像回退。

## 故障排查

| 现象 | 检查 |
| --- | --- |
| Python 报方法或语法不存在 | 部署会话及子进程是否使用 Python 3.8.10+ |
| Compose 缺失或校验失败 | 重新校验发行包并恢复包内 deployment/bin/docker-compose-v2，保持可执行权限；统一通过 local-stack.py 调用 |
| 镜像缺失或 ID／架构不符 | 原始包摘要、镜像导入结果、目标架构；不改清单绕过 |
| 文件不可写 | 指定目录数值 owner、挂载读写、SELinux 与剩余空间 |
| AI 不就绪 | 数据库、完整模型、模型清单与 Chroma；查看 readiness 和日志 |
| JNI 解密失败 | AMD64 平台、解密开关、库依赖和实际 DAT 调用日志 |
| 页面不能远程访问 | 回环绑定、反向代理／SSH 隧道、防火墙和证书 |
| 业务 AI 失败 | 真实 Chat 地址、凭据、六场景、检索资源及航空 AI 开关 |
| 商业许可异常 | 按[软件授权](license.md)区分导入、续期和单服务时间恢复 |
