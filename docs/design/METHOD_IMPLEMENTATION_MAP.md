# 方法、代码与证据映射

核对日期：2026-11-05。配套[方法稿](../METHODS.md)与[图源](../figures/methods/README.md)。本次未运行模型、重算效果或改动冻结数据；以下状态来自当前代码和已有回执。

## 写作与图示口径

主线是问题与检索前置、Screening、Coding、Synthesis。运行器有六阶段：`retrieval`、`screening`、`fulltext_fetch`、`fulltext_screening`、`coding`、`pooling`。三个研究模块不等于只有三个执行阶段。

Coding A/B 是模块内部机制，LangExtract 放在 A 内。主配置是 `full`，移除 A、移除 B 是显式消融。Synthesis 画成 Pi 工具循环，兼容的确定性入口不能替代 Pi 实验。Benchmark 单独成图，参考层并列，不预设所有 GT 集合严格嵌套。

## 当前 benchmark 快照

| 项目 | 当前含义 |
| --- | --- |
| 新 22-task 视图 | `dataset/benchmark_releases/20261105_all22_search_received_cap_v1` |
| 自然候选 | 38,741 条 `raw_search` |
| 人工补充 | 497 条，独立保留来源 |
| 增强候选池 | 39,238 条 `raw_pool` |
| 历史完整 SR 正例 | 1,132 条任务—报告关系，不是全局唯一且全部身份已认证的独立研究数 |
| 构建性质 | 操作性重建，原数据库完整复现和历史索引尚未认证 |
| P7/P8 参数试点 | 与完整 SR 范围分开，不能混用参数阳性和全 SR 标签 |
| CLI 默认 | 仍为 `20261104_experiment_ready_v1`，本次未切换；新运行需显式 `--dataset-root` |
| 已有 Screening/batch 小试验 | 绑定 `20261104_P16_operational_optimized_v1`，不能按新池数量或名单改述 |

计数是任务内报告条目，同一报告可跨任务重复。上表依读取时的 `profiles.csv` 和 `earlier_bound_counts.csv`，不使用继承目录旧计数。该视图取原文检索/更新与期刊 first Received 的较早有证据界限；后者并非已证全球首次投稿日期，缺失不能用 Accepted 等猜补。

读取快照为 **2026-11-05 02:03:39 +08:00**。整理期间另一工作线持续更新目录，早先 38,809／496／39,305 已被替换。本页不保证后续目录不变；实际实验仍以启动时 manifest 及输入为准。本次读取前后 manifest SHA 一致，绑定如下：

```text
manifest.json             457519564d5500f4dfe779323d04ebdcfa16da6e5bbfb88f9583024f00a7f42b
profiles.csv              5f14b8f9955dbd11b172976f5e30ef08186fec0c8924ba5112eb00eb9c6d1603
earlier_bound_counts.csv  78fdeba2987e772d6ce4d5e645bb950f3cb969d8cb1164f123c6f2e8862ec2ef
```

当前 gate 允许 15 项报告已知历史标签 P/R/F1；MP12、MP6、MP8、P12、P13、P15 六项限已知阳性恢复；MP9 缺操作性自然池，主执行或比较受阻。Gate 通过不等于全池有独立科学资格标签。`conditional_known_label_metrics`、`reference_label_coverage` 和 `full_pool_metrics_available` 应一起解释。

保留的 Coding 参考为 20 项、600 个任务—报告、950 条来源估计，原研究核对字段子集与综述转录参考分开。配套的确定性 source-oracle 综合任务是 MP11/MP12，不是 22 项 Pi 或端到端准确率。PDF/SI 和原文核查覆盖依来源清单与回执，不能由参考总数推断全部已下载解析。

## 方法到实现

| 要素 | 当前实现 | 表述边界 |
| --- | --- | --- |
| 共享任务 | [`workflow_task.py`](../../metaagent/workflow_task.py)、[`review_task.yaml`](../../configs/templates/review_task.yaml) | 低层独立 CLI 仍需显式传上下文 |
| 编排和恢复 | [`workflow_runner.py`](../../metaagent/workflow_runner.py) | 六阶段、输入配置绑定、manifest；能力不等于全部真实任务通过 |
| 基准重建 | [`build_sr_reconstruction.py`](../../tools/benchmark_v2/build_sr_reconstruction.py)、[`build_earlier_bound_release.py`](../../tools/benchmark_v2/build_earlier_bound_release.py) | 自然、人工、路由日期与版本分别保存 |
| 元数据投影 | [`metadata_completion.py`](../../metaagent/screening/metadata_completion.py)、[`context.py`](../../metaagent/screening/context.py) | 白名单书目字段，不是完备的自由文本答案检测 |
| 五维筛选 | [`engine.py`](../../metaagent/screening/engine.py)、[`models.py`](../../metaagent/screening/models.py) | 当前 22-task 没有 typed protocol，prose 协议不等于逻辑 schema |
| 结构化资格 | [`protocol.py`](../../metaagent/screening/protocol.py) | 应用另一路径，引文保证不能追认到五维实验 |
| PDF/SI 取得 | [`acquisition.py`](../../metaagent/acquisition.py)、[`documents.py`](../../metaagent/documents.py) | 共享池、身份/版本、公开来源；不保证自动发现全部 SI |
| MinerU 缓存 | [`cache.py`](../../tools/mineru/cache.py) | strict 按 PDF SHA 与解析指纹绑定，compatible helper 仍需披露实际 policy |
| Coding A/B | [`stages.py`](../../metaagent/coding/stages.py)、[`extraction.py`](../../metaagent/coding/pipeline/extraction.py) | 默认 A+B，遍历来源不等于找全所有有效估计 |
| LangExtract | [`langextract_backend.py`](../../metaagent/coding/pipeline/langextract_backend.py) | A 的后端，拼接文本与最终来源的坐标不能混用 |
| B 结构和证据 | [`response_contracts.py`](../../metaagent/coding/response_contracts.py)、[`evidence.py`](../../metaagent/coding/evidence.py) | records/dispositions 及引文定位，不是科学语义 oracle |
| Coding 上下文 | [`prompt_context.py`](../../metaagent/coding/prompt_context.py)、[`context_fields.py`](../../metaagent/coding/schema/context_fields.py) | 问题、协议和范围进入 A/B，适用字段仍依 codebook |
| 覆盖线索 | [`completeness.py`](../../metaagent/coding/completeness.py) | 词句/表格线索不是人审效应总分母 |
| Pi 分析 | [`pi_agent.py`](../../metaagent/synthesis/pi_agent.py)、[`pi_tools.py`](../../metaagent/synthesis/pi_tools.py)、[`pi_agent.md`](../../metaagent/prompts/synthesis/pi_agent.md) | 查询、save_plan、write_code、run_code、finalize，不整体拼大表 |
| 执行核验 | [`execution.py`](../../metaagent/synthesis/execution.py)、[`statistical_verification.py`](../../metaagent/synthesis/statistical_verification.py) | 沙箱及重复运行，独立复算仅覆盖声明方法 |
| 评分 | [`release.py`](../../metaagent/benchmark/release.py)、[`benchmark_metrics.py`](../../metaagent/evaluation/benchmark_metrics.py) | 历史成员、资格 sidecar、参数分支分开，unknown 非负例 |

## Prompt 与接口合同

### 五维分类方式

默认由模型给出五维 0–4 分、各维依据及 S/P/U 标签。五维评分说明用于解释相关性，模型结合研究问题和纳排标准确定标签。程序检查返回完整性与格式，不计算人为加权总分，也不用分数阈值覆盖模型标签。缺少或无效的返回请求纠正，仍不合格时记录失败。

`overall_score` 列保留兼容格式，默认不生成总分；报告不按加权总分排序。显式 `--no-prefer-llm-tier` 保留旧阈值路径，用于复核历史行为。文献材料、来源或资格待审状态另外记录，原始模型标签保留在 `llm_tier`。

本次修改不重算历史实验。已有结果仍对应各自记录的代码、提示词和数据版本。

### 各阶段输入输出

| 阶段 | 共享问题和协议之外的重点 | 输出及核查 |
| --- | --- | --- |
| Screening | 可用完整元数据、纳排细则、信息不足策略 | 维度/等级或结构化条件；单篇/批量及返回覆盖 |
| Coding A | codebook、范围、来源块、参数定义 | 多估计候选和引文，不代做分析贡献选择 |
| Coding B | 相同范围、原文、全部候选身份 | 归并核查补漏、records/dispositions、有界纠正 |
| Synthesis | 完整表、方法及 primary 来源、统一 estimand | 先计划后代码执行，选数、转换、依赖和敏感性 |

`docs/design/prompt_v2/` 是设计模板，不能据文档存在认定全部被运行时加载。实际提示以代码读取的资源、字段规则及调用回执为准。一次逻辑纠正可能包含传输重试，不能写成每文恰好两次模型请求。

独立 Coding 的 `--task-context` 接受问题与 protocol 精简对象，不是完整 task YAML。`--document-manifest` 用于从 Coding 或全文筛选开始，全文获取使用 `--raw-input`；综合输入表使用 `--estimates-input`。推荐通过共享 task 的 workflow 范围运行，减少重复传参漂移。

## 论文陈述与实验状态

旧 v4 三列配色和开放机制区保留。新主图增加全文缓存/取得/解析、模块输入、A/B 职责及 Pi 循环，Benchmark 另图。版本数字放本页，不固定在框架示意图。

方法稿第 8 节是评价与消融的组织方式，不表示这些实验全部完成。正式实验需冻结版本、问题和方法材料，审计报告身份及来源覆盖，分别运行模块和自然检索端到端；再做 A/B 配对消融，以及受完整返回约束的 batch 质量、成本和耗时分析。已有小试验不能支持“batch 越大越可信”。

严格答案屏蔽需在模型执行前冻结带原件定位的方法片段。当前 Pi 可读取原综述全篇和附件，标签路径拒绝及提示约束不是完整答案过滤。方法源 PDF 暂存时使用本地文本提取，不能称所有进入 Pi 的 PDF 都重新执行远程 MinerU。

精确引文、代码执行成功、重复运行一致、独立数值复算和原 SR 科学复现是不同证据层级，应按实际达到的层级报告。
