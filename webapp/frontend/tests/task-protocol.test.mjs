import assert from "node:assert/strict";
import { test } from "node:test";
import yaml from "js-yaml";
import {
  readAnalysisProtocol,
  writeAnalysisProtocol,
} from "../src/task-protocol.ts";

const analysis = {
  analysis_id: "main",
  parameter_type: "serial_interval",
  estimate_measure: "mean",
  unit: "days",
  method: "fixed",
  uncertainty_rules: { allowed_types: ["CI"] },
  independence: { unit: "cohort_id" },
  leave_one_out: true,
};
const advanced = {
  research_question: "A real saved question",
  review_protocol: {
    version: "1",
    criteria: [{ id: "design", description: "Original study" }],
    logic: "design",
  },
  coding: { backend: "langextract", stage_a_empty_retries: 2 },
  llm: { coding: { thinking: "disabled", max_tokens: 8000 } },
  custom_future_field: { preserve: ["all", "values"] },
};

test("backend default empty analysis_protocols cannot hide a saved single analysis", () => {
  const response = {
    ...advanced,
    analysis_protocol: analysis,
    analysis_protocols: [],
  };
  const reloaded = yaml.load(yaml.dump(response));
  assert.deepEqual(readAnalysisProtocol(reloaded), analysis);
});

test("nonempty multi-analysis list takes precedence and round-trips all analysis fields", () => {
  const multiple = [
    analysis,
    {
      ...analysis,
      analysis_id: "sensitivity",
      method: "random",
      filters: { variant: ["A", "B"] },
    },
  ];
  assert.deepEqual(
    readAnalysisProtocol({
      analysis_protocol: null,
      analysis_protocols: multiple,
    }),
    multiple,
  );
  const saved = yaml.load(yaml.dump(writeAnalysisProtocol(advanced, multiple)));
  assert.deepEqual(readAnalysisProtocol(saved), multiple);
  assert.deepEqual(saved.custom_future_field, advanced.custom_future_field);
});

test("switching single to multiple and back is mutually exclusive and immutable", () => {
  const original = {
    ...advanced,
    analysis_protocol: analysis,
    analysis_protocols: [],
  };
  const multi = writeAnalysisProtocol(original, [analysis]);
  assert.equal(Object.hasOwn(multi, "analysis_protocol"), false);
  assert.deepEqual(original.analysis_protocol, analysis);
  const single = writeAnalysisProtocol(multi, { ...analysis, method: "reml" });
  assert.equal(Object.hasOwn(single, "analysis_protocols"), false);
  assert.equal(single.analysis_protocol.method, "reml");
  for (const key of Object.keys(advanced))
    assert.deepEqual(single[key], advanced[key]);
});

test("an intentional empty multiple-analysis edit clears the single analysis", () => {
  const result = writeAnalysisProtocol({ analysis_protocol: analysis }, []);
  assert.equal(Object.hasOwn(result, "analysis_protocol"), false);
  assert.deepEqual(readAnalysisProtocol(result), []);
});
