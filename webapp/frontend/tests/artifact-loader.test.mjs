import assert from "node:assert/strict";
import { test } from "node:test";
import { setImmediate } from "node:timers/promises";
import { loadJsonArtifact, synthesisRevision } from "../src/artifact-loader.ts";

function run(hash = "old-hash", id = "same-run") {
  return {
    id,
    status: "complete",
    updated_at: "2026-11-03T00:00:00Z",
    stage_results: {
      pooling: {
        fingerprint: hash,
        output_hashes: { "/run/result.json": hash },
      },
    },
    manifest: {
      artifacts: { synthesis_result: "/run/result.json" },
      stage_results: {},
    },
  };
}
function transportHarness() {
  const calls = [];
  return {
    calls,
    transport: (url, options) =>
      new Promise((resolve) => calls.push({ url, options, resolve })),
  };
}
function response(value) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("same artifact URL refreshes from a new authoritative pooling revision without HTTP cache reuse", async () => {
  const harness = transportHarness();
  const seen = [];
  const errors = [];
  const before = synthesisRevision(run());
  const after = synthesisRevision(run("new-hash"));
  assert.notEqual(before, after);
  const cancel = loadJsonArtifact(
    "/api/runs/same/artifacts/synthesis_result",
    before,
    (value) => seen.push(value),
    (error) => errors.push(error),
    harness.transport,
  );
  harness.calls[0].resolve(response({ result: { pooled_mean: 5 } }));
  await setImmediate();
  cancel();
  loadJsonArtifact(
    "/api/runs/same/artifacts/synthesis_result",
    after,
    (value) => seen.push(value),
    (error) => errors.push(error),
    harness.transport,
  );
  harness.calls[1].resolve(response({ result: { pooled_mean: 5.25 } }));
  await setImmediate();
  assert.notEqual(harness.calls[0].url, harness.calls[1].url);
  assert.equal(harness.calls[1].options.cache, "no-store");
  assert.deepEqual(
    seen.map((value) => value.result.pooled_mean),
    [5, 5.25],
  );
  assert.deepEqual(errors, []);
});

test("switching run discards a late response from the previous run even if transport ignores abort", async () => {
  const harness = transportHarness();
  const seen = [];
  const cancel = loadJsonArtifact(
    "/api/runs/old/artifacts/synthesis_result",
    synthesisRevision(run("old", "old")),
    (value) => seen.push(value),
    assert.fail,
    harness.transport,
  );
  cancel();
  loadJsonArtifact(
    "/api/runs/new/artifacts/synthesis_result",
    synthesisRevision(run("new", "new")),
    (value) => seen.push(value),
    assert.fail,
    harness.transport,
  );
  assert.equal(harness.calls[0].options.signal.aborted, true);
  harness.calls[1].resolve(
    response({ run: "new", result: { pooled_mean: 5.25 } }),
  );
  await setImmediate();
  harness.calls[0].resolve(
    response({ run: "old", result: { pooled_mean: 5 } }),
  );
  await setImmediate();
  assert.deepEqual(seen, [{ run: "new", result: { pooled_mean: 5.25 } }]);
});

test("status, updated time and source hash each invalidate a stable artifact URL", () => {
  const initial = run();
  const base = synthesisRevision(initial);
  assert.notEqual(base, synthesisRevision({ ...initial, status: "running" }));
  assert.notEqual(
    base,
    synthesisRevision({ ...initial, updated_at: "2026-11-03T00:00:01Z" }),
  );
  const changed = structuredClone(initial);
  changed.stage_results.pooling.output_hashes["/run/result.json"] =
    "new-content";
  assert.notEqual(base, synthesisRevision(changed));
});
