# 五维筛选与提示词审查

审查日期：2026-11-05。对象为当前五维提示词、领域配置、筛选流程和已有错误案例。本次给出调整方案与候选提示词，不替换运行配置，也不执行新的模型实验。

## 结论

保留五维、0–4 分及模型输出 S/P/U 的方式。当前主要问题是通用规则与任务纳排标准存在冲突，评分说明混用了相关性、信息是否充分和研究质量。先修正规则与任务的对应关系，再比较实际效果。

## 五维如何调整

| 维度 | 审查结果 | 建议 |
| --- | --- | --- |
| 疾病 | 保留 | 判断是否研究目标疾病；相关疾病、共同感染等按任务条件处理。 |
| 人群 | 保留 | 根据任务规定的人群、病例定义和组别判断；观察数据及对这些数据的模型分析均按任务要求处理。 |
| 地区与场景 | 优先重写 | 按任务限定判断，区分感染或暴露地点、病例来源、入组地点和采样地点。任务不限地区时，不默认偏好流行地区或排斥境外病例。 |
| 研究类型与数据来源 | 建议替换“原创证据”的文字说明 | 判断病例报告、队列、监测、原始模型分析或二次研究是否符合任务。文献类型、样本量和研究质量分别理解。 |
| 目标参数 | 保留，按阶段说明 | 判断参数定义及其在文中的作用，区分研究结果、引用他人结果和模型固定输入。题摘阶段允许信息待确认，全文阶段按任务允许的数据形式判断。 |

第四维调整时可保留现有 `original_evidence` 字段，避免改变数据交换格式。语言和日期等要求在任务纳排标准中明确列出，由模型在最终分类前核对，无须增加评分维度。

## 优先修改的提示词问题

### 地区规则默认压低输入病例

[题摘模板](../../metaagent/prompts/5d/screening_system_title_abstract.md:20)要求非流行地区的输入病例得低分。具体任务却可能允许与目标地区有关的境外病例。应改为依据任务的地区条件判断，并在理由中说明相关地点指什么。

### 缺少参数信息与参数不符合混在一起

[题摘模板](../../metaagent/prompts/5d/screening_system_title_abstract.md:43)先要求未直接报告目标参数时倾向低分，后面又允许摘要省略相关结果时保留 P。评分说明中的“absent”也可能被理解为摘要没写。

应分别描述已支持、信息不足和明确不符合。信息不足可对应 2 分，明确不符合对应 0 分；模型必须根据实际材料评分，程序不填默认分。S/P/U 继续由模型结合五维依据及纳排标准判断。

### 文献类型与原始研究证据的关系不清

[用户模板](../../metaagent/prompts/5d/screening_user_title_abstract.md:19)要求把出版类型和 MeSH 当作证据评分的强信号，而系统模板又要求检查原文内容。出版类型可以提示研究类型，MeSH 可以提示主题，但二者不能直接证明存在原始数据。

建议统一为：任务标准决定允许的研究类型，文献内容支持具体判断，索引信息作为辅助。病例报告和通信是否保留取决于任务，而非固定低分；原始研究属性也不代表研究质量高。

### 全文模板对可用数据形式的要求过窄

[可能相关文献的全文模板](../../metaagent/prompts/5d/screening_system_possible_full_text_llm.md:19)要求文献自身必须报告、估计或综合目标参数，并排斥仅提供可计算原始数据的情况。

这个要求应由任务决定。例如，任务允许从事件数及分母计算比例时，可以保留相应数据；任务仅允许已报告的参数估计时，则按该条件判断。涉及重新拟合分布或其他模型时，还需有任务允许的方法与数据。筛选阶段判断是否符合条件，参数提取及综合分析阶段处理具体数值。

### 完整综述范围与某项分析的范围需要统一

部分任务筛选整篇原综述的纳入文献，同时参数提取只关注其中一项分析。提示词应以当前筛选任务声明的范围为准，覆盖其允许的全部参数及证据类型。

领域配置中“为恢复原综述名单而保留某类旧文献”的例外，应转换为有协议依据的纳排说明。原名单与原协议冲突时，记录标签问题；不要根据已知成员关系修改科学资格标准。

### 语言、日期等明确要求容易被遗漏

已有旧版试验中，P14 的 PMID 32171192 语言为 `chi`，任务要求英文，模型仍输出 S。该案例说明应检查所有已声明条件，而非只解释五维相关性。它属于旧运行，不能用来计算本次新提示词效果。

建议将纳排条件放在提示词开头逐条列出，总体理由说明支持分类的关键条件，以及明确违反或尚不清楚的条件。保留模型给标签的设计，不增加总分或阈值。

### 通用规则重复且混入特定疾病例外

当前题摘系统模板有 183 行，另叠加领域说明、工具说明和输出格式。建议按研究问题与纳排条件、当前筛选阶段、五维定义、相关参数说明、输出要求的顺序组织。疾病和参数例外放在对应领域文件中，避免每篇都读取无关规则。

## 候选提示词骨架

以下骨架用于下一轮改写，尚未接入运行时。各维定义及领域说明由任务加载，现有 JSON 字段保持不变。

```text
Task: assess this record against the supplied review question and eligibility criteria.

Research question: {research_question}
Eligibility criteria: {eligibility_criteria}
Screening stage: {screening_stage}
Applicable parameter guidance: {parameter_guidance}

Assess the five defined dimensions using only the supplied material.
For each dimension, return a 0–4 score and a short reason. Cite a supporting
source phrase when available; identify missing information when it prevents judgment.

Apply the task's requirements for population, study design, geography, dates,
language and eligible data. Distinguish the study's own parameter results from
background citations and fixed model inputs. Accept raw data suitable for a
declared calculation only when the task permits that data form.

Assign one tier from the five assessments, their evidence and the eligibility criteria:
S: available evidence clearly supports eligibility at this screening stage.
P: eligibility remains plausible, but a required detail or source is unresolved.
U: available evidence supports exclusion under a declared criterion.

At title/abstract screening, omitted information remains unresolved.
At full-text screening, assess the supplied main text and supplements; identify
missing material explicitly.

Give the main reason for the tier and the decisive or unresolved criteria in
overall_justification. Do not calculate a weighted total or derive a tier from
score cutoffs. Return the application's JSON schema, including all five assessments
and an explicit S/P/U tier, for every supplied record ID.
```

这里的四个占位符是候选材料结构，并非已新增的运行参数。其中研究问题和阶段已存在；纳排条件及参数说明应优先复用现有任务与配置。

## 是否增加 skills

Skills 在这里指按任务加载的操作说明和方法资料。建议先整理三类短文件：

| 资料 | 用途 | 现有可复用位置 |
| --- | --- | --- |
| 纳排判断说明 | 区分缺信息与明确排除，解释地区、时间、语言和研究设计条件 | [`guide.md`](../../metaagent/screening/guide.md)、任务纳排标准 |
| 流行病学参数说明 | 区分潜伏期、序列间隔、代际间隔，R0、Rt、Re，病死比例和感染死亡比例，以及参数在文中的作用 | `parameter_scoring_note`、领域编码表 |
| 统计综合方法说明 | 指导 Pi 选择估计、处理共享研究对象、转换单位和不确定性、执行敏感性分析 | 综合提示词、声明的方法材料及已有统计工具 |

筛选继续使用固定输入和短提示词，全文获取交给已有获取阶段。参数提取在 A/B 内加载相应字段及证据说明。Pi 可按分析问题读取相关统计资料，再调用现有工具执行。

当前筛选没有通用 skills 加载器。Pi 的[启动命令](../../metaagent/synthesis/pi_runtime.py:538)明确使用 `--no-skills`，只开放项目定义的 `epi_tool`。因此放入一个 `SKILL.md` 不会自动生效。若后续接入，应明确每阶段加载哪些项目内文件，并记录文件版本；可先复用现有领域配置与方法材料，无须立即改变 Pi 的启动方式。

## 如何验证调整

先用已有误判和边界案例形成开发样本，覆盖输入病例、文献类型与内容冲突、摘要缺失、语言不符、参数作为固定输入，以及仅提供允许计算的原始数据等情况。

在相同模型、候选、批量大小及并发度下比较当前提示词与候选提示词，报告有效返回比例、已知阳性召回和有明确标签范围的精确率、F1。缺少科学资格标签的记录单列，历史名单一致性另行解释。开发样本用于调整规则，其他任务用于检查泛化表现。

0–4 分的稳定性另作观察。当前没有独立的五维人工评分参考，不能以模型分数更整齐或批内差异更明显证明筛选更准确。

## 方法依据

题摘阶段先筛除明显无关文献，保留可能相关者取得全文；全文信息仍不足时保留待判断状态。这与 [Cochrane Handbook 第 4 章](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04)的分阶段选择流程一致。该手册以干预综述为主，本审查采用其分阶段选择原则，具体参数任务仍依据各自纳排标准。

[NHMRC 的文献选择说明](https://www.nhmrc.gov.au/guidelinesforguidelines/develop/selecting-studies-and-data-extraction)建议先用样本文献试行筛选标准。以上五维定义和 skills 组织方式属于本项目的设计建议，其效果需通过固定输入的比较实验验证。
