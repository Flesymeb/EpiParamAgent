# 沙盒平台配置

开发机项目目录：`/mnt/shared-storage-user/yanhaoyang/Projects/EpiParamAgent`。

平台 skills 和手册位于 `.deployment/sandbox-skills/`，八个 skill 已链接到开发机的 `~/.codex/skills/` 和 `~/.claude/skills/`。新建 Codex 或 Claude Code 会话后可使用。平台入口和最新版文档：<http://deepenv.sandbox.pjlab.org.cn/portal/#user-docs-skill>。

本次从源机复制了 skills 和手册。开发机访问 skills 的 Git 仓库时尚无可用认证，因此自动 `git fetch` 目前失败；从源机更新时应保留开发机已有修改。

开发机的 `~/.config/sandbox/env` 链接到项目私有文件 `.deployment/sandbox.env`，文件权限为 600。文件包含平台地址、工作台和 AK/SK；不要把它写入仓库、日志或沙盒镜像。

独立 Python SDK 环境位于 `/data/EpiParamAgent-runtime/sandbox-venv`，已安装 `opensandbox==0.1.9`。SDK 使用说明见 `.deployment/sandbox-skills/docs/04-sdk-usage.md`，平台 API、网络与数据迁移分别见同目录下的 `01-api-usage.md`、`07-network-policy.md` 和 `09-2-project-data-custom-mount-guide.md`。

可在开发机用以下只读检查验证凭据与工作台。检查只输出 HTTP 状态和实例数量：

```bash
/data/EpiParamAgent-runtime/sandbox-venv/bin/python - <<'PY'
import json, shlex, urllib.parse, urllib.request
from pathlib import Path

config = {}
for line in (Path.home() / '.config/sandbox/env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        key, value = line.removeprefix('export ').split('=', 1)
        values = shlex.split(value)
        config[key.strip()] = values[0] if values else ''
url = config['SBX_BASE'].rstrip('/') + '/v1/sandboxes?' + urllib.parse.urlencode({'project': config['SBX_PROJECT']})
request = urllib.request.Request(url, headers={'OPEN-SANDBOX-API-KEY': config['SBX_AK'] + ':' + config['SBX_SK']})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=15) as response:
    data = json.load(response)
    print('HTTP', response.status, '沙盒数', len(data.get('items', [])))
PY
```

沙盒使用平台项目存储。开发机上的项目和 `paper_pool` 不会自动出现在沙盒中；启动实验前须按数据迁移与挂载手册核实目标工作台、数据路径、访问权限和模型节点网络连通性。
