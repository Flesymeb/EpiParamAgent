# MetaAgent-Epi

MetaAgent-Epi 通过 CLI 执行传染病文献综述：检索、题录筛选、全文获取、参数编码与合并分析。本轮优先跑通 CLI 并验证真实效果；新 Web 工作台已暂停，源码与已有运行记录保留，当前界面尚未获得用户认可。

前一轮归档记录见[归档索引](archive/20261103_160112_pre_refactor/README.md)。原 `paper_pool/` 已恢复至项目根目录，继续作为共享全文缓存；归档清单保留迁移时的历史记录。后续改造见 [OPTIMIZATION_PLAN.md](OPTIMIZATION_PLAN.md)；目录精简不代表重构已经完成。

用户明确保留当前根 [docs/](docs/)：其中的新审计材料已完成，供后续优化使用。旧 docs 已移至归档，二者不覆盖，新 docs 不表示恢复了旧目录。不要盲目重跑归档脚本的 `--apply`；同时存在的新旧 docs 会触发安全拒绝。

## 当前实现

端到端主线为 Query／检索 → Screening → Coding（A 候选提取＋B 语义核查定稿）→ Synthesis，三个模块使用相同执行接口，也支持单独运行。新任务通过 YAML 定义研究问题、review 协议、codebook 和综合设置，无须注册 benchmark profile。[新任务模板](configs/templates/review_task.yaml) 显式使用 Pi 综合；[确定性兼容模板](configs/templates/review_task.deterministic.yaml) 保留独立 analysis 协议。旧任务省略 synthesis 设置时仍走确定性路径，也可用 `--synthesis-backend pi` 或 `--synthesis-backend deterministic` 显式选择。

Coding 的 A 输出结构化候选，默认新任务内部使用 LangExtract；B 按同版本原文核查定稿，保留在正式主线中。普通 workflow 与 smoke 默认运行 full（A＋B）；without_a、without_b 仅在显式阶段消融时使用，并记录实际调用与证据坐标。旧 index 命令仅为兼容保留。软件验收与科学数据验收分开，见 [实现验收记录](IMPLEMENTATION_STATUS.md)。

## 核心入口

|目录/入口|职责|
|---|---|
|[metaagent/](metaagent/)|CLI、筛选、编码、工作流与基准接口|
|[configs/](configs/)|任务配置、codebook、Stage A/B 提示模板|
|[tools/](tools/)|检索、全文获取及 CLI 调用的工具；`tools/scripts` 含运行依赖|
|[webapp/](webapp/README.md)|暂停开发的工作台源码；本轮使用 CLI，旧界面保存在归档中|
|[dataset/](dataset/README.md)|v1、v2 draft、benchmark_sources，以及4个旧数据路径的兼容软链|
|[docs/](docs/)|用户要求保留的新审计材料，供后续优化使用；旧 docs 位于归档|
|[pyproject.toml](pyproject.toml)、[uv.lock](uv.lock)|依赖与可重复环境|
|[archive/20261103_160112_pre_refactor/](archive/20261103_160112_pre_refactor/README.md)|重构前快照、Git 历史及历史工作区索引|

旧测试保存在 [legacy/tests/](archive/20261103_160112_pre_refactor/legacy/tests/)，追加记录见 [tests_archive_manifest.json](archive/20261103_160112_pre_refactor/tests_archive_manifest.json)。根目录 `tests/` 是后续新增的针对性测试；旧 fixture 可按需恢复，不能自动当作新方案已通过验证。

`benchmark_v1` 是保留的历史参考版本；`benchmark_v2` 仍是 draft，来源成员、目标资格、最终估计贡献和逐研究编码分别记录。源综述转录不等于原始研究已核验；待审行不能当作已认证 GT 评分。新检索结果与人工补齐候选池分开记录。

## 安装与配置

需要 Python 3.11+、Git 和 uv：

```bash
uv sync --extra dev --extra langextract --extra benchmark
cp -n .env.example .env.local  # 保留现有本地配置
uv run metaagent --help
uv run metaagent profile list
```

本轮不需要安装或启动 Web 服务。旧界面保留在 [legacy/webapp](archive/20261103_160112_pre_refactor/legacy/webapp/)，现有 [webapp/](webapp/) 也保留；暂不恢复、删除或继续重构界面。

在本地 `.env.local` 配置实际模型端点与凭据，不把凭据写进命令、日志或版本库。先检查所选任务配置；检查是否通过须按具体 profile 判断，不能视为所有 profile 都已就绪：

默认 LLM 配置使用 `pjlab` 网关和 `PJLAB_MODEL`。可将 `.env.local` 中的 `QUERY_LLM_PROVIDER`、`SCREENING_LLM_PROVIDER` 或 `CODING_LLM_PROVIDER` 分别改为 `selfhosted`，使对应模块使用自部署节点的 `SELFHOSTED_MODEL`；如要同时切换共享默认值，也修改 `LLM_PROVIDER`。模块级 `*_LLM_MODEL` 若被设置会覆盖所选 provider 的模型，切换时需删除或同步修改。自部署节点当前无需真实密钥，OpenAI 兼容客户端使用 `SELFHOSTED_API_KEY=empty`；代理环境下需将节点主机名加入 `NO_PROXY`。两种服务的模型 ID 不同，请勿混用。工作流和基准命令若显式传入 `--model`、`--api-base`、`--api-key-env`，则使用这些参数。

LLM 配置按 `QUERY_LLM_*`（检索词生成）、`SCREENING_LLM_*`（筛选）、`CODING_LLM_*`（编码）和 `SYNTHESIS_LLM_*`（参数综合）分别设置；每个阶段都可以单独指定 provider、model、API base、API key、温度、超时和 token 上限，未设置时使用所选 provider 或共享配置。使用 `uv run metaagent config check --stage synthesis` 检查综合阶段的 LLM 配置。新主线 `pooling` 使用独立 SYNTHESIS 配置，由 Pi 根据研究问题、Coding 表和方法／原始研究材料规划分析、写代码、在隔离沙箱执行、重复核验并有界修复；只有实际执行和校验通过的产物才能作为结果。没有预填 AnalysisProtocol 时，可明确声明假设并开展探索性分析，不把原综述的合并值当作调参目标。确定性兼容路径仍按显式 analysis 协议计算，可选启用受校验的 `llm_selection`／`llm_report`；两个路径都不能补做被消融的 B。Pi 后端需要本地 Pi 1.3.0 和 bubblewrap；预算、来源角色及恢复规则见 [Synthesis 模块说明](metaagent/synthesis/README.md)。

```bash
uv run metaagent config --help
uv run metaagent config check --profile <PROFILE_ID>
```

当前各模块入口：

```bash
uv run metaagent pubmed --help
uv run metaagent screening --help
uv run metaagent pdf --help
uv run metaagent coding --help
uv run metaagent workflow --help
uv run metaagent evaluation --help
uv run python -m tools.benchmark_v2.build --help
```

多来源文献检索和开放 PDF 获取：

```bash
uv run metaagent literature search --source europepmc --source medrxiv --source openalex --query 'mpox AND incubation' --limit 100 --out output/literature-search
uv run metaagent literature pdf --doi 10.1371/journal.pone.0256482 --out output/article.pdf
```

支持 `pubmed`、`europepmc`、`medrxiv`、`biorxiv`、`openalex`、`crossref`。medRxiv/bioRxiv 通过 Europe PMC 检索其预印本。不同来源的检索语法和覆盖范围不同；复杂检索应分别按来源运行并核对检索式，不能直接把 PubMed 检索式当作其他来源的完整等价表达。每源有 `--limit` 上限，`manifest.json` 记录查询、数量、截断及失败状态；`records.jsonl` 可作为 `workflow run --input-mode raw_search --raw-input ...` 输入。合并仅基于无冲突的 DOI 或 PMID；预印本和正式发表版本不自动合并，需要人工核验。任务 YAML 的 search 为逐来源原式，已接入统一工作流。未传 --limit 时按游标分页，保留页缓存和检查点；只有终止条件、数量、身份及计数一致性检查通过才标记完整。商业数据库另支持 literature import-native 导入已合法导出的 RIS/CSV 及执行日志。

OpenAlex 可填写 `OPENALEX_API_KEY` 获得独立额度；Unpaywall PDF 查找需要 `UNPAYWALL_EMAIL`（未设置时使用 `NCBI_EMAIL`）。Europe PMC、medRxiv、bioRxiv 和 Crossref 不需要 API key，Crossref 可选填写 `CROSSREF_EMAIL`。Embase 的 `EMBASE_API_KEY` 和 `EMBASE_INST_TOKEN` 仅作为未来授权接入的占位，当前没有实现 Embase API 检索。Unpaywall 下载只处理其提供的 PDF 链接，旁边的 JSON 记录来源和 SHA-256；获取 PDF 后，仍需经既有全文解析流程生成编码所需文本。

运行前确认输入、任务资格、人群和时段。恢复任务时显式指定运行目录，避免混用旧输出；基准标签与来源证据不能作为模型输入。

默认全文获取统一走严格 PDF 路线：先查根目录 `paper_pool/` 的身份／版本绑定缓存，未命中再从开放来源下载、核对 PMID／DOI／标题／预印本版本，再通过 MinerU 解析。复用须匹配原 PDF SHA-256、解析器／配置指纹和 Markdown 内容，保留原 PDF 与解析资产。仅凭 PMID 文件名命中的旧 Markdown、无 PDF 的历史缓存或 PMC XML，不能算作已取得并验证 PDF；失败保留为缺源，不冒充 MinerU 成功。用户显式提供的 Markdown／TXT 可作为 provided text 使用，但记录 `pdf_status=not_provided`，不声称下载了 PDF。`METAAGENT_PAPER_POOL` 可指定独立纸池；MinerU 解析失败不会静默退回简单 PDF 文本提取。

Stage A 内部 LangExtract 依赖：

```bash
uv sync --extra dev --extra langextract
uv run metaagent coding extract --help
```

[A_paper](archive/20261103_160112_pre_refactor/legacy/A_paper/) 保留在归档；[paper_pool](paper_pool/) 已恢复到根目录，用于复用已有全文及保存后续缓存。

运行产物保存在独立目录，原始机器预测、人工修订和参考裁决分别留痕。


## CLI 端到端与模块命令

先按研究问题修改 [Pi 任务模板](configs/templates/review_task.yaml) 中的逐来源检索式、纳排规则、codebook 和 synthesis 设置；需要固定协议统计时使用 [确定性任务模板](configs/templates/review_task.deterministic.yaml)，填写其 analysis 协议。以下使用同一任务和运行目录；已有目录默认按内容 hash 校验后续跑，不能仅凭文件存在判定成功。

```bash
# 1. 本地结构校验及执行计划；不调用服务、不创建运行目录
uv run metaagent workflow validate --task-config configs/templates/review_task.yaml --json
uv run metaagent workflow plan --task-config configs/templates/review_task.yaml --output-dir runs/example --json
# 2. 真正执行；默认 full（A＋B）。--limit 是显式有限检索
uv run metaagent workflow run --task-config configs/templates/review_task.yaml --output-dir runs/example --limit 100 --json
# 3. 检查真实 manifest 和产物 hash；修正问题后重跑上一条命令即可续跑
uv run metaagent workflow status --output-dir runs/example --json
```

`validate` 检查任务、review 协议、codebook 及所选后端依赖；确定性综合要求 analysis 协议，Pi 综合检查本地运行时和已声明的来源路径，不要求预填 AnalysisProtocol。`plan` 只校验所选阶段需要的内容。二者不会验证凭据、端点连通性、科研准确率或原综述协议恢复情况。`--json` 的执行结果在 stdout 是单个完整 JSON，诊断写入 stderr；工作流成功退出 0，partial／failed／stale 退出 1，Click 参数用法错误保留退出 2。失败 JSON 给出原因与后续操作；partial 应先核对待审证据和阶段记录，不能视作已完成。旧 `workflow status --run-dir ...` 是同一运行检查入口，`--profile ...` 仍可检查历史 profile 产物。

三个模块可分别运行，使用真实输入路径与协议文件：

```bash
uv run metaagent screening protocol-run --input records.jsonl --protocol review.yaml --out screened.jsonl
uv run metaagent coding extract --document-manifest documents.jsonl --codebook configs/mpox/codebooks/incubation_period.yaml --out runs/coding-only --ablation full
uv run metaagent synthesis agent --input estimates.xlsx --research-question '这些研究支持怎样的潜伏期估计？' \
  --method-source original_review_methods.pdf --primary-source primary_study.pdf \
  --max-turns 16 --max-tokens 256000 --max-executions 6 --output runs/synthesis-agent --json
# 确定性协议路径仍可单独调用
uv run metaagent synthesis run --input estimates.jsonl --protocol analysis.yaml --output runs/synthesis-only --json
```

`documents.jsonl` 每行含 `record_id`，再提供本地 `path` 或 PMID／DOI／公开 PDF URL；主文和 `supplements` 都支持仅声明身份，预印本应固定所需版本。相对路径以 manifest 所在目录解析。全量 Coding 默认 full（A＋B）；`--stage fetch` 仅获取 PDF 和准备 MinerU 缓存，不调用 A／B，也不输出估计。它使用标准 Rich 终端输出，没有 `--json` 参数：

```bash
cat > documents.jsonl <<'EOF'
{"record_id":"pmid:35994726","pmid":"35994726"}
EOF
uv run metaagent coding extract --document-manifest documents.jsonl \
  --codebook configs/mpox/codebooks/incubation_period.yaml \
  --stage fetch --out runs/pdf-fetch
```

`estimates.jsonl`／CSV／XLSX 是结构化估计表，不是题录。Pi 的 `--method-source` 声明原综述方法，`--primary-source` 声明原始研究材料，可重复传入；工作流会自动关联已获取的 primary evidence，身份或版本冲突仍保留待审。缺少原方法时必须明确探索性假设，不能猜作原法复现。确定性 `synthesis run` 可接受单个 analysis 对象或非空 analysis 列表；数值、区间及独立性须满足显式协议。完整字段、预算和源码入口见 [Synthesis 模块说明](metaagent/synthesis/README.md)。

```bash
# 从已有文档／估计接回同一执行器
uv run metaagent workflow run --task-config task.yaml --start-at coding --document-manifest documents.jsonl --output-dir runs/from-documents --json
uv run metaagent workflow run --task-config task.yaml --start-at pooling --estimates-input estimates.jsonl --output-dir runs/from-estimates --json
# 人工复核：编辑导出补丁的 changes/reviewer/reason 后 apply，再续跑原命令
uv run metaagent review export --run-dir runs/example --artifact coding_estimates --out review_patch.json
uv run metaagent review apply --run-dir runs/example --patch review_patch.json
# 显式消融，复用冻结上游；不改变普通运行的 full 主线
uv run metaagent workflow variants --task-config configs/templates/review_task.yaml --output-dir runs/variants --limit 100 --json
```

任务样例是新综述示例，不冒充原 22 篇 SR 的已恢复协议。确定性路径的多个分析使用 `analysis_protocols`；每个 analysis_id 独立选择、综合和出报告。Pi 可根据研究问题与方法来源规划多个分析，必须留下选择、转换、代码和执行核验记录。确定性统计方法及协议字段见 [Synthesis 说明](metaagent/synthesis/README.md)。支持固定、DL random、REML、描述中位数、共同风险二项合并及 logit 比例合并；计数推导、零事件、CI 方法、敏感性分析均须在协议中显式指定。

权威输出是 `coding_estimates.jsonl`、`analysis_selection.jsonl`、`synthesis_result.json`，另生成权重、森林图、敏感性与报告。全文、补充材料、解析器与配置均有 hash 和覆盖记录；复杂长表分块保留表头／脚注和原文坐标。只改分析协议会复用上游；改全文、补充材料或人工产物会使相应下游失效。

MinerU 缓存保留根目录 paper_pool，并按 PDF／解析器／配置指纹分版本，保留原 PDF、ZIP 与页表／图像资产。统一获取默认要求 strict 及出版物身份／版本核验；底层工具的 `compatible` 历史缓存模式仍保留用于明确的兼容操作，不能绕过主线 PDF 身份检查。

```bash
.venv/bin/python -m pytest tests -q
# 默认 full（A＋B）的服务冒烟：仅发送虚构 PDF，验证模型、MinerU 和 LangExtract 连接
.venv/bin/python tools/scripts/smoke_workflow.py --output runs/service_smoke
```

实际服务冒烟验证不代表科学提取准确率。原 22 篇 SR 的完整方法恢复、双人原文标注与参考裁决必须使用真实材料完成；不会自动把 draft 转为 verified，也不会恢复已停止的旧队列。


## 自部署节点验证

`configs/templates/review_task.selfhosted.yaml` 将四个阶段绑定到 `selfhosted` 服务，实际模型／地址／key 从根环境的 `SELFHOSTED_*` 解析。显式切换 provider 会隔离原服务的模型、地址和凭据；无需在任务文件中保存密钥。

```bash
.venv/bin/python tools/scripts/smoke_workflow.py \
  --provider selfhosted --variants full \
  --llm-report --output runs/selfhosted_smoke
```

指定 provider 后默认先检查所选节点。失败时保存真实 HTTP 状态、分类和时间，停止模型／MinerU 流程，不切换其他服务。结果同时保存最新别名和 `attempts/<uuid>/` 不可覆盖记录。`--dry-run` 可仅检查四阶段的实际绑定；`--model`、`--api-base` 可作显式覆盖。恢复后的运行记录会区分配置模型与响应模型，记录阶段／调用时间、token、A/B 调用与综合结果。

2026-11-03 的自部署节点验证结果为 `503 no healthy upstream`，尚不能测量该节点的模型响应速度或提取效果。详见验收记录中的本轮节点检查。


## pjlab 实测与 thinking 策略

```bash
.venv/bin/python tools/scripts/smoke_workflow.py \
  --provider pjlab --thinking disabled --max-tokens 8000 \
  --variants full --llm-report --output runs/pjlab_validation
```

`thinking` 可通过任务 llm 配置、`CODING_LLM_THINKING` 等模块变量或 provider 配置设为 enabled/disabled。本地编码配置已在原先未设置时添加 disabled：pjlab 实测发现复杂抽取请求会把输出预算全部耗在 reasoning 而没有正文；不能把空正文当作“没有估计”。烟测不再默认硬压到 2500 token，而是继承模块预算，仍支持显式上限。

Stage A 的 JSON/LangExtract 序列化分开，字段证据直接交接；空候选可通过 `coding.stage_a_empty_retries: 0..2` 做有界 A 内重扫（默认1），并记录全部调用。引文仅空白不同且能唯一定位时可恢复原文坐标，模型原句及修复标志保留；不会接受改数、改词或歧义匹配。

历史三分支冒烟曾显式传入 `--variants full without_a without_b`；这只用于消融诊断，不改变 full 主线。最新虚构文献实测 Full／without_a 正确得到 5 days 与区间 [4,6]；without_b 因点值与区间拆成两条候选而待审，不强行综合。该单例不证明阶段增益或科研准确率。运行、失败及配置快照都保存在独立 attempts 目录，详见 [验收记录](IMPLEMENTATION_STATUS.md)。

当前 pjlab 模型目录提供 `deepseek-v4.1-flash`，旧 `deepseek-v4-flash` 在本轮返回 503；已更新 `PJLAB_MODEL`，保留原凭据与旧失败收据。此标识是接口返回的模型别名，不独立证明底层权重。默认 LangExtract A＋B 使用显式 JSON 对象输出、24k 编码输出预算与有界重试；共享限额下按 1.5 次／分钟配置节流，耗时包括排队。显式使用 `--extraction-backend llm` 时，A 输出同样使用 `{"records": [...]}` 对象，并兼容旧数组响应；两个 A 后端均兼容 JSON 对象传输模式，无须删除 `.env.local` 的 `response_format: json_object` 覆盖。

历史开发验证（当前 Web 已暂停）：真实 Web Full 主线曾通过，PubMed 检索 PMID 32191173 → 筛选 → 核验过的 MinerU 缓存 → A＋B → 综合／报告，单研究结果 3.96 days、95% CI [3.53,4.39]，17 个产物可通过 HTTP 下载。默认工作区 `runs/webapp/` 中保留该开发验证任务，不代表完成了多研究系统综述。自动生成查询的 mpox 主线也已覆盖完整全文并到报告；原分析协议不接受 CrI，部分证据仍有歧义，正确保留 partial／待审。

此前 Web 开发检查点：**317 项 Python 测试、13 项前端测试、build／lint／wheel 构建通过**；开发时曾实际操作浏览器验证保存、运行、修订、续跑刷新、移动端及真实结果；这些记录不表示用户认可当前界面，也不替代本轮 CLI 与真实效果验收。旧 Queue 大响应假超时、旧模型 503 和格式失败均保留历史证据。见[真实 Web 验收](runs/webapp_acceptance/web_real_full/TESTER_REPORT.json)、[实现验收记录](IMPLEMENTATION_STATUS.md)。

此前 CLI 验证检查点：**420 项测试通过**；真实六阶段 CLI（指定 PMID 32191173、保留 LangExtract A＋B）约 156 秒完成，退出码 0，单研究结果 3.96 days、95% CI [3.53,4.39]，selected 1／review 0。另一个同源固定文档测试实际通过一次受锁定约束的 B 引文补丁，恢复原 OCR 拼写，未改数值。首轮失败、v2 范围改善和 v3 成功分别保留，见 [开发验证指南](evaluation/development_cli/README.md) 与 [实现验收记录](IMPLEMENTATION_STATUS.md)。这不是多研究 meta-analysis 或 22-SR 正式准确率；mpox 的冲突／范围待审未被强行转为成功，v3 未复测该案例。

此前确定性路径的真实 benchmark MP5 也已执行：原式全量 13 条→6 篇全文→4 篇 A＋B，33 条估计／3 条待审，30.5 分钟；最终 partial，因为缺明确 AnalysisProtocol，未生成合并值。该运行还暴露了旧 profile 筛选范围漂移、legacy 批次并发与请求并发不一致、筛选逐调用审计缺失，尚不能视为整个 benchmark 路径优化完成。发现的错误 PMID 缓存已在取文前保留隔离并换为核验原文。运行期间另有两处评估／评分文件同期修改，此结果绑定启动快照，420 项通过是此前检查点，不代替新评分代码验收；详见 [实现记录](IMPLEMENTATION_STATUS.md)。


## Pi 综合与 PDF 获取的本轮验收（2026-11-04）

最终完整软件回归 **578 项通过，129.03 秒**，249 个源码文件的前后哈希一致；见 [最终回归回执](runs/pi_synthesis_integration_20261104/release_regression_v2/receipt.json)。来源守卫独立验收 **111 项测试＋12 项检查通过**，安装环境解释器修复独立验收 **15 项测试＋9 项检查通过**；见 [来源守卫验收](runs/acquisition_integration_20261104/tester_explicit_pdf/TESTER_REPORT.json) 和 [安装环境验收](runs/pi_synthesis_integration_20261104/installed_interpreter_tester_screening/TESTER_REPORT.json)。身份冲突、版本缺失与旧错误缓存的原始失败及修复后证据均保留，见 [来源匹配验收](runs/acquisition_integration_20261104/tester_workflow_wrapper/v4/TESTER_REPORT.json)。

真实五篇贡献文献的原生 `coding extract --stage fetch` 已在断网条件下退出 0、约 3 秒完成：PDF 5／5、严格解析缓存 5／5，本次新增 MinerU 解析 0 次。这证明已有身份／版本绑定材料可复用，不表示重新下载或重新解析；命令和输出见 [五篇 PDF 获取回执](runs/benchmark_real_task_20261104/mp5_contribution_pdfs/root_cli_all_five_v2/INVOCATION.json)。

另以空缓存、仅 PMID **35994726** 实测自动获取：Europe PMC 官方元数据定位到 CDC 原始 PDF，核对身份后下载完成，耗时 **5.22 秒**；未手填 DOI、URL 或标题。下载 PDF 与根纸池原件 SHA 相同，随后在断网下用 **0.024 秒**命中共享 MinerU 严格解析缓存，新增 MinerU 调用 **0 次**，不能称作本次新解析；见 [冷启动下载回执](runs/acquisition_integration_20261104/root_cold_public_pdf/RESULT.json) 和 [下载到解析缓存的衔接回执](runs/acquisition_integration_20261104/root_cold_public_pdf/DOWNLOAD_TO_SHARED_PARSER_CACHE.json)。

Pi 的离线真实本地工具循环、沙箱执行／修复、重复核验和业务恢复已通过 [独立核心验收](runs/pi_synthesis_integration_20261104/core_tester_screening/TESTER_REPORT.json)。真实 MP5 综合仍未产生通过核验的科学合并值：DeepSeek 的多次尝试因共享网关 429 结束，Qwen 尝试因 503 结束，均保留 failed／result=null；见 [DeepSeek 尝试记录](runs/pi_synthesis_integration_20261104/live_mp5_v2/ATTEMPTS.json) 和 [Qwen 原始结果](runs/pi_synthesis_integration_20261104/live_mp5_qwen_v1/stdout.json)。服务失败、软件功能验收与科研复现是不同结论，不能据此宣称 MP5 科学复现成功。Web 继续暂停，未启动旧 22 篇研究队列。


### Quality tools and fixed-pool evaluation

Screening guards, source-bound coding completeness audits and Pi independent numerical
checks are explicitly loaded per module. The product can start from query generation;
the paper experiment can start from a frozen `raw_search` or explicitly augmented
`raw_pool` with `--synthesis-backend pi`. `evaluation diagnose --manifest ... --json`
reports observed stage attrition, original filter reasons, pending inputs and actual
usage without accessing labels or reference answers. See the
[optimization guide](docs/optimization_guide.md) for executable examples, artifacts,
cache behavior and the independently frozen reference specification required to score
a Pi result. Software verification does not establish improved scientific accuracy.

CLI 三模块独立运行、共享 task YAML、PDF／SI 缓存与端到端命令见 [CLI 模块使用说明](docs/CLI_MODULES.md)。

[方法稿与框架图](docs/METHODS.md) · [实现映射](docs/design/METHOD_IMPLEMENTATION_MAP.md)。
