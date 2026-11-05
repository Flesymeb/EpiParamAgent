import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactPreviewKind } from "../src/artifact-preview.ts";

test("XLSX and archive artifacts are download-only and cannot be decoded as text", () => {
  for (const name of [
    "coding_sheet.xlsx",
    "archive.zip",
    "assets.tar.gz",
    "results.parquet",
    "unknown.bin",
  ]) {
    assert.equal(
      artifactPreviewKind({ name, media_type: "application/octet-stream" }),
      "download",
    );
  }
  assert.equal(
    artifactPreviewKind({
      name: "coding_sheet.xlsx",
      media_type: "text/plain",
    }),
    "download",
  );
  assert.equal(
    artifactPreviewKind({
      name: "unknown",
      media_type: "application/octet-stream",
    }),
    "download",
  );
});

test("existing PNG/PDF preview survives generic binary MIME", () => {
  assert.equal(
    artifactPreviewKind({
      name: "forest.png",
      media_type: "application/octet-stream",
    }),
    "image",
  );
  assert.equal(
    artifactPreviewKind({
      name: "forest.pdf",
      media_type: "application/octet-stream",
    }),
    "pdf",
  );
});

test("only explicit text formats and text MIME are eligible for text fetch", () => {
  for (const name of [
    "coding.jsonl",
    "result.json",
    "report.md",
    "records.csv",
    "protocol.yaml",
    "source.xml",
    "worker.log",
    "search.ris",
  ]) {
    assert.equal(
      artifactPreviewKind({ name, media_type: "application/octet-stream" }),
      "text",
    );
  }
  assert.equal(
    artifactPreviewKind({
      name: "result",
      media_type: "application/json; charset=utf-8",
    }),
    "text",
  );
  assert.equal(
    artifactPreviewKind({ name: "worker", media_type: "text/plain" }),
    "text",
  );
});
