# 重构前归档：2026-11-03 16:01:12

前一轮归档已完成：23项顶层迁移、49项补充迁移和2项核心来源迁移，共74条路径、256,076个文件、31,155,709,760字节，原三份 manifest 与统计保持不变。现另追加15个测试文件、161,692字节，逐文件 inode 与 SHA256 核验通过；完整映射现为89条。核心来源迁移至当前 dataset，并非全部内容都放入 legacy。旧评测已停止：20项 finished（8项 completed、12项 partial_or_failed）、2项中断、23项未开始。归档不表示 Stage A 重构、benchmark 科学审定或旧评测已完成。

**当前根 docs/ 是用户明确保留的例外。** 其中的新审计材料已完成，保留供后续优化使用；旧 docs 已在 [legacy/docs/](legacy/docs/)，不覆盖、不合并，新 docs 不表示恢复旧目录。不要盲目重跑 `archive_project.py --apply`：根 docs 与归档 docs 同时存在会触发安全拒绝，不能为绕过拒绝而移走保留的新材料。

## 索引与完成证据

|位置|用途与状态|
|---|---|
|[move_manifest.json](move_manifest.json)|23项顶层迁移，状态 completed；251,982文件、30,017,164,229字节，全部 verified|
|[supplemental_manifest.json](supplemental_manifest.json)|49项补充迁移，状态 completed；3,502文件、1,073,627,350字节，含旧 dataset、非 CLI 工具/图表、4项 legacy 测试及缓存|
|[core_relocations.json](core_relocations.json)|2项核心审计来源迁往 dataset/benchmark_sources；592文件、64,918,181字节，全部 verified|
|[all_path_relocations.json](all_path_relocations.json)|完整89条映射：原74条加追加15个测试文件；附兼容软链恢复说明，恢复时优先查此表|
|[tests_archive_manifest.json](tests_archive_manifest.json)|测试追加归档 completed：15文件、161,692字节，逐文件 before/after inode 与 SHA256 全 verified，记录既有旧测试集且不覆盖|
|[legacy/tests/](legacy/tests/)|旧测试与 fixture 的实际归档位置；根 tests 已移除且未留软链|
|[pathmap.json](pathmap.json)|顶层脚本生成的恢复映射；仅覆盖顶层23项|
|[move_plan_review.json](move_plan_review.json)|移动前只读计划；实际完成清单以 manifest 为准|
|[legacy/A_paper/](legacy/A_paper/)|论文实际归档位置，嵌套 .git 随整个目录保留|
|`legacy/paper_pool/`|历史归档位置；纸池现已恢复到项目根目录 `paper_pool/`，供运行时复用|
|[legacy/](legacy/)|其余历史目录、结果、开发材料、工具和大文件，保留原相对路径|
|`private/.env.local.bk`|本地凭据备份；目录700、文件600，不展示内容|
|`state/core_snapshot.tar.gz`|移动前核心快照；468,987,241字节，SHA256 `83d15ee92cd21b3962be9c182be4d44b88e80b54fe8547d49008a4188e3fbb14`|
|`state/history.bundle`|移动前 Git 历史，已通过 bundle 验证|
|[state/snapshot_content_validation.json](state/snapshot_content_validation.json)|核心快照782个文件逐项 SHA256 检查通过，无缺失或不一致|
|[state/rebuild_comparison.json](state/rebuild_comparison.json)|离线重建22项通过：来源893、coding1532、GT488、source tables222；与既有参考仅审计路径前缀不同，不表示科学 gold 已审定|
|[state/move_inventories/](state/move_inventories/)|逐项移动前后文件清单与校验；敏感文件只存哈希和元数据|
|[archive_context.json](archive_context.json)|归档背景与已停止进程|
|[archive_project.py](archive_project.py)|固定顶层允许清单工具；未包含补充迁移和核心来源迁移|

归档数据、快照、凭据和执行清单默认不入 Git；仅此索引与工具可纳入版本管理。当前 tools 保留32个核心源/README文件及 benchmark evidence/protocols；被归档工具的具体映射见 supplemental manifest，不根据历史文件名推断仍可调用。

## 当前入口与运行边界

核心代码、配置、基准数据及环境仍在项目根目录；旧测试已全部合并到 `legacy/tests/`，根目录没有 `tests/` 或测试软链。后续新测试按重构重新建立，旧 fixture 可按需从归档恢复。历史检查记录（包括200 passed）保留原时点含义，移动不改变这些历史结果，也不表示新方案已重新通过验证。两份 benchmark 审计缓存已迁至 `dataset/benchmark_sources/ground_truth_coverage_audit_20261103` 和 `dataset/benchmark_sources/query_strategy_audit_20261103`，builder 已使用新位置。

以下4个旧数据入口保留相对兼容软链，实际内容在 `legacy/dataset/<同名目录>`：`dataset/_legacy_imports`、`dataset/avian_influenza`、`dataset/covid19`、`dataset/mpox`。链接用于旧 CLI 路径解析，不是新工作区或只读权限隔离；写这些路径会改动归档数据。

纸池已从 `legacy/paper_pool/` 整体恢复至项目根目录 `paper_pool/`；原迁移清单保留当时记录，后续全文缓存使用根目录。其他归档材料的位置未因纸池恢复而改变。

## 复核与恢复

可运行只读计划查看当前源/目标状态：

```bash
python archive/20261103_160112_pre_refactor/archive_project.py --plan
```

此时看到 docs 冲突是已知保护行为。原允许清单的 apply 已完成；不要照旧教程再次执行，也不要为了重跑移动用户要求保留的新 docs。若要增加归档范围，先单独审核新计划。

恢复前停止相关写入，查看 [all_path_relocations.json](all_path_relocations.json) 和相应 inventories。仅在原路径不存在时将实际归档目标整体移回，不覆盖新目录。4个 dataset 兼容入口需先确认仍是指向已记录目标的软链，再仅移除该软链，随后将实际目录移回原路径并校验；不能删除软链指向的数据。旧测试可根据 tests_archive_manifest 按需恢复到新的测试工作区，保留原 fixture 与相对位置，不覆盖后来建立的新 tests。A_paper 应整体恢复以保留嵌套 Git 与相对位置。核心 benchmark_sources 的恢复必须与对应 builder 路径配置一起协调。

完整核心恢复可使用 tar 快照与 Git bundle，先在独立恢复目录展开和核对，避免直接覆盖当前代码。凭据备份恢复后仍保持600权限；不要公开 private、快照或本地配置。
