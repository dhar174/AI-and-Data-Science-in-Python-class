"use strict";

const fs = require("node:fs");
const path = require("node:path");

const GOOGLE_VIEW_HOSTS = new Set([
  "drive.google.com",
  "docs.google.com",
  "colab.research.google.com",
]);

const ACCESS_REQUIRED_PATTERNS = [
  /\brequest access\b/i,
  /\byou need access\b/i,
  /\baccess denied\b/i,
  /\bask for access\b/i,
  /\bpermission denied\b/i,
  /\byou (?:do not|don't) have permission\b/i,
  /\bfile is not shared\b/i,
];

function cleanText(value, limit = 500) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function safeHostname(value) {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function classifyAuditObservation(observation) {
  const requestedUrl = String(observation.requestedUrl || "");
  const finalUrl = String(observation.finalUrl || requestedUrl);
  const finalHost = safeHostname(finalUrl);
  const title = cleanText(observation.title, 200);
  const bodyText = cleanText(observation.bodyText, 4_000);
  const combined = `${title}\n${bodyText}`;
  const httpStatus = Number.isInteger(observation.httpStatus)
    ? observation.httpStatus
    : null;
  const navigationError = cleanText(observation.navigationError, 500);

  if (navigationError) {
    return {
      classification: "error",
      evidence: `Navigation failed: ${navigationError}`,
    };
  }

  if (finalHost === "accounts.google.com") {
    return {
      classification: "access_required",
      evidence: "Anonymous navigation redirected to accounts.google.com.",
    };
  }

  const accessMatch = ACCESS_REQUIRED_PATTERNS.find((pattern) =>
    pattern.test(combined),
  );
  if (accessMatch) {
    return {
      classification: "access_required",
      evidence: `Page displayed access-blocking text: "${cleanText(
        combined.match(accessMatch)?.[0] || "access required",
        120,
      )}".`,
    };
  }

  if (httpStatus !== null && httpStatus >= 400) {
    return {
      classification: "error",
      evidence: `Navigation returned HTTP ${httpStatus}.`,
    };
  }

  if (!GOOGLE_VIEW_HOSTS.has(finalHost)) {
    return {
      classification: "error",
      evidence: finalHost
        ? `Navigation ended on unexpected host ${finalHost}.`
        : "Navigation did not produce a valid final URL.",
    };
  }

  return {
    classification: "accessible",
    evidence: title
      ? `Anonymous Google viewer/editor loaded with title "${title}".`
      : "Anonymous Google viewer/editor loaded without access-blocking text.",
  };
}

function selectPreflight(records) {
  const files = records.filter((record) => record.resource_kind === "file");
  const selectors = [
    {
      category: "drive_file",
      predicate: (record) =>
        safeHostname(record.cloud?.source_url) === "drive.google.com" &&
        record.cloud?.app !== "colab",
      urlField: "source_url",
    },
    {
      category: "docs_document",
      predicate: (record) =>
        safeHostname(record.cloud?.source_url) === "docs.google.com" &&
        new URL(record.cloud.source_url).pathname.startsWith("/document/"),
      urlField: "source_url",
    },
    {
      category: "presentation",
      predicate: (record) =>
        safeHostname(record.cloud?.source_url) === "docs.google.com" &&
        new URL(record.cloud.source_url).pathname.startsWith("/presentation/"),
      urlField: "source_url",
    },
    {
      category: "spreadsheet",
      predicate: (record) =>
        safeHostname(record.cloud?.source_url) === "docs.google.com" &&
        new URL(record.cloud.source_url).pathname.startsWith("/spreadsheets/"),
      urlField: "source_url",
    },
    {
      category: "colab",
      predicate: (record) =>
        safeHostname(record.cloud?.launch_url) === "colab.research.google.com",
      urlField: "launch_url",
    },
  ];

  return selectors.map((selector) => {
    const record = files.find(selector.predicate);
    if (!record) {
      throw new Error(`No public catalog record found for ${selector.category}.`);
    }
    return {
      category: selector.category,
      id: record.id,
      name: record.name,
      url_field: selector.urlField,
      requested_url: record.cloud[selector.urlField],
    };
  });
}

function buildFullAuditTargets(records) {
  return records
    .filter((record) => record.resource_kind === "file")
    .map((record) => ({
      category: "source_url",
      id: record.id,
      name: record.name,
      url_field: "source_url",
      requested_url: record.cloud?.source_url || "",
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
}

function summarize(results) {
  const summary = {
    total: results.length,
    accessible: 0,
    access_required: 0,
    error: 0,
    blocking: 0,
  };
  for (const result of results) {
    if (Object.hasOwn(summary, result.classification)) {
      summary[result.classification] += 1;
    }
  }
  summary.blocking = summary.access_required + summary.error;
  return summary;
}

function markdownReport(report) {
  const lines = [
    "# Anonymous Google Drive Access Audit",
    "",
    `- Generated: ${report.generated_utc}`,
    `- Catalog: \`${report.catalog_path}\``,
    `- Initial browser cookies: ${report.browser.initial_cookie_count}`,
    `- Preflight: ${report.preflight.status} (${report.preflight.summary.accessible}/${report.preflight.summary.total} accessible)`,
  ];

  if (report.full_audit) {
    lines.push(
      `- Full audit: ${report.full_audit.status} (${report.full_audit.summary.accessible}/${report.full_audit.summary.total} accessible)`,
    );
  } else {
    lines.push(
      report.preflight.status === "passed"
        ? "- Full audit: not run; this execution was intentionally limited to the representative preflight."
        : "- Full audit: not run because the preflight did not pass.",
    );
  }

  lines.push("", "## Preflight", "", "| Type | Record | Result | Evidence |", "|---|---|---|---|");
  for (const result of report.preflight.results) {
    lines.push(
      `| ${escapeMarkdown(result.category)} | ${escapeMarkdown(result.name)} | ${result.classification} | ${escapeMarkdown(result.evidence)} |`,
    );
  }

  const blockers = [
    ...report.preflight.results,
    ...(report.full_audit?.results || []),
  ].filter((result) => result.classification !== "accessible");

  lines.push("", "## Blocking results", "");
  if (!blockers.length) {
    lines.push("None.");
  } else {
    lines.push("| ID | Record | Result | Final URL | Evidence |", "|---|---|---|---|---|");
    for (const result of blockers) {
      lines.push(
        `| ${escapeMarkdown(result.id)} | ${escapeMarkdown(result.name)} | ${result.classification} | ${escapeMarkdown(result.final_url)} | ${escapeMarkdown(result.evidence)} |`,
      );
    }
  }
  lines.push("");
  return lines.join("\n");
}

function escapeMarkdown(value) {
  return cleanText(value, 1_000).replace(/\|/g, "\\|");
}

function writeReportFiles(report, jsonPath, markdownPath) {
  fs.mkdirSync(path.dirname(jsonPath), { recursive: true });
  fs.mkdirSync(path.dirname(markdownPath), { recursive: true });
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  fs.writeFileSync(markdownPath, markdownReport(report), "utf8");
}

module.exports = {
  buildFullAuditTargets,
  classifyAuditObservation,
  markdownReport,
  selectPreflight,
  summarize,
  writeReportFiles,
};
