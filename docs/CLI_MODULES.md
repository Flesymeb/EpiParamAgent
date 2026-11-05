# CLI：同一任务的三个模块与端到端运行

以一份 task YAML 保存研究问题、纳排协议、检索式、codebook、提取范围和综合设置。推荐复制 [Pi 新任务模板](../configs/templates/review_task.yaml)，修改后保存为 `my_review.yaml`；相对 codebook／方法文件路径以任务文件所在目录解析，请一并调整。凭据只在环境配置中填写，不写进 task、命令或方法文档。

模板目前为 Pi 设置 `max_turns: 16`、`max_tokens: 256000`、`max_executions: 6`、总时限 1200 秒；这是开发实测使用的有界预算，不保证任意大表、复杂模型或 MCMC 都能完成。`max_tokens` 是代理预算，模块环境中的单次输出上限是另一层限制。Pi 需要本地兼容版本、Node 和代码执行沙箱；先用本地校验／规划检查依赖。

## 共享任务配置的推荐入口

以下输入、输出路径是示例；命令不是已经完成的科学实验。先校验和规划，规划不调用模型、不下载、不创建输出目录：

```bash
uv run metaagent workflow validate --task-config my_review.yaml --json
uv run metaagent workflow plan --task-config my_review.yaml --output-dir runs/my-review --json
```

三个模块可以分别运行，仍使用同一 YAML 中的研究问题与协议：

```bash
# Screening：筛选固定书目池；不执行 Coding 或 Synthesis。
uv run metaagent screening task --task-config my_review.yaml \
  --input papers.jsonl --input-mode raw_search \
  --batch-mode multi --batch-size 8 --output-dir runs/my-screening --json

# Coding：已确认纳入的报告，从自动获取 PDF 开始，执行完整 A+B。
# 仍需全文资格判断时，去掉 --skip-fulltext-screening。
uv run metaagent workflow run --task-config my_review.yaml \
  --start-at fulltext_fetch --stop-after coding \
  --input-mode raw_pool --raw-input included_reports.jsonl \
  --skip-fulltext-screening --output-dir runs/my-coding --json

# Synthesis：读取自己的提取表，Pi 规划、编写并执行分析。
uv run metaagent workflow run --task-config my_review.yaml \
  --start-at pooling --stop-after pooling --estimates-input estimates.jsonl \
  --synthesis-backend pi --output-dir runs/my-synthesis --json

# 端到端：按 task.search 检索，然后筛选、获取全文、Coding A+B、综合。
uv run metaagent workflow run --task-config my_review.yaml \
  --output-dir runs/my-review --json
```

`--document-manifest` 仅用于 `--start-at coding` 或 `--start-at fulltext_screening`；`--start-at fulltext_fetch` 使用上例的 `--raw-input`。例如：

```bash
uv run metaagent workflow run --task-config my_review.yaml \
  --start-at coding --stop-after coding --document-manifest documents.jsonl \
  --output-dir runs/my-document-coding --json
```

完整主线默认保留 A 候选提取和 B 语义核查。LangExtract 是 A 内部后端；消融需显式选择 `without_a`／`without_b`，并使用各自输出目录。固定自然检索池的回放使用 `raw_search`；手工补充池使用 `raw_pool` 并记录补充来源，不能把后者宣称为自然检索召回。

## 更底层的独立命令与上下文

`coding extract` 不自动加载完整 task YAML。它的 `--task-context` 只接受 `research_question` 和 `review_protocol`，可从同一任务导出；综合独立入口的 `--review-context` 则传共享协议对象：

```bash
uv run python - <<'PY'
import json
from pathlib import Path
import yaml

task = yaml.safe_load(Path('my_review.yaml').read_text(encoding='utf-8'))
Path('coding_context.json').write_text(json.dumps({
    'research_question': task['research_question'],
    'review_protocol': task.get('review_protocol'),
}, ensure_ascii=False, indent=2), encoding='utf-8')
Path('review_protocol.json').write_text(json.dumps(
    task.get('review_protocol') or {}, ensure_ascii=False, indent=2
), encoding='utf-8')
PY

# 将 codebook 和 extraction-scope 替换为 my_review.yaml 中的同一设置。
uv run metaagent coding extract --document-manifest documents.jsonl \
  --codebook configs/mpox/codebooks/incubation_period.yaml \
  --task-context coding_context.json --extraction-scope '研究问题预先声明的提取范围' \
  --extraction-backend langextract --ablation full --out runs/coding-only

# 问题必须与 task 相同；方法文献和原始研究必须分开声明。
uv run metaagent synthesis agent --input runs/coding-only/coding_estimates.jsonl \
  --research-question '与 my_review.yaml 相同的研究问题' \
  --review-context review_protocol.json \
  --method-source original_review_methods.pdf --primary-source primary_study.pdf \
  --max-turns 16 --max-tokens 256000 --max-executions 6 \
  --total-timeout-s 1200 --exec-timeout-s 120 --output runs/synthesis-only --json
```

没有预声明提取范围时省略 `--extraction-scope`，不要为通过测试另造范围；它是额外的绑定约束，不替代研究协议。Coding 的问题、协议与范围实际进入 A（含 LangExtract）和 B。独立综合可先加 `--dry-run`；方法来源不足时应明确记录探索性假设或待审，不能把原始研究当作原综述方法证据。上述重复参数较多时，优先使用上一节的共享任务范围运行。

`documents.jsonl` 每行是一篇报告，可只给 PMID／DOI，也可声明本地 PDF 和补充材料。例如（路径相对清单文件解析）：

```json
{"record_id":"PMID:35994726","pmid":"35994726"}
{"record_id":"my-report","doi":"10.xxxx/example","path":"pdfs/main.pdf","supplements":[{"source_id":"supplement-1","path":"pdfs/supplement.pdf","role":"supplement"}]}
```

第二行 DOI 是格式示意，使用时替换为真实身份。预印本须声明确切版本或冻结日期，不能自动以最新版本／正式发表版替代。显式本地 PDF 与已绑定缓存字节不一致会拒绝，避免忽略用户输入。用户明确提供的 Markdown 可作为输入，但不等于已有原始 PDF。

## 新实验的 benchmark 版本与评分范围

截至 2026-11-04，当前工作区最新发布目录为 `dataset/benchmark_releases/20261104_P16_operational_optimized_v1`。CLI 默认仍保留旧基线 `20261104_experiment_ready_v1`，**新实验必须显式传 `--dataset-root` 并使用独立输出目录／run-id**；本页没有更改全局默认。既有工程验收、测试数量和历史结果仍绑定各自原始版本，不能因命令路径更新而改标为新版效果。

最新包是 `20261104_temporal_raw_v4` 之上的 P16 操作性变体，不是原综述全部数据库与历史检索的忠实复现。P16 自然 `raw_search` 为 790 条候选，人工补入 16 条后的 `raw_pool` 为 806 条；这些是筛选候选／报告身份，不是已认证的独立研究数。自然池覆盖 GT **27/43**，v4 为 **33/43**；补齐池覆盖 **43/43** 是构造覆盖，不能作为自然检索召回。两种输入须分开运行与计分，unknown 不当作负例，已知标签上的 precision／F1 需注明条件。

以下是本地计划命令，`--plan` 不产生模型预测；去掉该选项才会执行实际实验：

```bash
uv run metaagent evaluation benchmark \
  --dataset-root dataset/benchmark_releases/20261104_P16_operational_optimized_v1 \
  --run-id P16-natural-new --profile P16 --mode screening --input-mode raw_search \
  --model qwen3.8-27b-fp8 --api-base https://token.pjlab.org.cn/v1 \
  --output-dir runs/my-latest-benchmark --plan --json

uv run metaagent evaluation benchmark \
  --dataset-root dataset/benchmark_releases/20261104_P16_operational_optimized_v1 \
  --run-id P16-augmented-new --profile P16 --mode screening --input-mode raw_pool \
  --model qwen3.8-27b-fp8 --api-base https://token.pjlab.org.cn/v1 \
  --output-dir runs/my-latest-benchmark --plan --json
```

Coding 与固定综合输入可按内容哈希复用，但新版身份映射须重新核对，不能直接套用旧行号或 opaque-ID 映射。四项新版计划的既有回执见 [版本核对](../runs/latest_benchmark_alignment_20261104/version_audit/README.md)，其中独立 benchmark 的 synthesis 是**确定性 source-oracle 检查，不是 Pi**；Pi 仍使用前文的 `synthesis agent` 或 `workflow`。计划通过也不表示正式 scoring policy 已批准全部任务或所有端到端效果。

## 元数据补齐与 PDF 预取

下列入口针对声明的 benchmark 输入创建派生产物，不修改冻结输入或参考答案；不调用 LLM。PDF 预取不批量触发 MinerU：

```bash
uv run metaagent literature enrich \
  --dataset-root dataset/benchmark_releases/20261104_P16_operational_optimized_v1 \
  --out runs/my-enriched-p16-operational-v1 --online

uv run metaagent coding prefetch \
  --dataset-root dataset/benchmark_releases/20261104_P16_operational_optimized_v1 \
  --out runs/my-pdf-prefetch-p16-operational-v1 --allow-network

# 同目录恢复；需要重新尝试失败项时显式添加该标志。
uv run metaagent coding prefetch \
  --dataset-root dataset/benchmark_releases/20261104_P16_operational_optimized_v1 \
  --out runs/my-pdf-prefetch-p16-operational-v1 --allow-network --retry-failed
```

- 元数据：`enriched/profiles/<profile>/raw_search.jsonl`、`raw_pool.jsonl` 保留原身份与补齐来源；`model_inputs/` 中为只含书目信息的 opaque-ID 视图；`MODEL_IDENTITY_MAP.jsonl` 供外部评分回映；覆盖见 `COVERAGE_REPORT.json`。完整官方题名与原题名分别保留，书目信息不能代替全文科学证据。
- PDF：`document_manifests/<profile>.jsonl` 可交给 `coding extract --document-manifest` 或工作流从 coding 开始；它只包含 PDF-ready 条目。全分母、失败和版本待确认项见 `COVERAGE.json`、`MEMBERSHIP_RESULTS.json`，不能以 ready 子集冒充全任务。旧基线及新版保留的 active coding 输入范围为 20 profiles、600 报告条目，去重身份簇不是独立研究数。
- 数据恢复可独立于提取进行。附件的下载／缓存不保证已经加入某次运行的文档清单；要用于提取，应显式关联到主文的 `supplements`，并检查实际 source manifest。

## 缓存、输出与效果边界

目前本地模块默认统一为 `qwen3.8-27b-fp8`，关闭 thinking 并传 Qwen 对应模板参数；task 或命令显式覆盖可能改变实际模型，应以运行审计为准。API 凭据仍从各模块环境读取。Query 的配置独立，不由“三阶段同模型”推断。

正常获取顺序是校验根目录 `paper_pool` 的身份／版本绑定，缺失时尝试合法公开下载，再由 MinerU 优先解析或复用 PDF SHA 与解析器指纹匹配的严格缓存。PDF／SI 已缓存与解析已完成是两个状态；下载失败、来源冲突和未知版本必须保留，不能以摘要充全文。正文和补充材料都可缓存，但并非所有来源都能自动公开获取。

工作流以 `workflow_manifest.json` 的当前 attempt 和 artifact 路径为准；`workflow status --output-dir ... --json` 可检查状态。Coding 的权威结构化输出为 `coding_estimates.jsonl`，Excel 是审核视图；同时检查 `source_manifest.jsonl`、证据、coverage、调用日志和失败诊断。重新运行会校验输入与配置指纹；不要靠任意“最新文件”串接历史结果，也不要将 partial 当 complete。

软件回归、模型能返回 JSON、HTTP 200 与科学效果分别验收。目前元数据、全文覆盖与字段提取仍有缺口，MCMC 等方法／计算描述仍有漏提记录；不能宣称所有 benchmark 已完整复现。综合应保留参数、统计量、人群／组别、时期、单位、区间类型与水平、方法及依赖关系，并只发布经过实际代码执行核验的数值。来源未报告的字段不猜补。

旧 `synthesis run`（[确定性任务模板](../configs/templates/review_task.deterministic.yaml)）是显式协议计算；`benchmark --mode synthesis` 的 source-oracle 检查也应单独报告，均不能替代 Pi 的规划／工具／执行验收。原 SR 复现与探索性分析必须分开标明。
