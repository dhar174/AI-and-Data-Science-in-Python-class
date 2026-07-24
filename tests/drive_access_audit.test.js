"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  buildFullAuditTargets,
  classifyAuditObservation,
  markdownReport,
  selectPreflight,
  summarize,
} = require("../scripts/drive_access_audit_lib");

test("optional sign-in text does not block an anonymous Google viewer", () => {
  const result = classifyAuditObservation({
    requestedUrl: "https://docs.google.com/document/d/abc",
    finalUrl: "https://docs.google.com/document/d/abc/edit",
    httpStatus: 200,
    title: "Lesson - Google Docs",
    bodyText: "Sign in to save a copy",
  });
  assert.equal(result.classification, "accessible");
});

test("request access text is blocking", () => {
  const result = classifyAuditObservation({
    requestedUrl: "https://drive.google.com/file/d/abc",
    finalUrl: "https://drive.google.com/file/d/abc/view",
    httpStatus: 200,
    title: "Google Drive",
    bodyText: "You need access. Request access from the owner.",
  });
  assert.equal(result.classification, "access_required");
});

test("account-only redirect is blocking", () => {
  const result = classifyAuditObservation({
    requestedUrl: "https://docs.google.com/document/d/abc",
    finalUrl: "https://accounts.google.com/v3/signin/identifier",
    httpStatus: 200,
  });
  assert.equal(result.classification, "access_required");
});

test("navigation failures and unexpected hosts are errors", () => {
  assert.equal(
    classifyAuditObservation({
      requestedUrl: "https://drive.google.com/file/d/abc",
      navigationError: "Timeout 15000ms exceeded",
    }).classification,
    "error",
  );
  assert.equal(
    classifyAuditObservation({
      requestedUrl: "https://drive.google.com/file/d/abc",
      finalUrl: "https://example.com/",
      httpStatus: 200,
    }).classification,
    "error",
  );
});

test("preflight selects all five required Google application types", () => {
  const records = [
    record("1", "drive", "https://drive.google.com/file/d/drive"),
    record("2", "docs", "https://docs.google.com/document/d/doc"),
    record("3", "slides", "https://docs.google.com/presentation/d/slides"),
    record("4", "sheets", "https://docs.google.com/spreadsheets/d/sheet"),
    {
      ...record("5", "notebook", "https://drive.google.com/file/d/notebook"),
      cloud: {
        source_url: "https://drive.google.com/file/d/notebook",
        launch_url: "https://colab.research.google.com/drive/notebook",
      },
    },
  ];
  assert.deepEqual(
    selectPreflight(records).map((item) => item.category),
    ["drive_file", "docs_document", "presentation", "spreadsheet", "colab"],
  );
});

test("full targets are files only and sorted deterministically", () => {
  const records = [
    record("b", "B", "https://drive.google.com/file/d/b"),
    { ...record("web", "Web", "https://example.com"), resource_kind: "web_app" },
    record("a", "A", "https://drive.google.com/file/d/a"),
  ];
  assert.deepEqual(
    buildFullAuditTargets(records).map((item) => item.id),
    ["a", "b"],
  );
});

test("summary and markdown report expose the release blockers", () => {
  const results = [
    { classification: "accessible" },
    { classification: "access_required" },
    { classification: "error" },
  ];
  assert.deepEqual(summarize(results), {
    total: 3,
    accessible: 1,
    access_required: 1,
    error: 1,
    blocking: 2,
  });

  const markdown = markdownReport({
    generated_utc: "2026-07-23T00:00:00.000Z",
    catalog_path: "../data/course-catalog.json",
    browser: { initial_cookie_count: 0 },
    preflight: {
      status: "blocked",
      summary: summarize(results),
      results: [
        {
          category: "drive_file",
          id: "a",
          name: "Blocked | File",
          classification: "access_required",
          final_url: "https://drive.google.com/file/d/a",
          evidence: "Request access",
        },
      ],
    },
    full_audit: null,
  });
  assert.match(markdown, /Full audit: not run because the preflight did not pass/);
  assert.match(markdown, /Blocked \\| File/);
});

function record(id, name, sourceUrl) {
  return {
    id,
    name,
    resource_kind: "file",
    cloud: { source_url: sourceUrl, launch_url: sourceUrl },
  };
}
