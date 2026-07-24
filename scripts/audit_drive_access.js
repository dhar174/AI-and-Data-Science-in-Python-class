#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { performance } = require("node:perf_hooks");
const {
  buildFullAuditTargets,
  classifyAuditObservation,
  selectPreflight,
  summarize,
  writeReportFiles,
} = require("./drive_access_audit_lib");

const DEFAULT_PLAYWRIGHT_PATH =
  "C:\\Users\\darf3\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\node_modules\\.pnpm\\playwright@1.61.1\\node_modules\\playwright";

function parseArgs(argv) {
  const root = path.resolve(__dirname, "..");
  const options = {
    catalog: path.join(root, "data", "course-catalog.json"),
    outputJson: path.join(root, "reports", "drive-access-audit.json"),
    outputMarkdown: path.join(root, "reports", "drive-access-audit.md"),
    concurrency: 8,
    timeoutMs: 15_000,
    settleMs: 900,
    preflightOnly: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--preflight-only") {
      options.preflightOnly = true;
      continue;
    }
    const next = argv[index + 1];
    if (!next) throw new Error(`Missing value after ${argument}.`);
    if (argument === "--catalog") options.catalog = path.resolve(next);
    else if (argument === "--output-json") options.outputJson = path.resolve(next);
    else if (argument === "--output-md") options.outputMarkdown = path.resolve(next);
    else if (argument === "--concurrency") options.concurrency = Number(next);
    else if (argument === "--timeout-ms") options.timeoutMs = Number(next);
    else if (argument === "--settle-ms") options.settleMs = Number(next);
    else throw new Error(`Unknown argument: ${argument}`);
    index += 1;
  }

  if (!Number.isInteger(options.concurrency) || options.concurrency < 1 || options.concurrency > 16) {
    throw new Error("--concurrency must be an integer from 1 through 16.");
  }
  if (!Number.isInteger(options.timeoutMs) || options.timeoutMs < 3_000) {
    throw new Error("--timeout-ms must be an integer of at least 3000.");
  }
  return options;
}

function loadPlaywright() {
  const candidate = process.env.CODEX_PLAYWRIGHT_PATH || DEFAULT_PLAYWRIGHT_PATH;
  try {
    return require(candidate);
  } catch (error) {
    throw new Error(`Unable to load Playwright from ${candidate}: ${error.message}`);
  }
}

function findInstalledChromium() {
  if (process.env.CODEX_CHROMIUM_EXECUTABLE) {
    return process.env.CODEX_CHROMIUM_EXECUTABLE;
  }
  const cacheRoot =
    process.env.PLAYWRIGHT_BROWSERS_PATH ||
    path.join(process.env.LOCALAPPDATA || "", "ms-playwright");
  if (!cacheRoot || !fs.existsSync(cacheRoot)) return null;
  const candidates = fs
    .readdirSync(cacheRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("chromium_headless_shell-"))
    .map((entry) =>
      path.join(
        cacheRoot,
        entry.name,
        "chrome-headless-shell-win64",
        "chrome-headless-shell.exe",
      ),
    )
    .filter((candidate) => fs.existsSync(candidate))
    .sort()
    .reverse();
  return candidates[0] || null;
}

async function observeTarget(browser, target, options) {
  let lastObservation = null;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const context = await browser.newContext({
      acceptDownloads: false,
      locale: "en-US",
      serviceWorkers: "block",
    });
    const initialCookieCount = (await context.cookies()).length;
    const page = await context.newPage();
    await page.route("**/*", async (route) => {
      const resourceType = route.request().resourceType();
      if (["image", "media", "font"].includes(resourceType)) {
        await route.abort();
      } else {
        await route.continue();
      }
    });

    const started = performance.now();
    const observation = {
      requestedUrl: target.requested_url,
      finalUrl: target.requested_url,
      httpStatus: null,
      title: "",
      bodyText: "",
      navigationError: "",
    };

    try {
      const response = await page.goto(target.requested_url, {
        waitUntil: "domcontentloaded",
        timeout: options.timeoutMs,
      });
      observation.httpStatus = response?.status() ?? null;
      await page.waitForTimeout(options.settleMs);
      observation.finalUrl = page.url();
      observation.title = await page.title().catch(() => "");
      observation.bodyText = await page
        .locator("body")
        .innerText({ timeout: 2_000 })
        .catch(() => "");
    } catch (error) {
      observation.finalUrl = page.url() || target.requested_url;
      observation.navigationError = String(error?.message || error).split("\n")[0];
    } finally {
      await context.close();
    }

    const verdict = classifyAuditObservation(observation);
    lastObservation = {
      ...target,
      requested_url: target.requested_url,
      final_url: observation.finalUrl,
      http_status: observation.httpStatus,
      classification: verdict.classification,
      evidence: verdict.evidence,
      attempt,
      initial_cookie_count: initialCookieCount,
      elapsed_ms: Math.round(performance.now() - started),
    };

    const transient =
      verdict.classification === "error" &&
      (observation.navigationError ||
        observation.httpStatus === 429 ||
        (observation.httpStatus !== null && observation.httpStatus >= 500));
    if (!transient || attempt === 2) return lastObservation;
  }
  return lastObservation;
}

async function auditTargets(browser, targets, options) {
  const results = new Array(targets.length);
  let cursor = 0;

  async function worker() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= targets.length) return;
      results[index] = await observeTarget(browser, targets[index], options);
      if ((index + 1) % 50 === 0 || index + 1 === targets.length) {
        process.stdout.write(`Audited ${index + 1}/${targets.length}\n`);
      }
    }
  }

  const workerCount = Math.min(options.concurrency, targets.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}

function phase(results) {
  const summary = summarize(results);
  return {
    status: summary.blocking === 0 ? "passed" : "blocked",
    summary,
    results,
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const started = performance.now();
  const catalog = JSON.parse(fs.readFileSync(options.catalog, "utf8"));
  const playwright = loadPlaywright();
  const chromiumExecutable = findInstalledChromium();
  const browser = await playwright.chromium.launch({
    headless: true,
    ...(chromiumExecutable ? { executablePath: chromiumExecutable } : {}),
  });

  try {
    const cookieProbe = await browser.newContext();
    const initialCookieCount = (await cookieProbe.cookies()).length;
    await cookieProbe.close();

    const preflightTargets = selectPreflight(catalog.records || []);
    const preflightResults = await auditTargets(browser, preflightTargets, {
      ...options,
      concurrency: Math.min(options.concurrency, preflightTargets.length),
    });
    const preflight = phase(preflightResults);
    let fullAudit = null;

    if (preflight.status === "passed" && !options.preflightOnly) {
      const fullTargets = buildFullAuditTargets(catalog.records || []);
      const fullResults = await auditTargets(browser, fullTargets, options);
      fullAudit = phase(fullResults);
    }

    const report = {
      schema_version: 1,
      generated_utc: new Date().toISOString(),
      catalog_path: path.relative(path.dirname(options.outputJson), options.catalog).replaceAll("\\", "/"),
      browser: {
        engine: "chromium",
        headless: true,
        fresh_context_per_navigation: true,
        executable: chromiumExecutable || "playwright-managed",
        initial_cookie_count: initialCookieCount,
        host: os.hostname(),
      },
      settings: {
        concurrency: options.concurrency,
        timeout_ms: options.timeoutMs,
        settle_ms: options.settleMs,
        transient_navigation_retries: 1,
      },
      elapsed_ms: Math.round(performance.now() - started),
      preflight,
      full_audit: fullAudit,
      release_gate:
        preflight.status === "passed" &&
        (options.preflightOnly || fullAudit?.status === "passed")
          ? "passed"
          : "blocked",
    };

    writeReportFiles(report, options.outputJson, options.outputMarkdown);
    process.stdout.write(
      `Preflight ${preflight.status}: ${preflight.summary.accessible}/${preflight.summary.total} accessible.\n`,
    );
    if (fullAudit) {
      process.stdout.write(
        `Full audit ${fullAudit.status}: ${fullAudit.summary.accessible}/${fullAudit.summary.total} accessible.\n`,
      );
    }
    process.stdout.write(`Report: ${options.outputJson}\n`);
    process.exitCode = report.release_gate === "passed" ? 0 : 2;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
