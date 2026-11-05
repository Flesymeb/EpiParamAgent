# Datasets

当前基准与来源证据保留在 dataset；旧工作区已归档，仅4个兼容软链仍保留原入口。

**Raw pool 后续复核提示：** 已发现旧池中有日期上界、晚入库记录、未来预印本版本及ICU子串误匹配问题。下文74693等数量属于旧实验快照；代码可运行不等于历史候选池复现已验收。请先看[历史检索范围复核与独立修订](../docs/audits/20261104_raw_pool_temporal/REPORT.zh-CN.md)，再确定screening实验输入。

**当前可执行冻结版是 [experiment_ready_v1](benchmark_releases/20261104_experiment_ready_v1/README.md)。** [中文快速开始](../docs/audits/20261104_experiment_ready/START_HERE.zh-CN.md)给出三模块实际命令与可用范围；[独立验收](../docs/audits/20261104_experiment_ready/tester_final_review.md)已通过。数据可用于范围明确的模块实验，不声称22篇所有模块全部就绪或原数据库完整复现。

新包已修P6森林图成员、P10 SI/GT混入、P15九条续行及其源值/方法继承。Coding为20任务、600个任务—报告、950条来源估计；建议先跑有本地全文的364报告/622估计子集。236份内容去重MD已随包固定。Synthesis仅MP11/MP12两个真实输入/协议/oracle配套任务已计算验证；P5/MP8保screening和辅助，未拿无原CI或未核派生链充当主数值gold。Primary准确率另仅使用15条估计的70个已列核查字段，SR参考恢复率独立计分。

Screening主池74693条、确认GT1132条保持不变；主21任务可执行，MP9需显式fallback。主15项/fallback16项可在已知历史标签范围评Precision/F1；其余6项只评已知阳性召回。池子来自公开操作性重建和人工补齐，不是作者全部历史导出。P4/P6/P16与原文检索数量差异尤其明显，不能拿本池工作量直接声称复现原SR人工成本，见[Raw pool说明及22项对照](../docs/audits/20261104_experiment_ready/RAW_POOL_SCOPE.md)。原provider/操作性主视图与公开代理fallback分开，后者总池147567条。

旧675是分析分支候选，按字节保legacy，不是22个单一参考值的精确输入总数；[原文审计](../docs/audits/20261104_reference_value_membership/SCIENTIFIC_AUDIT.md)解释其问题。新source保原1517记录，加P6 forest57与P15续行9，共1583条；其中950条进入当前coding源参考。总体/亚组/敏感性/未闭合目标分别存catalog，未核旧3.55/3.50不升为gold。扩展参照方向见[22项总体/分组候选](../docs/audits/20261104_reference_value_membership/OVERALL_REFERENCE_CANDIDATES.md)；候选有出处不等于已具备可执行综合协议。

上一GT范围草稿的684条已由原表/代码/输入核对修订为675条分析成员；下文旧1129条是旧整篇SR来源草稿，不能直接替代本轮1132条已确认screening GT。所有旧版本保留，没有就地覆盖。

|位置|用途与状态|
|---|---|
|[20261105 screening GT 已核更正候选](benchmark_releases/20261105_screening_gt_corrected_candidate_v1/README.md)|将 P12 的1条及 MP12 的2条历史分析来源补入，关联 P17 两个版本；参数GT 838、候选池39238。仅 screening，仍有名单与参数口径缺口，尚未作为 benchmark_v0 冻结；原包不变|
|[20261105 双口径 GT 重建版](benchmark_releases/20261105_dual_GT_conservative_v2/README.md)|22 项保留目标参数和整篇 SR 两个视图，候选池相同；名单缺口、未知标签、负例不足和人工补入按任务披露。仅限注明范围的 screening，详见[中文说明](../docs/audits/20261105_dual_gt_scope/REPORT.zh-CN.md)，CLI 默认数据根未切换|
|[检索与首次投稿较早上界：22项完整SR视图](benchmark_releases/20261105_all22_search_received_cap_v1/README.md)|按路线过滤可证晚于上界的自然候选并补齐GT；main池39238、完整SR GT1132。MP6/MP7首次收稿未确认，部分其他日期有冲突或精度不足；不是22项参数GT|
|[同上界：P7/P8参数screening试点](benchmark_releases/20261105_P7_P8_parameter_earlier_bound_v1/README.md)|保留P7 R0 152、P8 R0 46；仅两项参数screening，其他20项尚未完成参数GT。未知时间非GT不当确定负例|
|[P7 原文共享条件严格视图](benchmark_releases/20261105_P7_strict_source_rule_v1/README.md)|依原文题摘、人类及时间条件重检；不含用户排除的arXiv或未列代理；12268条，152 GT含75人工补入。当前索引近似、原文其他库未完成，详见[P7审计](../docs/audits/20261105_P7_query_fidelity/REPORT.zh-CN.md)|
|[P7 不含arXiv视图](benchmark_releases/20261105_P7_without_arxiv_v1/README.md)|用户指定范围下18331条，保留较宽LitCovid路线；原文实际使用arXiv，排除路线为有意偏离，历史版本保留|
|[P7/P8 参数screening试点](benchmark_releases/20261105_P7_P8_parameter_screening_pilot_v3/README.md)|P7 R0 152个来源锚点、P8 R0 46个；定性/定量、历史分支与科学相关性分层。仅两项screening；其他20项尚未按新口径完成，CLI默认未切换|
|[20261104 Screening GT修订](benchmark_releases/20261104_GT_reconciled_v1/README.md)|P11补回Amato、保留Yu冲突为unknown；P13合并重复报告。GT合计仍1132但名单改变；独立新版本，不代表全部原文名单已闭合|
|[20261104 P16操作性优化](benchmark_releases/20261104_P16_operational_optimized_v1/README.md)|只调整P16：原文指定4个可处理来源，790自然候选+16人工补入；43 GT全在池内。另3个原库未执行，非原式历史复现；[中文说明](../docs/audits/20261104_raw_pool_temporal/P16_OPTIMIZED_POOL.zh-CN.md)|
|[20261104 偏大池P13修订v4](benchmark_releases/20261104_temporal_raw_v4/README.md)|P13按原明确检索日约束CRDT；主池59685、GT1132。P16/P4差距尚未闭合；CLI默认未切换，详情见[修订记录](../docs/audits/20261104_raw_pool_temporal/OVERSIZED_REPAIR_RESULT.md)|
|[20261104历史范围修订v3](benchmark_releases/20261104_temporal_raw_v3/README.md)|独立raw修订：4项日期/词元/版本问题；主池59767、GT1132；其余18项未新增忠实性认证，P16差距仍未闭合；CLI默认未切换|
|[20261104 可执行实验版](benchmark_releases/20261104_experiment_ready_v1/README.md)|当前默认：screening主21/fallback22、coding20（600报告/950源估计）、localMD364/622、controlled synthesis2；不开放正式e2e评分|
|[20261104 Screening/分析分层版](benchmark_releases/20261104_screening_eligibility_v1/README.md)|保留上一分层快照：筛选池/1132GT沿用，旧675转legacy；其coding映射问题已在新实验版修订；原数据库导出缺口仍在|
|[20261104 SR数据重建v1](benchmark_releases/20261104_sr_reconstruction_v1/README.md)|不可变分析参考及历史目标分析选择诊断：原主池73566/分析GT675；不是新版完整SR screening的GT|
|[20261104目标参数分析GT草稿v2](benchmark_releases/20261104_target_analysis_v2/README_TARGET_ANALYSIS.md)|保留上一范围修正草稿：684报告、主池5036、coding候选770；已由新数据重建包接替，不用于本轮新评估|
|[benchmark_v1/](benchmark_v1/README.md)|不可变历史版本：22个 COVID-19/mpox 任务的原始池、标签、查询及综述参考值；保留用于追溯，不就地修订|
|[benchmark_v2/](benchmark_v2/)|保留旧strict-original草稿：整篇SR最终纳入来源与原库/原式检索分别记录；当前数据请使用上方可执行实验版|
|[20261104优先修订版](benchmark_releases/20261104_priority_revision_v1/README_PRIORITY_REVISION.md)|保留原数据，P5/MP8退出主coding和综合评分；20个设计候选尚无完整核验参考包可正式评分，IFR替换待完成|
|[上一轮扩展版本备份](../archive/20261103_160112_pre_refactor/superseded/benchmark_v2_expanded_before_original_alignment_20261103/)|保留切换前完整full-review版本及旧导出，未删除|
|[benchmark_sources/full_review_sources_20261103/](benchmark_sources/full_review_sources_20261103/)|原综述来源成员台账、原表定位及各任务完整度/身份待审状态|
|[benchmark_sources/original_aligned_sources_20261103/](benchmark_sources/original_aligned_sources_20261103/)|新版最终纳入阶段对齐台账，保留旧source ID、未决与非最终来源|
|[benchmark_sources/ground_truth_coverage_audit_20261103/](benchmark_sources/ground_truth_coverage_audit_20261103/)|纳入来源/版本及逐研究证据审计缓存，原位于 output/|
|[benchmark_sources/query_strategy_audit_20261103/](benchmark_sources/query_strategy_audit_20261103/)|原综述检索策略与附件缓存，原位于 output/；供离线重建|

来源成员事实 `included_in_source_review`、完整综述资格、特定分析的 `eligible_for_target` 和最终 `contributes_to_estimate` 不是同一标签；unknown 不能直接当负例。源综述表格转录也不等于已核验原始报告版本及数值。

当前CLI默认数据根为 `dataset/benchmark_releases/20261104_experiment_ready_v1`。Screening补齐池明确传 `--input-mode raw_pool`；公开代理池为 `views/public_fallback/`。首轮coding使用 `views/document_available_coding/` 并标明子集分母；source评分显式传 `--reference-policy source_transcribed`。综合主任务明确选MP11和MP12，其他未支持目标不冒主评分。实际命令、旧版本与源输入保留方式见[中文快速开始](../docs/audits/20261104_experiment_ready/START_HERE.zh-CN.md)。

此前strict-original草稿曾通过独立一致性验收并切换到`benchmark_v2/`；以下是该旧口径草稿的数量，不是本轮目标参数主GT的数量（同一报告跨任务分别计数）：

|产物|记录数与口径|
|---|---|
|`ground_truth` / `screening_ground_truth`|1129条，旧台账按整篇SR最终纳入的报告级参考；两文件互为兼容别名，范围宽于本轮主GT，不是独立scientific gold|
|主`raw_search` / `raw_search_original`|4453条，仅明确准入的原数据库、原式与原窗口支路|
|`manual_source_additions`|975条，有最终纳入证据及补入理由的人工补齐|
|主`raw_pool`|5428条，去重后的原式主检索加人工补齐；不是完整原始检索池|
|`raw_search_extended`|125413条，所有活跃真实检索，包含主检索与另列的扩展/代理支路|
|`raw_pool_extended`|125715条，扩展自然检索与有标签来源补齐的独立视图|

只有6个任务的8次运行有准入原式支路，且尚无全部原数据库路线完成的证据；其余16任务的主自然检索池为空，表示待复原，不表示原作者检索到0篇。它们的主池可能只有GT人工补齐，当前草稿暂不用于22任务screening评测。来源台账就绪只表示`source_roster_alignment_ready`；兼容字段`strict_original_alignment_ready`的scope为`source_ledger_only`。所有任务的`original_raw_pool_complete`与`screening_evaluation_ready`均为false。

`legacy_pool` 是隔离的旧v1诊断视图，不进入主 `raw_search` 或 `raw_pool`；`historical_manual_source_additions`也只保留旧补入审计。补齐正例不等于自然检索恢复，增强池表现不能冒充自然端到端召回。主GT记录历史原综述最终纳入事实，不是独立科学纳排金标准；pending和名单外记录不能自动当科学负例，名单未齐的任务不能据此宣称完整precision/F1。`analysis_ground_truth` 与 `analysis_reference` 保留分析子集口径，`coding_reference` 是后者的兼容别名，主GT变化不删这些数值证据。GT、来源清单和参考数值不进入模型输入。

前轮重建过程见[重建报告](../docs/audits/20261103_benchmark_rebuild/REPORT.md)；本轮原式政策与最终纳入对齐见[对齐报告](../docs/audits/20261103_original_alignment/REPORT.md)。逐任务状态以当前manifest及task文件为准；旧备份与当前版本均为draft。

## 旧路径兼容与恢复

以下入口是相对软链，实际目录均在本次归档中：

|兼容入口|实际位置（相对项目根）|
|---|---|
|`dataset/_legacy_imports`|`archive/20261103_160112_pre_refactor/legacy/dataset/_legacy_imports`|
|`dataset/avian_influenza`|`archive/20261103_160112_pre_refactor/legacy/dataset/avian_influenza`|
|`dataset/covid19`|`archive/20261103_160112_pre_refactor/legacy/dataset/covid19`|
|`dataset/mpox`|`archive/20261103_160112_pre_refactor/legacy/dataset/mpox`|

这些软链仅兼容旧 CLI 路径，不建议继续向旧路径写入新项目数据；它们不提供只读隔离，写入会修改归档内容。新检索、编码和实验输出应使用独立的新工作目录及显式输入/输出路径。

迁移与恢复记录见[完整映射](../archive/20261103_160112_pre_refactor/all_path_relocations.json)和[归档索引](../archive/20261103_160112_pre_refactor/README.md)。恢复时先停止写入、确认兼容入口仍是预期软链，仅移除链接本身，再把实际目录移回空缺的原路径并核对清单；不得覆盖新文件或删除链接目标。其余旧 dataset 资料也保留在归档，详见 supplemental manifest。
