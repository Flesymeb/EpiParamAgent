import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import {
  synthesisAnalyses,
  synthesisReviewReasons,
} from "../src/synthesis-view.ts";

// Captured from an actual local background-worker software acceptance run.
// Its two synthetic records (4/6 days, SE1) are not research evidence or gold.
const recorded = JSON.parse(
  readFileSync(
    new URL("./fixtures/software-acceptance-synthesis.json", import.meta.url),
    "utf8",
  ),
);

test("the actual API single-analysis artifact exposes its computed fields unchanged", () => {
  const [analysis] = synthesisAnalyses(recorded);
  assert.equal(analysis.analysis_id, "incubation-mean-example");
  assert.equal(analysis.status, "complete");
  assert.equal(analysis.result.pooled_mean, 5);
  assert.equal(analysis.result.method, "fixed");
  assert.equal(analysis.result.unit, "days");
  assert.equal(analysis.counts.selected, 2);
  assert.equal(analysis.result.ci_lower, 3.614096175650322);
  assert.deepEqual(synthesisReviewReasons(analysis), []);
});

test("multi-analysis preserves failed analysis and review reasons without inventing a result", () => {
  const pending = {
    analysis_id: "pending-analysis",
    status: "protocol_pending",
    result: null,
    protocol_gaps: ["Method is unresolved"],
    counts: { input: 2, selected: 0, review: 2 },
    selection: [
      { estimate_id: "e1", decision: "review", reasons: ["missing_cohort_id"] },
    ],
  };
  const analyses = synthesisAnalyses({
    status: "partial",
    analyses: [recorded, pending],
  });
  assert.equal(analyses.length, 2);
  assert.equal(analyses[1].result, null);
  assert.equal(analyses[1].status, "protocol_pending");
  assert.deepEqual(synthesisReviewReasons(analyses[1]), [
    "Method is unresolved",
    "e1：missing_cohort_id",
  ]);
});

test("missing or invalid artifacts do not become successful numeric summaries", () => {
  assert.deepEqual(synthesisAnalyses(null), []);
  assert.deepEqual(synthesisAnalyses("complete"), []);
  assert.deepEqual(
    synthesisAnalyses({ analyses: [null, "not-an-analysis"] }),
    [],
  );
  const [failed] = synthesisAnalyses({
    status: "not_computable",
    result: null,
    reason: "insufficient_eligible_independent_estimates",
  });
  assert.equal(failed.result, null);
  assert.deepEqual(synthesisReviewReasons(failed), [
    "insufficient_eligible_independent_estimates",
  ]);
});
