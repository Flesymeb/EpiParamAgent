# MetaAgent-Epi Web

根目录的活动 Web App 与 CLI 共用 `WorkflowOptions` 和相同的 Screening、Coding、Synthesis 引擎。正式端到端任务保留 Coding A＋B；归档中的旧 Web 和旧数据保留不动。

## 启动

在项目根目录安装环境与前端依赖：

```bash
uv sync --extra web --extra langextract --extra dev
npm --prefix webapp/frontend ci
npm --prefix webapp/frontend run build
webapp/run-backend.sh
```

构建后的页面与 API 共用 `http://127.0.0.1:8000`。服务默认只监听本机；`WEB_HOST` 和 `WEB_PORT` 可显式调整。开发前端可在另一个终端运行 `webapp/run-frontend.sh`，使用 `http://127.0.0.1:5173`，`/api` 由 Vite 转发到后端。

每个工作区只允许一个后端服务持有运行 lease；第二个实例会拒绝启动而不终止现有任务。长任务运行时不要使用后端 `--reload` 或多个 Uvicorn workers；不同服务实例应指定不同的 `METAAGENT_WEB_WORKSPACE`。导入 API 模块和运行测试不会终止正在运行的服务任务。

已有模型与 MinerU 配置继续从根 `.env.local` 读取。Web 设置可分别配置 Query、Screening、Coding 和 Synthesis；密钥字段只写入私有配置，响应不回显，留空保留现值。任务 YAML 只引用密钥环境变量名。

## 使用

1. 新建任务，填写研究问题并检查完整纳入标准、分析协议和代码簿；各来源使用其原生检索式，也可由 Query 生成 PubMed 查询。YAML 编辑器保留高级配置。
2. 运行完整端到端，或选择独立筛选、独立编码、独立综合并提交相应 JSONL 输入。PDF、Markdown 和输入文件可上传到任务目录，再使用返回路径。
3. 查看实际阶段、日志、原文证据、结构化记录和图表／报告。`partial`、`failed`、`protocol_pending` 和无法综合的状态保留原意，未生成科学结果时不显示虚构数值。
4. 人工修订使用核心 review 接口，填写审核人和理由；机器原始预测不覆盖，误贴密钥会被拒绝。旧综合结果立即标记过期，续跑完成后按实际产物版本刷新数值和森林图。
5. 停止按钮只中断核验过的受管 worker，保留原始产物，可继续按内容哈希续跑。XLSX／ZIP 等二进制文件提供下载，JSONL、JSON、Markdown、PNG 和 PDF 可直接检查。

## 工作区

默认 `runs/webapp/`，可用 `METAAGENT_WEB_WORKSPACE` 指定其他路径。任务、运行记录和私有设置持久化；后端重新启动后中断的任务明确标记，可从保存输入续跑。根 `paper_pool/` 跨任务共享原文和解析缓存，模型输出按独立运行隔离。

`private/` 下的运行配置包含密钥，不是可下载产物。服务不把私有工作区作为静态目录公开。Web 后端边界与前端类型见 [API_CONTRACT.md](API_CONTRACT.md)。

前端检查：`npm --prefix webapp/frontend run build`、`npm --prefix webapp/frontend run lint`；后端检查：`.venv/bin/python -m pytest tests/test_webapp_api.py -q`。真实模型结果、浏览器联调及科学验收范围记录在根 [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)。

本轮默认工作区保留一条 **COVID-19 SI · 真实单报告开发验证**：六个阶段实际完成，Coding A／B 各一次，结果为 single_estimate，属于软件集成验证而非正式综述。来源、原文与模型输出可在运行页查看并下载。[独立真实 HTTP 验收](../runs/webapp_acceptance/web_real_full/TESTER_REPORT.json)记录了请求、17 个下载产物、精确证据跨度及经校验的 MinerU 缓存关联。
