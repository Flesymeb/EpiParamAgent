# 开发机部署与数据同步

目标项目：`yanhaoyang-dev:/mnt/shared-storage-user/yanhaoyang/Projects/EpiParamAgent`。
本机数据源为仓库的 `dataset/benchmark_v0`。初次代码、配置、环境文件及完整 `paper_pool` 迁移由部署流程完成；下面的监听器仅同步 benchmark 数据，不覆盖代码或 `.env.local`。

## 激活开发机环境

进入 SSH 后运行：

```bash
source /mnt/shared-storage-user/yanhaoyang/Projects/EpiParamAgent/scripts/deploy/activate_dev.sh
```

脚本从自身位置定位项目并切换目录。项目 `.venv/bin`、`/data/EpiParamAgent-runtime/bin` 和私有 Pi 1.3 安装目录依次进入 PATH；私有 runtime 包含虚拟环境、Pi 与 bwrap 0.9。`VIRTUAL_ENV` 指向 `.venv` 的实际位置，uv 缓存与 Python 字节码放在 `/data/EpiParamAgent-runtime`。应用自行读取 dotenv，脚本不加载 `.env.local`，也不修改 shell 启动文件。部署流程需先准备 `.venv` 链接及旧绝对缓存路径的兼容链接。原 `uv.lock` 镜像无法直连时，由部署流程按冻结依赖导出经内部 PyPI 代理安装精确版本，精确版本安装已由部署流程完成，详细状态见部署回执。

## 外部访问代理

开发机通过源机 `PJNL251070223` 的已授权 HTTP 代理访问外网。当前连接路径是：开发机 `127.0.0.1:17890` → socat → 私有 Unix socket → SSH → 源机 `127.0.0.1:7890`。开发机已核实仅监听回环地址；socket 权限为 600，父目录为 700，SSH 密钥未复制到开发机。

原TCP反向转发受开发机 SSH `GatewayPorts` 配置影响，会监听所有网卡，现已停止。重启使用下面的 Unix socket 路线。已有 SSH 隧道或 socat 桥接时，不重复启动。

先在开发机准备私有目录：

```bash
install -d -m 700 /data/EpiParamAgent-runtime/private-proxy
```

再在源机启动 SSH，并保持会话运行：

```bash
ssh -N -T \
  -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ControlMaster=no -o ControlPath=none \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -R /data/EpiParamAgent-runtime/private-proxy/egress.sock:127.0.0.1:7890 \
  yanhaoyang-dev
```

socket 建立后，在开发机启动回环桥接，并保持会话运行：

```bash
chmod 600 /data/EpiParamAgent-runtime/private-proxy/egress.sock
socat TCP4-LISTEN:17890,bind=127.0.0.1,fork,reuseaddr \
  UNIX-CONNECT:/data/EpiParamAgent-runtime/private-proxy/egress.sock
```

用开发机的 `ss -lnt` 确认监听为 `127.0.0.1:17890`；用 `ss -lx` 查看 socket。若重启遇残留 socket，先确认源机对应 SSH 已停止、开发机该 socket 无活动监听，再手动清理；启动命令不会自动删除 socket。这里使用现有 OpenSSH 和 socat，没有新增自定义守护进程。

新增外部文献获取和需联网的解析依赖源机、代理、SSH 与 socat 持续运行。本地已命中的缓存按原路由复用，实验室模型地址和回环流量绕过代理。

开发机保留原环境副本 `.deployment/env.local.source`（权限 600）。已部署 `.env.local` 仅调整 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 和 `MINERU_NO_PROXY=false`，保留实验室主机及回环地址的绕过规则；两份配置的哈希见 `.deployment/network_config.json`。后续同步环境文件时须保留这四项开发机设置，源机环境不变。环境仍由应用 dotenv 读取，不将 `.env.local` 当 shell 脚本执行。

当前探测结果：经代理访问 MinerU 官网 HTTP 200；Europe PMC HTTP 503，尚未确认可用。未提交 MinerU 解析请求，官网连通不能代表解析接口已经验证。

## benchmark 默认目录与部署检查

benchmark CLI 默认读取 `dataset/benchmark_v0`。在开发机激活环境后，用以下命令检查默认目录、任务与运行配置；`--plan` 不调用模型、不发网络请求，也不创建实验输出：

```bash
WORKFLOW_LLM_API_KEY=selfhosted-local metaagent evaluation benchmark \
  --profile MP5 --mode screening --input-mode raw_pool \
  --model qwen3.6-35b-a3b \
  --api-base http://s-20261104160440-5qhjb.ailab-ma4agismall.pjh-service.org.cn/v1 \
  --api-key-env WORKFLOW_LLM_API_KEY \
  --run-id dev_readiness --output-dir runs/deployment-plan \
  --plan --json
```

`selfhosted-local` 是此无认证自部署节点使用的占位值，不是真实密钥。模型和地址显式指定，不使用提供商回退。该命令仅作单任务部署检查。正式运行仍需使用已固定的逐次实验快照，并显式传其 `--dataset-root`。

## 增量同步

在原开发机的项目根目录执行一次：

```bash
scripts/deploy/sync_benchmark_v0.sh \
  --source "$PWD/dataset/benchmark_v0" \
  --project yanhaoyang-dev:/mnt/shared-storage-user/yanhaoyang/Projects/EpiParamAgent \
  --once
```

同步按文件内容校验识别同大小、同时间戳的修改。持续同步用相同命令，将 `--once` 换成 `--watch --interval 30`；Ctrl-C 停止。可先加 `--dry-run` 核对传输统计。同步不使用删除选项，源中删除的旧文件会留在目标目录；需要清理时单独核对。实验按清单与快照读取，不凭目录中额外文件扩充任务。

同一来源和目标通过 `flock` 防止重复监听。日志和锁默认位于本机 `~/.local/state/epi-param-agent/benchmark-v0-sync`，可用 `--state-dir` 指定数据集之外的目录。脚本不输出文件内容、凭据或完整环境；单次模式保留 rsync 原始退出码；监听模式遇连接、超时或源文件在同步时消失（code 24）时记录失败，等下个周期重试，其它错误停止。目标目录限当前用户访问，文件保留用户读写及所需执行权限。需要两端已有 rsync、原机有 flock，SSH 使用现有 `yanhaoyang-dev` 配置及非交互认证，不新增系统调度器。

## 每次运行固定输入

在开发机上，先为一个**尚不存在**的运行目录创建独立快照：

```bash
scripts/deploy/snapshot_benchmark_v0.sh \
  "$PWD/dataset/benchmark_v0" \
  "$PWD/runs/my_run_20261105"
```

随后将实验的 `--dataset-root` 指向 `runs/my_run_20261105/inputs/benchmark_v0`。同步器继续更新 live dataset，不更新此快照。快照是独立只读副本，另存逐文件 `benchmark_v0.SHA256.json`；复制前后核对来源及副本哈希。来源在复制期间变化会报未完成，不发布快照，待同步稳定后改用新运行目录重试。既有运行目录一律拒绝修改；数据集存在符号链接时要求先整理为完整可独立复制的目录。

这些脚本只迁移和固定文件，不启动 API、模型或实验。
