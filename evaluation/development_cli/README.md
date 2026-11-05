# CLI developer effect validation

The runnable pack is `configs/validation/pack.json`; its task YAMLs contain no expected values or gold labels. Expected source fields and short quotes live only in `references.json`. `freeze.json` binds tasks, codebooks, reference and source bytes before new live model validation.

Run a retrospective check through actual CLI status subprocesses:

```bash
.venv/bin/python tools/scripts/validate_cli_effect.py \
  --case covid_serial_mean_32191173 \
  --case mpox_incubation_CrI_36323407 \
  --run covid_serial_mean_32191173=runs/pjlab_v41_ci/workflow \
  --run mpox_incubation_CrI_36323407=runs/pjlab_v41_mpox/workflow \
  --output runs/cli_effect_validation_20261104/offline
```

New live checks require the explicit flag below. Execute only after the core CLI/model configuration is frozen; this command runs the selected cases serially. No live run was used to prepare this pack.

```bash
.venv/bin/python tools/scripts/validate_cli_effect.py --live \
  --output runs/cli_effect_validation_20261104
```

Each live subprocess executes `python -m metaagent.cli workflow run --start-at coding --stop-after pooling --document-manifest ... --ablation full --json`. This is **fixed-document Coding→Synthesis development validation**, not a natural-retrieval E2E result. The two full-text parse cases and the primary-abstract-only median case are reported separately by `case_coverage`/`source_scope`. The existing CI/mpox runs were visible before pack creation: retrospective agreement is not a blinded test-set estimate.

Reports retain exact argv, CLI exit code, complete stdout/stderr plus hashes, strict JSON-contract status, declared workflow manifest, actual A/B logical and logged provider attempts, reference field differences, scope ambiguity/missingness, synthesis refusal, wall time and raw call-audit paths. Token totals retain unknown-usage counts. New model attempts/token deltas are separated from historical artifact costs when resume reuses prior outputs.

Record matching uses canonical report identity, parameter/statistic and predeclared source regions. It never picks a numerically nearest estimate. Extra predictions remain pending annotation; ambiguous or missing inputs remain in the planned case denominator. Conflicted source fields are `not_scored_source_conflict`. No formal extraction precision, recall or F1 is claimed, and no benchmark verified-reference gate is relaxed.

The harness exits nonzero when development checks are incomplete or fail. Inspect per-case fields and semantic safety rather than interpreting a partial CLI run as success. In the mpox safety case, a genuine CrI refusal is expected to produce a non-computable synthesis and a nonzero workflow exit; that safety behavior is reported separately from extraction agreement and conflict visibility.

All full texts and generated reports live under ignored `runs/cli_effect_validation_20261104/`; only this small guide and reusable pack/script files should be tracked. Source recovery and version changes are described in `configs/validation/SOURCE_RECOVERY.md`.

## Real CLI development observations, 2026-11-04

The first run tested all three frozen cases. Prompt v2 retested CI and mpox with the **same tasks, sources, references and matcher** after independent offline checks. Version v3 tested only CI with a bounded evidence-only correction phase; none of the expected fields were adjusted to model output. The source references remain provisional developer annotations, and these visible development cases do not establish general accuracy.

| Case | First live run | Prompt v2 live run | Evidence v3 live run |
| --- | --- | --- | --- |
| Serial interval mean, full text | A+B ran; five rows made scope ambiguous; evidence pending; CLI partial | One overall row and all eight reference fields agree; distribution evidence still unmatched; CLI partial | One overall row, eight fields agree; one evidence-only correction located the original OCR quote; no pending review; synthesis complete |
| Incubation median, primary abstract only | A+B ran; unique scope and eight fields agree; median synthesis complete | Not rerun | Not rerun |
| Mpox mean/CrI, full text | Conflict explicitly preserved; multiple scoped rows pending; no synthesis | Conflict preserved; ambiguity/pending remain; no synthesis | Not rerun; latest-version quality on this case remains unvalidated |

The mpox case did **not** pass the predeclared CrI-specific safety check in either new live run: evidence/semantic review blocked the rows before the unauthorized-uncertainty rule was exercised. No CrI was converted to CI or pooled, but that alone is insufficient to claim that this specific test passed. The conflicted upper bound remains unscored. Missing, ambiguous and partial cases remain visible; neither live round is reported as all passing.

An additional first-round CLI run executed all six stages against a real PubMed identity query: retrieval, title/abstract screening, full-text fetch, full-text screening, Coding A+B, and synthesis. The first five completed; synthesis returned partial because coding evidence remained pending. The v2 six-stage run was **not started**, because its predeclared CI-complete condition was unmet. After fixed-document CI passed in v3, a fresh v3 six-stage run completed all six stages with no reused workflow stages, CLI exit zero, one selected estimate, and zero pending rows. It made two screening requests and one A plus one B request; the E2E run needed no evidence correction. Full-text retrieval reused the shared MinerU cache tied to the source PDF hash. Both E2E parses differed from the frozen fixed-document source version, so their reports list source-supported magnitudes without reusing old source offsets for an exact score.

Before v3 live execution, an independent tester passed **420 offline tests**, 18 adversarial scenarios/153 checks, and seven real CLI subprocess probes/47 checks. Scientific guard ASTs and monitored source/reference/policy hashes remained unchanged; final live hash verification also matched all 13 monitored files. These are software-contract checks, separate from the small real-model observations above. The successful fixed-document and six-stage CI runs concern the **same primary report**, not two independent scientific validation samples.

The successful six-stage command was then executed again with exactly the same argv and an inherited socket guard forbidding network access. Resume returned complete in 1.85 seconds, reused all six stages, made zero network attempts, and left every provider log byte-for-byte unchanged. This checks actual CLI idempotence; it is not another model validation sample. The original live receipts remain intact, and `e2e_v3/resume_probe/report.json` records both manifest versions and log hashes.

Runtime evidence is retained under `runs/cli_effect_validation_20261104/`: `LIVE_ROUND1_SUMMARY.json`, `V1_V2_COMPARISON.json`, `V1_V2_V3_COMPARISON.json`, `LIVE_V3_FINAL_HASH_VERIFICATION.json`, `live/`, `live_v2/`, `live_v3/CI_EVIDENCE_RECEIPT.json`, and the `e2e/`/`e2e_v3/` reports. Raw CLI stdout/stderr, exit codes, actual provider attempts, quota failures, observed tokens and unknown-usage events remain alongside the reports. First-round and v2 failures are retained separately.

The exact two-case v2 harness command used was:

```bash
.venv/bin/python tools/scripts/validate_cli_effect.py --live \
  --case covid_serial_mean_32191173 \
  --case mpox_incubation_CrI_36323407 \
  --output runs/cli_effect_validation_20261104/live_v2
```

The final successful fixed-document command was:

```bash
.venv/bin/python tools/scripts/validate_cli_effect.py --live \
  --case covid_serial_mean_32191173 \
  --output runs/cli_effect_validation_20261104/live_v3
```

The separately tested, successful v3 six-stage command was:

```bash
.venv/bin/python -m metaagent.cli workflow run \
  --task-config runs/cli_effect_validation_20261104/e2e_v3/task.yaml \
  --start-at retrieval --stop-after pooling --ablation full --limit 1 \
  --output-dir runs/cli_effect_validation_20261104/e2e_v3/workflow --json
```

That E2E task is an **ignored local runtime fixture**, copied from the frozen CI task with its task ID changed, codebook path made absolute, and `search.pubmed` set to `32191173[uid]`; it contains no reference values. Its task/source/reference hashes were saved before first execution in `e2e/pre_model_reference.json`; the v3 task and pre-model reference are byte-identical copies. The identity query verifies the complete engineering path for one known report; it does not measure broad-query retrieval recall. The reusable tracked entry point remains `configs/validation/pack.json` and the harness above; complete source fixtures must be restored as documented before either command is reproduced.
