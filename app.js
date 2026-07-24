(() => {
  "use strict";

  const payload = window.COURSE_LIBRARY_DATA;
  if (!payload || !Array.isArray(payload.records)) {
    document.body.innerHTML = '<p class="fatal-error">Course catalog data could not be loaded.</p>';
    return;
  }

  const summary = payload.summary || {};
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  const emptyCloud = Object.freeze({
    provider: "google_drive", status: "missing", source_url: "", mime_type: "",
    app: "", launch_url: "", copy_mode: "none",
    available: false, reason: "No verified Google Drive link has been recorded.",
  });
  const records = payload.records.map((record) => {
    const resourceKind = record.resource_kind || "file";
    return {
      ...record,
      resource_kind: resourceKind,
      catalog_path: record.catalog_path || "",
      audience_normalized: record.audience_normalized || normalizeAudience(record.audience),
      ...(resourceKind === "file" ? { cloud: { ...emptyCloud, ...(record.cloud || {}) } } : {}),
    };
  });
  const directories = Array.isArray(payload.directories) && payload.directories.length
    ? payload.directories
    : deriveDirectories(records);
  const recordById = new Map(records.map((record) => [record.id, record]));
  const directoryByPath = new Map(directories.map((directory) => [directory.path, directory]));
  const childDirectories = new Map();
  const directRecords = new Map();

  directories.forEach((directory) => {
    if (directory.parent_path === null) return;
    if (!childDirectories.has(directory.parent_path)) childDirectories.set(directory.parent_path, []);
    childDirectories.get(directory.parent_path).push(directory);
  });
  childDirectories.forEach((items) => items.sort((a, b) => collator.compare(a.name, b.name)));
  records.forEach((record) => {
    const parent = recordParentPath(record);
    if (!directRecords.has(parent)) directRecords.set(parent, []);
    directRecords.get(parent).push(record);
  });
  directRecords.forEach((items) => items.sort((a, b) => collator.compare(a.name, b.name)));

  const defaults = Object.freeze({
    view: "library",
    path: "",
    query: "",
    mode: "All",
    module: "",
    type: "",
    resourceKind: "",
    status: "Organized",
    topic: "",
    audience: "",
    dependency: "",
    confidence: "",
    scope: "all",
    sort: "name",
    direction: "asc",
    page: 1,
    pageSize: 25,
    selectedId: "",
    visualLayout: "list",
  });
  const state = { ...defaults };
  const ui = {
    expandedPaths: new Set([""]),
    treeFocusPath: "",
    folderLimit: 12,
    fileLimit: 24,
    inspectorTab: "overview",
    previewRecordId: "",
    lastTrigger: null,
  };
  let filteredRecords = records.slice();
  let directoryMatchCounts = new Map();
  let directFilteredRecords = new Map();
  let toastTimer = 0;

  const els = {
    appShell: byId("appShell"),
    sidebar: byId("sidebar"),
    mobileMenu: byId("mobileMenu"),
    mobileScrim: byId("mobileScrim"),
    breadcrumb: byId("breadcrumb"),
    search: byId("searchInput"),
    summaryLine: byId("summaryLine"),
    sidebarFileCount: byId("sidebarFileCount"),
    overviewButton: byId("overviewButton"),
    overviewDialog: byId("overviewDialog"),
    closeOverview: byId("closeOverview"),
    overviewContent: byId("overviewContent"),
    filterPanel: byId("filterPanel"),
    module: byId("moduleFilter"),
    type: byId("typeFilter"),
    resourceKind: byId("resourceKindFilter"),
    status: byId("statusFilter"),
    topic: byId("topicFilter"),
    audience: byId("audienceFilter"),
    dependency: byId("dependencyFilter"),
    confidence: byId("confidenceFilter"),
    moreToggle: byId("moreFiltersToggle"),
    moreFilters: byId("moreFilters"),
    activeFilters: byId("activeFilters"),
    recoveryHint: byId("recoveryHint"),
    clearFilters: byId("clearFilters"),
    libraryView: byId("libraryView"),
    treeView: byId("treeView"),
    visualView: byId("visualView"),
    libraryHeading: byId("libraryHeading"),
    librarySubtitle: byId("librarySubtitle"),
    pageSize: byId("pageSize"),
    catalogBody: byId("catalogBody"),
    pagination: byId("pagination"),
    directoryTree: byId("directoryTree"),
    treeFolderHeader: byId("treeFolderHeader"),
    treeChildFolders: byId("treeChildFolders"),
    treeFiles: byId("treeFiles"),
    treeRootButton: byId("treeRootButton"),
    treeCollapseButton: byId("treeCollapseButton"),
    childFolderCount: byId("childFolderCount"),
    visualFolderGrid: byId("visualFolderGrid"),
    showAllFolders: byId("showAllFolders"),
    ancestorRail: byId("ancestorRail"),
    currentFolderBanner: byId("currentFolderBanner"),
    visualFilesSummary: byId("visualFilesSummary"),
    visualFiles: byId("visualFiles"),
    showMoreFiles: byId("showMoreFiles"),
    inspector: byId("inspector"),
    inspectorTitle: byId("inspectorTitle"),
    inspectorSubtitle: byId("inspectorSubtitle"),
    inspectorKicker: byId("inspectorKicker"),
    inspectorPreviewTab: byId("inspectorTabPreview"),
    inspectorIntegrityLabel: byId("inspectorIntegrityLabel"),
    inspectorPreview: byId("inspectorPreview"),
    inspectorOverview: byId("inspectorOverview"),
    inspectorMetadata: byId("inspectorMetadata"),
    inspectorIntegrity: byId("inspectorIntegrity"),
    closeInspector: byId("closeInspector"),
    cloudAction: byId("cloudAction"),
    cloudActionLabel: byId("cloudActionLabel"),
    cloudActionHint: byId("cloudActionHint"),
    driveAction: byId("driveAction"),
    webAppAction: byId("webAppAction"),
    copyUrl: byId("copyUrl"),
    toast: byId("toast"),
  };
  els.viewButtons = Array.from(document.querySelectorAll("[data-view]"));
  els.collectionButtons = Array.from(document.querySelectorAll(".collection-nav"));
  els.audienceButtons = Array.from(document.querySelectorAll("[data-mode]"));
  els.sortButtons = Array.from(document.querySelectorAll("[data-sort]"));
  els.layoutButtons = Array.from(document.querySelectorAll("[data-layout]"));
  els.inspectorTabs = Array.from(document.querySelectorAll("[data-inspector-tab]"));

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function shortLabel(value) {
    return String(value || "").replace(/^\d{2}\s+-\s+/, "");
  }

  function normalizeAudience(value) {
    const normalized = shortLabel(value).toLocaleLowerCase();
    if (normalized === "student") return "Student";
    if (normalized === "instructor") return "Instructor";
    return "Shared";
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString();
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let amount = value / 1024;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) {
      amount /= 1024;
      index += 1;
    }
    return `${amount >= 100 ? amount.toFixed(0) : amount >= 10 ? amount.toFixed(1) : amount.toFixed(2)} ${units[index]}`;
  }

  function formatDate(value) {
    if (!value) return "Unknown";
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? value
      : new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(date);
  }

  function humanize(value) {
    return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function isWebApp(record) {
    return record?.resource_kind === "web_app";
  }

  function recordParentPath(record) {
    const parts = String(record.catalog_path || "").split("/");
    parts.pop();
    return parts.join("/");
  }

  function parentPath(path) {
    if (!path) return "";
    const parts = path.split("/");
    parts.pop();
    return parts.join("/");
  }

  function recordHref(record) {
    return isWebApp(record) ? record.web_app.url : record.cloud.source_url;
  }

  function recordUpdatedUtc(record) {
    return isWebApp(record) ? record.web_app.last_checked_utc : record.modified_utc;
  }

  function resourceSizeLabel(record) {
    return isWebApp(record) ? "Web app" : formatBytes(record.size_bytes);
  }

  const textPreviewExtensions = new Set([
    ".csv", ".css", ".ipynb", ".js", ".json", ".jsonl", ".md", ".py", ".r", ".readme",
    ".sh", ".sql", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
  ]);

  function previewKind(record) {
    if (isWebApp(record)) return "unsupported";
    const extension = String(record.extension || "").toLocaleLowerCase();
    return textPreviewExtensions.has(extension) ? "text" : "drive";
  }

  function renderPreview(record) {
    const kind = previewKind(record);
    const name = escapeHtml(recordDisplayName(record));
    if (kind === "text") {
      const excerpt = record.preview_text || "No text excerpt is available for this file.";
      const continuation = record.preview_truncated
        ? "Preview truncated. Open the verified Drive file to read the remainder."
        : "Complete embedded text preview.";
      els.inspectorPreview.innerHTML = `<div class="file-preview" data-preview-kind="text"><div class="preview-stage is-text"><pre class="preview-code" tabindex="0" aria-label="Text preview of ${name}"><code>${escapeHtml(excerpt)}</code></pre></div><p class="preview-help">${continuation}</p></div>`;
    } else {
      const driveUrl = escapeHtml(record.cloud.source_url);
      els.inspectorPreview.innerHTML = `<div class="preview-unavailable"><span class="file-badge file-generic" aria-hidden="true">${escapeHtml((record.extension || "FILE").replace(".", "").slice(0, 5).toUpperCase())}</span><strong>Preview in Google Drive</strong><p>Binary course files are not loaded from this GitHub Pages site.</p><a class="button primary" href="${driveUrl}" target="_blank" rel="noreferrer">Preview in Google Drive</a></div>`;
    }
    els.inspectorPreview.dataset.recordId = record.id;
    els.inspectorPreview.dataset.previewKind = kind;
  }

  function deriveDirectories(sourceRecords) {
    const paths = new Set();
    sourceRecords.forEach((record) => {
      const parts = record.catalog_path.split("/");
      for (let index = 1; index < parts.length; index += 1) paths.add(parts.slice(0, index).join("/"));
    });
    const allPaths = ["", ...Array.from(paths).sort((a, b) => collator.compare(a, b))];
    return allPaths.map((path) => {
      const parts = path ? path.split("/") : [];
      const prefix = path ? `${path}/` : "";
      const directRecordsForPath = sourceRecords.filter((record) => recordParentPath(record) === path);
      const descendantRecords = sourceRecords.filter((record) => !path || record.catalog_path.startsWith(prefix));
      const directFiles = directRecordsForPath.filter((record) => !isWebApp(record)).length;
      const descendantFiles = descendantRecords.filter((record) => !isWebApp(record)).length;
      const directWebApps = directRecordsForPath.filter(isWebApp).length;
      const descendantWebApps = descendantRecords.filter(isWebApp).length;
      const children = allPaths.filter((candidate) => candidate && parentPath(candidate) === path).length;
      return {
        id: path ? `dir-${path}` : "dir-root",
        path,
        name: path ? parts.at(-1) : "Course Library",
        parent_path: path ? parentPath(path) : null,
        depth: parts.length,
        folder_uri: path ? "#" : summary.library_root_uri || "#",
        physical_exists: true,
        direct_file_count: directFiles,
        descendant_file_count: descendantFiles,
        direct_web_app_count: directWebApps,
        descendant_web_app_count: descendantWebApps,
        direct_resource_count: directRecordsForPath.length,
        descendant_resource_count: descendantRecords.length,
        child_folder_count: children,
      };
    });
  }

  function directoryAncestors(path) {
    const ancestors = [directoryByPath.get("")];
    if (!path) return ancestors.filter(Boolean);
    const parts = path.split("/");
    for (let index = 1; index <= parts.length; index += 1) {
      const directory = directoryByPath.get(parts.slice(0, index).join("/"));
      if (directory) ancestors.push(directory);
    }
    return ancestors;
  }

  function uniqueSorted(field, source = records) {
    return Array.from(new Set(source.map((record) => record[field]).filter(Boolean)))
      .sort((a, b) => collator.compare(a, b));
  }

  function populateSelect(select, values, firstLabel, formatter = shortLabel) {
    const selected = select.value;
    select.innerHTML = `<option value="">${escapeHtml(firstLabel)}</option>` + values
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(formatter(value))}</option>`)
      .join("");
    if (values.includes(selected)) select.value = selected;
  }

  function populateFilters() {
    populateSelect(els.module, uniqueSorted("module"), "All modules");
    populateSelect(els.type, uniqueSorted("item_type"), "All types", (value) => shortLabel(value) || "Unclassified type");
    populateSelect(els.status, uniqueSorted("status"), "All statuses", (value) => value);
    populateSelect(els.audience, uniqueSorted("audience_normalized"), "Any compatible audience", (value) => value);
    populateSelect(els.confidence, uniqueSorted("confidence"), "All confidence levels", humanize);
    updateTopicOptions();
  }

  function updateTopicOptions() {
    const source = state.module ? records.filter((record) => record.module === state.module) : records;
    const values = uniqueSorted("topic", source);
    if (state.topic && !values.includes(state.topic)) state.topic = "";
    populateSelect(els.topic, values, "All topics");
    els.topic.value = state.topic;
  }

  function readHashState() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    Object.assign(state, defaults);
    const map = {
      view: "view", path: "path", q: "query", mode: "mode", module: "module", type: "type",
      kind: "resourceKind",
      status: "status", topic: "topic", audience: "audience", dependency: "dependency",
      confidence: "confidence", scope: "scope", sort: "sort", direction: "direction",
      selected: "selectedId", layout: "visualLayout",
    };
    Object.entries(map).forEach(([parameter, key]) => {
      if (params.has(parameter)) state[key] = params.get(parameter) || defaults[key];
    });
    if (!["library", "tree", "visual"].includes(state.view)) state.view = "library";
    if (!directoryByPath.has(state.path)) state.path = "";
    if (state.mode === "Instructor") state.mode = "All";
    if (!["All", "Student"].includes(state.mode)) state.mode = "All";
    state.scope = "all";
    if (!["", "file", "web_app"].includes(state.resourceKind)) state.resourceKind = "";
    if (!["asc", "desc"].includes(state.direction)) state.direction = "asc";
    if (!["grid", "list"].includes(state.visualLayout)) state.visualLayout = "list";
    if (state.selectedId && !recordById.has(state.selectedId)) state.selectedId = "";
    const page = Number(params.get("page"));
    const pageSize = Number(params.get("pageSize"));
    if (Number.isInteger(page) && page > 0) state.page = page;
    if ([25, 50, 100].includes(pageSize)) state.pageSize = pageSize;
    directoryAncestors(state.path).forEach((directory) => ui.expandedPaths.add(directory.path));
    ui.treeFocusPath = state.path;
  }

  function writeHashState() {
    const values = {
      view: state.view === "library" ? "" : state.view,
      path: state.path,
      q: state.query,
      mode: state.mode === "All" ? "" : state.mode,
      module: state.module,
      type: state.type,
      kind: state.resourceKind,
      status: state.status,
      topic: state.topic,
      audience: state.audience,
      dependency: state.dependency,
      confidence: state.confidence,
      scope: state.scope === "all" ? "" : state.scope,
      sort: state.sort === "name" ? "" : state.sort,
      direction: state.direction === "asc" ? "" : state.direction,
      page: state.page > 1 ? state.page : "",
      pageSize: state.pageSize === 25 ? "" : state.pageSize,
      selected: state.selectedId,
      layout: state.visualLayout === "list" ? "" : state.visualLayout,
    };
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) params.set(key, String(value));
    });
    const targetHash = params.size ? `#${params.toString()}` : "";
    if (location.hash === targetHash) return;
    try {
      history.replaceState(null, "", `${location.pathname}${location.search}${targetHash}`);
    } catch (_error) {
      location.hash = targetHash;
    }
  }

  function syncControls() {
    els.search.value = state.query;
    els.module.value = state.module;
    els.type.value = state.type;
    els.resourceKind.value = state.resourceKind;
    els.status.value = state.status;
    els.topic.value = state.topic;
    els.audience.value = state.audience;
    els.dependency.value = state.dependency;
    els.confidence.value = state.confidence;
    els.pageSize.value = String(state.pageSize);
    els.audienceButtons.forEach((button) => {
      const active = button.dataset.mode === state.mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    els.layoutButtons.forEach((button) => {
      const active = button.dataset.layout === state.visualLayout;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const secondaryActive = Boolean(state.resourceKind || state.topic || state.audience || state.dependency || state.confidence);
    if (secondaryActive) els.moreFilters.hidden = false;
    els.moreToggle.setAttribute("aria-expanded", String(!els.moreFilters.hidden));
  }

  function matchesAudienceMode(record) {
    if (state.mode === "All") return true;
    return record.audience_normalized === state.mode || record.audience_normalized === "Shared";
  }

  function getFilteredRecords() {
    const tokens = state.query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const filtered = records.filter((record) => {
      if (!matchesAudienceMode(record)) return false;
      if (state.resourceKind && record.resource_kind !== state.resourceKind) return false;
      if (state.module && record.module !== state.module) return false;
      if (state.type && record.item_type !== state.type) return false;
      if (state.status && record.status !== state.status) return false;
      if (state.topic && record.topic !== state.topic) return false;
      if (state.audience && record.audience_normalized !== state.audience) return false;
      if (state.dependency && isWebApp(record)) return false;
      if (state.dependency === "sensitive" && !record.dependency_sensitive) return false;
      if (state.dependency === "none" && record.dependency_sensitive) return false;
      if (state.confidence && record.confidence !== state.confidence) return false;
      if (tokens.length && !tokens.every((token) => record.search_text.includes(token))) return false;
      return true;
    });
    const accessors = {
      name: (record) => recordDisplayName(record),
      location: (record) => `${record.module} ${record.topic} ${record.catalog_path}`,
      type: (record) => record.item_type,
      audience: (record) => record.audience_normalized,
      status: (record) => record.status,
      modified: recordUpdatedUtc,
    };
    const accessor = accessors[state.sort] || accessors.name;
    filtered.sort((a, b) => {
      const result = collator.compare(accessor(a) || "", accessor(b) || "");
      return state.direction === "asc" ? result : -result;
    });
    return filtered;
  }

  function buildFilteredIndexes() {
    directoryMatchCounts = new Map([["", filteredRecords.length]]);
    directFilteredRecords = new Map();
    filteredRecords.forEach((record) => {
      const directPath = recordParentPath(record);
      if (!directFilteredRecords.has(directPath)) directFilteredRecords.set(directPath, []);
      directFilteredRecords.get(directPath).push(record);
      const parts = directPath ? directPath.split("/") : [];
      for (let index = 1; index <= parts.length; index += 1) {
        const path = parts.slice(0, index).join("/");
        directoryMatchCounts.set(path, (directoryMatchCounts.get(path) || 0) + 1);
      }
    });
  }

  function hasActiveFilters() {
    return Boolean(state.query || state.mode !== "All" || state.module || state.type || state.resourceKind || state.status || state.topic
      || state.audience || state.dependency || state.confidence || state.scope !== "all");
  }

  function fileBadge(record) {
    if (isWebApp(record)) return '<span class="file-badge web-app" aria-hidden="true">WEB</span>';
    const extension = String(record.extension || "").toLocaleLowerCase();
    let label = extension.replace(/^\./, "").slice(0, 4).toUpperCase() || "FILE";
    let kind = "file";
    if (extension === ".ipynb") { label = "NB"; kind = "notebook"; }
    else if (extension === ".pdf") { label = "PDF"; kind = "pdf"; }
    else if ([".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"].includes(extension)) { label = extension.replace(".", "").toUpperCase(); kind = "image"; }
    else if ([".mp4", ".mov", ".avi", ".mp3", ".wav"].includes(extension)) { label = extension.replace(".", "").toUpperCase(); kind = "media"; }
    else if ([".ppt", ".pptx"].includes(extension)) { label = "PPT"; kind = "presentation"; }
    else if ([".doc", ".docx"].includes(extension)) { label = "DOCX"; kind = "document"; }
    return `<span class="file-badge ${kind}" aria-hidden="true">${escapeHtml(label)}</span>`;
  }

  const cloudAppNames = Object.freeze({ colab: "Colab", docs: "Google Docs", slides: "Google Slides", sheets: "Google Sheets" });

  function cloudAppName(record) {
    return cloudAppNames[record.cloud?.app] || "Google app";
  }

  function cloudBadge(record) {
    if (!record.cloud?.available) return "";
    const label = record.cloud.app === "colab" ? "Colab" : record.cloud.app.replace(/^./, (value) => value.toUpperCase());
    return `<span class="cloud-app-label app-${escapeHtml(record.cloud.app)}" title="Verified ${escapeHtml(cloudAppName(record))} link">${escapeHtml(label)}</span>`;
  }

  function cloudStatusMarkup(record) {
    if (!record.cloud?.app) return "Not configured for this file type";
    return `${cloudBadge(record)} <span>${escapeHtml(record.cloud.reason)}</span>`;
  }

  function recordDisplayName(record) {
    return record.display_name || record.name;
  }

  function configureCloudAction(record) {
    const cloud = record.cloud || emptyCloud;
    const hasDriveLink = cloud.status === "verified" && Boolean(cloud.source_url);
    const hasApp = Boolean(cloud.available && cloud.app && cloud.launch_url);
    els.driveAction.hidden = !hasDriveLink;
    if (hasDriveLink) {
      els.driveAction.href = cloud.source_url;
      els.driveAction.target = "_blank";
      els.driveAction.rel = "noreferrer";
    } else {
      els.driveAction.removeAttribute("href");
    }
    const appName = cloudAppName(record);
    els.cloudAction.hidden = !hasApp;
    els.cloudActionHint.hidden = false;
    els.cloudActionHint.textContent = hasApp
      ? "Viewing is anonymous. Google sign-in is required to save, copy, or edit."
      : "Viewing is anonymous in Google Drive. Google sign-in is required to save, copy, or edit.";
    if (!hasApp) {
      els.cloudAction.removeAttribute("href");
      return;
    }
    els.cloudActionLabel.textContent = cloud.app === "colab" ? "Open in Colab" : `Make a copy in ${appName}`;
    els.cloudAction.href = cloud.launch_url;
    els.cloudAction.target = "_blank";
    els.cloudAction.rel = "noreferrer";
  }

  function statusClass(record) {
    if (record.status === "Organized" || record.status === "Available") return "organized";
    if (/duplicate/i.test(record.status)) return "duplicate";
    return "review";
  }

  function renderSummary() {
    const types = summary.item_type_counts || {};
    const notebookCount = Object.entries(types).filter(([key]) => /notebook|code/i.test(key)).reduce((sum, [, count]) => sum + count, 0);
    const mediaCount = Object.entries(types).filter(([key]) => /video|audio/i.test(key)).reduce((sum, [, count]) => sum + count, 0);
    const visualCount = Object.entries(types).filter(([key]) => /visual|infographic/i.test(key)).reduce((sum, [, count]) => sum + count, 0);
    const readingCount = Object.entries(types).filter(([key]) => /reading|reference/i.test(key)).reduce((sum, [, count]) => sum + count, 0);
    els.summaryLine.innerHTML = `<strong>${formatNumber(summary.total_resources)} resources</strong><span>${formatNumber(summary.directory_count)} folders</span><span>${formatNumber(summary.total_files)} files</span><span>${formatNumber(summary.total_web_apps)} web apps</span><span>${formatNumber(notebookCount)} notebooks/code</span><span>${formatNumber(mediaCount)} video/audio</span><span>${formatNumber(visualCount)} visuals</span><span>${formatNumber(readingCount)} readings</span>`;
    els.sidebarFileCount.textContent = `${formatNumber(summary.total_resources)} resources`;
  }

  function renderNavigation() {
    els.viewButtons.forEach((button) => {
      const active = button.dataset.view === state.view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });
    els.collectionButtons.forEach((button) => {
      let active = false;
      if (button.dataset.collection === "overview") {
        active = state.view === "library" && !state.module && state.scope === "all" && !state.resourceKind;
      } else if (button.dataset.collection === "web-apps") {
        active = state.view === "library" && state.resourceKind === "web_app";
      } else if (state.view === "library") {
        active = !state.resourceKind && button.dataset.module === state.module;
      } else {
        active = Boolean(button.dataset.path && (state.path === button.dataset.path || state.path.startsWith(`${button.dataset.path}/`)));
      }
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function renderBreadcrumb() {
    if (state.view === "library") {
      const location = state.resourceKind === "web_app"
        ? "Web Apps"
        : state.module ? shortLabel(state.module) : "All materials";
      els.breadcrumb.textContent = `Course Library / ${location}`;
      return;
    }
    const labels = directoryAncestors(state.path).map((directory) => shortLabel(directory.name));
    els.breadcrumb.textContent = labels.join(" / ");
  }

  function renderFilterPanel() {
    const slot = document.querySelector(`[data-filter-slot="${state.view}"]`);
    if (slot && els.filterPanel.parentElement !== slot) slot.appendChild(els.filterPanel);
    syncControls();
    const chips = [];
    const add = (label, key) => chips.push(`<button type="button" data-clear-filter="${key}">${escapeHtml(label)}<span aria-hidden="true">×</span></button>`);
    if (state.query) add(`Search: ${state.query}`, "query");
    if (state.mode !== "All") add(`${state.mode} mode`, "mode");
    if (state.module) add(shortLabel(state.module), "module");
    if (state.type) add(shortLabel(state.type), "type");
    if (state.resourceKind) add(state.resourceKind === "web_app" ? "Web apps" : "Files", "resourceKind");
    if (state.status) add(state.status, "status");
    if (state.topic) add(shortLabel(state.topic), "topic");
    if (state.audience) add(state.audience, "audience");
    if (state.dependency) add(state.dependency === "sensitive" ? "Dependency-sensitive" : "No detected dependencies", "dependency");
    if (state.confidence) add(`Confidence: ${humanize(state.confidence)}`, "confidence");
    els.activeFilters.innerHTML = chips.join("");
    els.clearFilters.hidden = chips.length === 0;
    els.recoveryHint.hidden = filteredRecords.length !== 0;
  }

  function renderLibrary() {
    els.libraryHeading.textContent = state.resourceKind === "web_app"
      ? "Web Apps"
      : state.module ? shortLabel(state.module) : "All materials";
    els.librarySubtitle.textContent = `${formatNumber(filteredRecords.length)} results in ${state.mode.toLocaleLowerCase()} view`;
    const totalPages = Math.max(1, Math.ceil(filteredRecords.length / state.pageSize));
    state.page = Math.min(state.page, totalPages);
    const start = (state.page - 1) * state.pageSize;
    const pageRecords = filteredRecords.slice(start, start + state.pageSize);
    if (!pageRecords.length) {
      els.catalogBody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><strong>No matching resources</strong><span>Clear one or more filters, or choose another collection.</span></div></td></tr>';
    } else {
      els.catalogBody.innerHTML = pageRecords.map((record) => {
        const selected = record.id === state.selectedId;
        return `<tr class="catalog-row${selected ? " is-selected" : ""}" data-record-id="${escapeHtml(record.id)}" tabindex="0" aria-selected="${selected}">
          <td data-label="Name"><div class="file-name-cell">${fileBadge(record)}<span><strong title="${escapeHtml(recordDisplayName(record))}">${escapeHtml(recordDisplayName(record))}</strong><small>${escapeHtml(resourceSizeLabel(record))}${cloudBadge(record)}</small></span></div></td>
          <td data-label="Location"><span class="truncate" title="${escapeHtml(record.catalog_path)}">${escapeHtml(shortLabel(record.module))} › ${escapeHtml(shortLabel(record.topic) || "General")}</span></td>
          <td data-label="Type">${escapeHtml(shortLabel(record.item_type) || "Unclassified")}</td>
          <td data-label="Audience"><span class="audience-label">${escapeHtml(record.audience_normalized)}</span></td>
          <td data-label="Status"><span class="status-label ${statusClass(record)}"><span aria-hidden="true"></span>${escapeHtml(record.status)}</span></td>
          <td data-label="Updated">${escapeHtml(formatDate(recordUpdatedUtc(record)))}</td>
          <td data-label="Open"><a class="row-open" href="${escapeHtml(recordHref(record))}" target="_blank" rel="noopener noreferrer">${isWebApp(record) ? "Launch" : "Open"}</a></td>
        </tr>`;
      }).join("");
    }
    renderPagination(totalPages);
    els.sortButtons.forEach((button) => {
      const active = button.dataset.sort === state.sort;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-sort", active ? (state.direction === "asc" ? "ascending" : "descending") : "none");
      button.dataset.direction = active ? state.direction : "";
    });
  }

  function pageSequence(current, total) {
    if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
    const values = new Set([1, total, current - 1, current, current + 1].filter((value) => value > 0 && value <= total));
    const sorted = Array.from(values).sort((a, b) => a - b);
    const sequence = [];
    sorted.forEach((value, index) => {
      if (index && value - sorted[index - 1] > 1) sequence.push("ellipsis");
      sequence.push(value);
    });
    return sequence;
  }

  function renderPagination(totalPages) {
    const buttons = pageSequence(state.page, totalPages).map((value) => value === "ellipsis"
      ? '<span class="pagination-ellipsis">…</span>'
      : `<button type="button" data-page="${value}" class="${value === state.page ? "is-active" : ""}" ${value === state.page ? 'aria-current="page"' : ""}>${value}</button>`).join("");
    els.pagination.innerHTML = `<button type="button" data-page="${state.page - 1}" ${state.page === 1 ? "disabled" : ""} aria-label="Previous page">Previous</button>${buttons}<button type="button" data-page="${state.page + 1}" ${state.page === totalPages ? "disabled" : ""} aria-label="Next page">Next</button>`;
  }

  function renderDirectoryTree() {
    const renderNode = (directory) => {
      const children = childDirectories.get(directory.path) || [];
      const hasChildren = children.length > 0;
      const expanded = directory.path === "" || ui.expandedPaths.has(directory.path);
      const selected = directory.path === state.path;
      const matchCount = directoryMatchCounts.get(directory.path) || 0;
      const visibleChildren = hasActiveFilters() ? children.filter((child) => (directoryMatchCounts.get(child.path) || 0) > 0) : children;
      const childMarkup = expanded && visibleChildren.length
        ? `<div class="tree-group" role="group">${visibleChildren.map(renderNode).join("")}</div>`
        : "";
      return `<div class="tree-node">
        <div class="tree-row${selected ? " is-selected" : ""}" role="treeitem" data-tree-path="${escapeHtml(directory.path)}" aria-level="${directory.depth + 1}" aria-selected="${selected}" ${hasChildren ? `aria-expanded="${expanded}"` : ""} tabindex="${directory.path === ui.treeFocusPath ? "0" : "-1"}">
          <button class="tree-toggle" type="button" data-tree-toggle="${escapeHtml(directory.path)}" ${hasChildren ? "" : "disabled"} aria-label="${expanded ? "Collapse" : "Expand"} ${escapeHtml(shortLabel(directory.name))}"><span class="icon icon-chevron${expanded ? "-down" : "-right"}" aria-hidden="true"></span></button>
          <button class="tree-select" type="button" data-tree-select="${escapeHtml(directory.path)}"><span class="icon ${directory.path ? "icon-folder" : "icon-home"}" aria-hidden="true"></span><span>${escapeHtml(shortLabel(directory.name))}</span><small>${formatNumber(matchCount)}</small></button>
        </div>${childMarkup}
      </div>`;
    };
    const root = directoryByPath.get("");
    els.directoryTree.innerHTML = root ? renderNode(root) : '<p class="empty-state">Directory data unavailable.</p>';
  }

  function folderListItem(directory, targetAttribute) {
    const matches = directoryMatchCounts.get(directory.path) || 0;
    return `<button class="compact-folder" type="button" ${targetAttribute}="${escapeHtml(directory.path)}">
      <span class="icon icon-folder" aria-hidden="true"></span>
      <span><strong>${escapeHtml(shortLabel(directory.name))}</strong><small>${formatNumber(matches)} matching · ${formatNumber(directory.descendant_resource_count)} total</small></span>
      <span class="icon icon-chevron-right" aria-hidden="true"></span>
    </button>`;
  }

  function compactFileItem(record, targetAttribute) {
    const selected = record.id === state.selectedId;
    return `<button class="compact-file${selected ? " is-selected" : ""}" type="button" ${targetAttribute}="${escapeHtml(record.id)}">
      ${fileBadge(record)}
      <span><strong>${escapeHtml(recordDisplayName(record))}</strong><small>${escapeHtml(shortLabel(record.item_type))} · ${escapeHtml(resourceSizeLabel(record))} · ${escapeHtml(record.audience_normalized)}${cloudBadge(record)}</small></span>
      <span class="status-label ${statusClass(record)}"><span aria-hidden="true"></span>${escapeHtml(record.status)}</span>
    </button>`;
  }

  function renderTreeView() {
    renderDirectoryTree();
    const directory = directoryByPath.get(state.path) || directoryByPath.get("");
    const children = childDirectories.get(directory.path) || [];
    const visibleChildren = hasActiveFilters() ? children.filter((child) => (directoryMatchCounts.get(child.path) || 0) > 0) : children;
    const resources = directFilteredRecords.get(directory.path) || [];
    const ancestors = directoryAncestors(directory.path).map((item) => shortLabel(item.name)).join(" / ");
    els.treeFolderHeader.innerHTML = `<div class="tree-folder-header"><span class="icon ${directory.path ? "icon-folder" : "icon-home"}" aria-hidden="true"></span><div><p>${escapeHtml(ancestors)}</p><h3>${escapeHtml(shortLabel(directory.name))}</h3><span>${formatNumber(directory.descendant_resource_count)} resources across ${formatNumber(directory.child_folder_count)} child folders</span></div></div>`;
    els.treeChildFolders.innerHTML = visibleChildren.length ? visibleChildren.map((child) => folderListItem(child, "data-tree-folder")).join("") : '<p class="empty-state">No child folders match the current filters.</p>';
    els.treeFiles.innerHTML = resources.length ? resources.map((record) => compactFileItem(record, "data-tree-file")).join("") : '<p class="empty-state">No direct resources match in this folder.</p>';
  }

  function folderAccent(path) {
    const top = path.split("/")[0] || "";
    if (top.startsWith("00 -")) return "admin";
    if (top.startsWith("01 -")) return "module-1";
    if (top.startsWith("02 -")) return "module-2";
    if (top.startsWith("03 -")) return "module-3";
    if (top.startsWith("04 -")) return "cross";
    if (top.startsWith("05 -")) return "review";
    return "overview";
  }

  function renderVisualView() {
    const directory = directoryByPath.get(state.path) || directoryByPath.get("");
    const children = childDirectories.get(directory.path) || [];
    const visibleChildren = hasActiveFilters() ? children.filter((child) => (directoryMatchCounts.get(child.path) || 0) > 0) : children;
    const shownChildren = visibleChildren.slice(0, ui.folderLimit);
    els.childFolderCount.textContent = `${formatNumber(visibleChildren.length)} folders · ${formatNumber(directoryMatchCounts.get(directory.path) || 0)} matching resources`;
    els.visualFolderGrid.innerHTML = shownChildren.length ? shownChildren.map((child) => {
      const matching = directoryMatchCounts.get(child.path) || 0;
      return `<button class="folder-card accent-${folderAccent(child.path)}" type="button" data-visual-folder="${escapeHtml(child.path)}">
        <span class="folder-card-icon"><span class="icon icon-folder" aria-hidden="true"></span></span>
        <strong>${escapeHtml(shortLabel(child.name))}</strong>
        <span>${formatNumber(matching)} matching</span>
        <small>${formatNumber(child.direct_resource_count)} direct · ${formatNumber(child.descendant_resource_count)} total</small>
      </button>`;
    }).join("") : '<div class="empty-state shelf-empty"><strong>No child folders</strong><span>This folder contains resources only, or no descendants match the active filters.</span></div>';
    els.showAllFolders.hidden = visibleChildren.length <= 12;
    els.showAllFolders.textContent = ui.folderLimit >= visibleChildren.length ? "Show fewer folders" : `Show all ${formatNumber(visibleChildren.length)} folders`;

    const ancestors = directoryAncestors(directory.path);
    els.ancestorRail.innerHTML = ancestors.map((ancestor, index) => `<button type="button" data-ancestor-path="${escapeHtml(ancestor.path)}" class="${ancestor.path === directory.path ? "is-current" : ""}" ${ancestor.path === directory.path ? 'aria-current="page"' : ""}>
      <span class="ancestor-dot"><span class="icon ${ancestor.path ? "icon-folder" : "icon-home"}" aria-hidden="true"></span></span>
      <span><strong>${escapeHtml(shortLabel(ancestor.name))}</strong><small>${index === ancestors.length - 1 ? "Current folder" : `${formatNumber(ancestor.descendant_resource_count)} resources`}</small></span>
    </button>`).join("");

    const depthPercent = summary.max_directory_depth ? Math.max(4, (directory.depth / summary.max_directory_depth) * 100) : 0;
    const breadcrumb = ancestors.map((ancestor) => shortLabel(ancestor.name)).join(" / ");
    els.currentFolderBanner.className = `folder-banner accent-${folderAccent(directory.path)}`;
    els.currentFolderBanner.innerHTML = `<div class="banner-main"><span class="banner-icon"><span class="icon ${directory.path ? "icon-folder" : "icon-library"}" aria-hidden="true"></span></span><div><p>${escapeHtml(breadcrumb)}</p><h2 id="visualHeading">${escapeHtml(shortLabel(directory.name))}</h2><span>${formatNumber(directory.child_folder_count)} child folders · ${formatNumber(directory.direct_resource_count)} direct resources · ${formatNumber(directory.descendant_resource_count)} total resources</span></div></div>
      <div class="banner-actions">${directory.path ? `<button class="button banner-button" type="button" data-parent-folder="${escapeHtml(directory.parent_path || "")}">Parent folder</button>` : ""}</div>
      <div class="depth-indicator"><span>Depth in library</span><div><i style="--depth:${depthPercent}%"></i></div><strong>Level ${directory.depth} of ${summary.max_directory_depth || directory.depth}</strong></div>`;

    const resources = directFilteredRecords.get(directory.path) || [];
    const shownFiles = resources.slice(0, ui.fileLimit);
    const descendantMatches = directoryMatchCounts.get(directory.path) || 0;
    els.visualFilesSummary.textContent = `${formatNumber(resources.length)} direct matches · ${formatNumber(descendantMatches)} matching resources below this location`;
    els.visualFiles.className = `visual-files is-${state.visualLayout}`;
    els.visualFiles.innerHTML = shownFiles.length ? shownFiles.map((record) => {
      const selected = record.id === state.selectedId;
      return `<button class="visual-file${selected ? " is-selected" : ""}" type="button" data-visual-file="${escapeHtml(record.id)}">
        ${fileBadge(record)}
        <span class="visual-file-name"><strong>${escapeHtml(recordDisplayName(record))}</strong><small>${escapeHtml(shortLabel(record.item_type))} · ${escapeHtml(resourceSizeLabel(record))}${cloudBadge(record)}</small></span>
        <span class="audience-label">${escapeHtml(record.audience_normalized)}</span>
        <span class="status-label ${statusClass(record)}"><span aria-hidden="true"></span>${escapeHtml(record.status)}</span>
        <time datetime="${escapeHtml(recordUpdatedUtc(record))}">${escapeHtml(formatDate(recordUpdatedUtc(record)))}</time>
      </button>`;
    }).join("") : `<div class="empty-state"><strong>No direct resource matches</strong><span>${descendantMatches ? "Matching resources exist in a child folder above." : "Clear a filter or return to a parent folder."}</span></div>`;
    els.showMoreFiles.hidden = resources.length <= ui.fileLimit;
    els.showMoreFiles.textContent = `Show ${formatNumber(Math.min(24, resources.length - ui.fileLimit))} more resources`;
  }

  function detailsList(items) {
    return `<dl>${items.map(([label, value, wide = false]) => `<div class="${wide ? "wide" : ""}"><dt>${escapeHtml(label)}</dt><dd>${value || "Not specified"}</dd></div>`).join("")}</dl>`;
  }

  function renderInspector() {
    const record = recordById.get(state.selectedId);
    const open = Boolean(record);
    els.inspector.hidden = !open;
    els.appShell.classList.toggle("inspector-open", open);
    if (!record) return;
    const webAppRecord = isWebApp(record);
    els.inspectorTitle.textContent = recordDisplayName(record);
    els.inspectorKicker.textContent = webAppRecord ? "Selected web app" : "Selected file";
    els.inspectorSubtitle.textContent = shortLabel(record.item_type) || (webAppRecord ? "Course web app" : "Course file");
    els.inspectorPreviewTab.hidden = webAppRecord;
    els.inspectorIntegrityLabel.textContent = webAppRecord ? "Link Details" : "Integrity & Dependencies";
    const previewChanged = ui.previewRecordId !== record.id;
    if (previewChanged) {
      ui.previewRecordId = record.id;
      ui.inspectorTab = webAppRecord || previewKind(record) === "unsupported" ? "overview" : "preview";
      if (!webAppRecord) renderPreview(record);
    }
    if (webAppRecord) {
      const host = new URL(record.web_app.url).hostname;
      els.inspectorOverview.innerHTML = detailsList([
        ["Description", escapeHtml(record.web_app.description), true],
        ["Location", `${escapeHtml(shortLabel(record.module))} › ${escapeHtml(shortLabel(record.topic))}`, true],
        ["Type", escapeHtml(shortLabel(record.item_type) || "Unclassified")],
        ["Audience", escapeHtml(record.audience_normalized)],
        ["Status", `<span class="status-label ${statusClass(record)}"><span aria-hidden="true"></span>${escapeHtml(record.status)}</span>`],
        ["Last verified", escapeHtml(formatDate(record.web_app.last_checked_utc))],
      ]);
      els.inspectorMetadata.innerHTML = detailsList([
        ["Module", escapeHtml(shortLabel(record.module) || "Not specified"), true],
        ["Topic", escapeHtml(shortLabel(record.topic) || "Not specified"), true],
        ["Service name", `<code>${escapeHtml(record.web_app.service_name)}</code>`, true],
        ["URL", `<span class="path-value">${escapeHtml(record.web_app.url)}</span>`, true],
        ["Material type", escapeHtml(shortLabel(record.item_type) || "Unclassified")],
        ["Manifest audience", escapeHtml(record.audience)],
      ]);
      els.inspectorIntegrity.innerHTML = detailsList([
        ["Link status", escapeHtml(humanize(record.web_app.link_status))],
        ["Last verified", escapeHtml(formatDate(record.web_app.last_checked_utc))],
        ["External host", `<code>${escapeHtml(host)}</code>`, true],
        ["Launch behavior", "Opens in a separate browser tab; the Course Library does not embed or pre-load this app.", true],
      ]);
      els.webAppAction.hidden = false;
      els.copyUrl.hidden = false;
      els.webAppAction.href = record.web_app.url;
      els.webAppAction.target = "_blank";
      els.webAppAction.rel = "noopener noreferrer";
      els.cloudAction.hidden = true;
      els.cloudActionHint.hidden = true;
      els.driveAction.hidden = true;
    } else {
      els.inspectorOverview.innerHTML = detailsList([
        ["Catalog location", `<span class="path-value">${escapeHtml(record.catalog_path)}</span>`, true],
        ["Type", escapeHtml(shortLabel(record.item_type) || "Unclassified")],
        ["Size", escapeHtml(formatBytes(record.size_bytes))],
        ["Modified", escapeHtml(formatDate(record.modified_utc))],
        ["Status", `<span class="status-label ${statusClass(record)}"><span aria-hidden="true"></span>${escapeHtml(record.status)}</span>`],
        ["Audience", escapeHtml(record.audience_normalized)],
        ["Google app", cloudStatusMarkup(record), true],
      ]);
      els.inspectorMetadata.innerHTML = detailsList([
        ["Module", escapeHtml(shortLabel(record.module) || "Not specified"), true],
        ["Topic", escapeHtml(shortLabel(record.topic) || "Not specified"), true],
        ["Audience", escapeHtml(record.audience_normalized)],
        ["Material type", escapeHtml(shortLabel(record.item_type) || "Unclassified"), true],
      ]);
      els.inspectorIntegrity.innerHTML = detailsList([
        ["SHA-256", `<code>${escapeHtml(record.sha256)}</code>`, true],
        ["Dependency", escapeHtml(record.dependency_status)],
        ["Bundle", escapeHtml(record.bundle_id || "None")],
        ["Google link status", escapeHtml(humanize(record.cloud.status))],
      ]);
      els.webAppAction.hidden = true;
      els.copyUrl.hidden = true;
      configureCloudAction(record);
    }
    els.inspectorTabs.forEach((button) => {
      const active = button.dataset.inspectorTab === ui.inspectorTab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = button.hidden ? -1 : active ? 0 : -1;
    });
    els.inspectorPreview.hidden = webAppRecord || ui.inspectorTab !== "preview";
    els.inspectorOverview.hidden = ui.inspectorTab !== "overview";
    els.inspectorMetadata.hidden = ui.inspectorTab !== "metadata";
    els.inspectorIntegrity.hidden = ui.inspectorTab !== "integrity";
  }

  function renderOverview() {
    const modules = Object.entries(summary.resource_module_counts || summary.module_counts || {}).map(([label, count]) => `<li><span>${escapeHtml(shortLabel(label))}</span><strong>${formatNumber(count)}</strong></li>`).join("");
    els.overviewContent.innerHTML = `<div class="overview-stats"><div><strong>${formatNumber(summary.total_resources)}</strong><span>Resources</span></div><div><strong>${formatNumber(summary.total_files)}</strong><span>Files</span></div><div><strong>${formatNumber(summary.total_web_apps)}</strong><span>Web apps</span></div><div><strong>${formatNumber(summary.directory_count)}</strong><span>Folders</span></div></div><h3>Resources by module</h3><ul class="overview-list">${modules}</ul><p class="overview-note">Generated ${escapeHtml(formatDate(summary.generated_utc))} from the approved file and web-app manifests.</p>`;
  }

  function render() {
    filteredRecords = getFilteredRecords();
    buildFilteredIndexes();
    renderNavigation();
    renderBreadcrumb();
    renderFilterPanel();
    els.libraryView.hidden = state.view !== "library";
    els.treeView.hidden = state.view !== "tree";
    els.visualView.hidden = state.view !== "visual";
    if (state.view === "library") renderLibrary();
    if (state.view === "tree") renderTreeView();
    if (state.view === "visual") renderVisualView();
    renderInspector();
    writeHashState();
  }

  function clearFilters({ preserveMode = true } = {}) {
    const mode = preserveMode ? state.mode : "All";
    Object.assign(state, {
      query: "", mode, module: "", type: "", resourceKind: "", status: "", topic: "", audience: "",
      dependency: "", confidence: "", scope: "all", page: 1,
    });
    updateTopicOptions();
    ui.fileLimit = 24;
    render();
  }

  function selectPath(path) {
    if (!directoryByPath.has(path)) return;
    state.path = path;
    state.page = 1;
    ui.fileLimit = 24;
    ui.folderLimit = 12;
    ui.treeFocusPath = path;
    directoryAncestors(path).forEach((directory) => ui.expandedPaths.add(directory.path));
    render();
  }

  function selectRecord(id, trigger = null) {
    if (!recordById.has(id)) return;
    state.selectedId = id;
    ui.lastTrigger = trigger || document.activeElement;
    renderInspector();
    writeHashState();
  }

  function closeInspector({ restoreFocus = true } = {}) {
    els.inspectorPreview.querySelectorAll("video, audio").forEach((media) => media.pause());
    state.selectedId = "";
    renderInspector();
    writeHashState();
    if (restoreFocus && ui.lastTrigger instanceof HTMLElement && document.contains(ui.lastTrigger)) ui.lastTrigger.focus();
  }

  function showToast(message) {
    window.clearTimeout(toastTimer);
    els.toast.textContent = message;
    els.toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => els.toast.classList.remove("is-visible"), 2600);
  }

  async function copyText(text, successMessage = "Path copied to clipboard.") {
    try {
      await navigator.clipboard.writeText(text);
      showToast(successMessage);
    } catch (_error) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.className = "clipboard-fallback";
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand("copy");
      textarea.remove();
      showToast(copied ? successMessage : "Copy failed. Select the value from the inspector.");
    }
  }

  function closeMobileNavigation() {
    els.sidebar.classList.remove("is-open");
    els.mobileMenu.setAttribute("aria-expanded", "false");
    els.mobileScrim.hidden = true;
  }

  function focusTreePath(path) {
    ui.treeFocusPath = path;
    renderTreeView();
    const target = Array.from(els.directoryTree.querySelectorAll(".tree-row")).find((row) => row.dataset.treePath === path);
    target?.focus();
  }

  function bindEvents() {
    els.search.addEventListener("input", () => {
      state.query = els.search.value;
      state.page = 1;
      ui.fileLimit = 24;
      render();
    });
    [els.module, els.type, els.resourceKind, els.status, els.topic, els.audience, els.dependency, els.confidence].forEach((select) => {
      select.addEventListener("change", () => {
        const keys = new Map([[els.module, "module"], [els.type, "type"], [els.resourceKind, "resourceKind"], [els.status, "status"], [els.topic, "topic"], [els.audience, "audience"], [els.dependency, "dependency"], [els.confidence, "confidence"]]);
        state[keys.get(select)] = select.value;
        if (select === els.module) updateTopicOptions();
        state.page = 1;
        ui.fileLimit = 24;
        render();
      });
    });
    els.pageSize.addEventListener("change", () => {
      state.pageSize = Number(els.pageSize.value);
      state.page = 1;
      render();
    });
    els.moreToggle.addEventListener("click", () => {
      els.moreFilters.hidden = !els.moreFilters.hidden;
      els.moreToggle.setAttribute("aria-expanded", String(!els.moreFilters.hidden));
    });
    els.clearFilters.addEventListener("click", () => clearFilters());
    els.activeFilters.addEventListener("click", (event) => {
      const button = event.target.closest("[data-clear-filter]");
      if (!button) return;
      const key = button.dataset.clearFilter;
      state[key] = defaults[key];
      if (key === "module") updateTopicOptions();
      state.page = 1;
      render();
    });
    els.audienceButtons.forEach((button) => button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      if (state.mode === "Student" && state.scope === "review") state.scope = "all";
      state.page = 1;
      render();
    }));
    els.viewButtons.forEach((button) => button.addEventListener("click", () => {
      state.view = button.dataset.view;
      state.page = 1;
      closeMobileNavigation();
      render();
    }));
    els.collectionButtons.forEach((button) => button.addEventListener("click", () => {
      if (button.dataset.collection === "overview") {
        state.view = "library";
        state.module = "";
        state.resourceKind = "";
        state.scope = "all";
      } else if (button.dataset.collection === "web-apps") {
        Object.assign(state, {
          view: "library", path: "", query: "", module: "", type: "", resourceKind: "web_app",
          status: "", topic: "", audience: "", dependency: "", confidence: "", scope: "all",
        });
        updateTopicOptions();
      } else if (state.view === "library") {
        state.module = button.dataset.module || "";
        state.resourceKind = "";
        state.scope = button.dataset.scope || "all";
        updateTopicOptions();
      } else {
        state.module = "";
        state.resourceKind = "";
        state.scope = button.dataset.scope || "all";
        state.path = button.dataset.path || "";
        directoryAncestors(state.path).forEach((directory) => ui.expandedPaths.add(directory.path));
      }
      state.page = 1;
      closeMobileNavigation();
      render();
    }));
    els.sortButtons.forEach((button) => button.addEventListener("click", () => {
      if (state.sort === button.dataset.sort) state.direction = state.direction === "asc" ? "desc" : "asc";
      else { state.sort = button.dataset.sort; state.direction = "asc"; }
      state.page = 1;
      render();
    }));
    els.catalogBody.addEventListener("click", (event) => {
      if (event.target.closest(".row-open")) return;
      const row = event.target.closest("[data-record-id]");
      if (row) selectRecord(row.dataset.recordId, row);
    });
    els.catalogBody.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      const row = event.target.closest("[data-record-id]");
      if (!row) return;
      event.preventDefault();
      selectRecord(row.dataset.recordId, row);
    });
    els.pagination.addEventListener("click", (event) => {
      const button = event.target.closest("[data-page]");
      if (!button || button.disabled) return;
      state.page = Number(button.dataset.page);
      render();
      byId("catalog-results")?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    });
    els.directoryTree.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-tree-toggle]");
      if (toggle && !toggle.disabled) {
        const path = toggle.dataset.treeToggle;
        if (ui.expandedPaths.has(path) && path) ui.expandedPaths.delete(path); else ui.expandedPaths.add(path);
        renderTreeView();
        return;
      }
      const select = event.target.closest("[data-tree-select]");
      if (select) selectPath(select.dataset.treeSelect);
    });
    els.directoryTree.addEventListener("keydown", (event) => {
      const row = event.target.closest(".tree-row");
      if (!row) return;
      const path = row.dataset.treePath;
      const visibleRows = Array.from(els.directoryTree.querySelectorAll(".tree-row"));
      const index = visibleRows.indexOf(row);
      if (event.key === "ArrowDown" && index < visibleRows.length - 1) { event.preventDefault(); focusTreePath(visibleRows[index + 1].dataset.treePath); }
      else if (event.key === "ArrowUp" && index > 0) { event.preventDefault(); focusTreePath(visibleRows[index - 1].dataset.treePath); }
      else if (event.key === "Home") { event.preventDefault(); focusTreePath(visibleRows[0].dataset.treePath); }
      else if (event.key === "End") { event.preventDefault(); focusTreePath(visibleRows.at(-1).dataset.treePath); }
      else if (event.key === "ArrowRight") {
        const children = childDirectories.get(path) || [];
        if (children.length) {
          event.preventDefault();
          if (!ui.expandedPaths.has(path)) { ui.expandedPaths.add(path); focusTreePath(path); }
          else focusTreePath(children[0].path);
        }
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (ui.expandedPaths.has(path) && path) { ui.expandedPaths.delete(path); focusTreePath(path); }
        else focusTreePath(parentPath(path));
      } else if (["Enter", " "].includes(event.key)) { event.preventDefault(); selectPath(path); }
    });
    els.treeChildFolders.addEventListener("click", (event) => {
      const button = event.target.closest("[data-tree-folder]");
      if (button) selectPath(button.dataset.treeFolder);
    });
    els.treeFiles.addEventListener("click", (event) => {
      const button = event.target.closest("[data-tree-file]");
      if (button) selectRecord(button.dataset.treeFile, button);
    });
    els.treeRootButton.addEventListener("click", () => selectPath(""));
    els.treeCollapseButton.addEventListener("click", () => { ui.expandedPaths = new Set([""]); ui.treeFocusPath = ""; renderTreeView(); focusTreePath(""); });
    els.visualFolderGrid.addEventListener("click", (event) => {
      const button = event.target.closest("[data-visual-folder]");
      if (button) selectPath(button.dataset.visualFolder);
    });
    els.ancestorRail.addEventListener("click", (event) => {
      const button = event.target.closest("[data-ancestor-path]");
      if (button) selectPath(button.dataset.ancestorPath);
    });
    els.currentFolderBanner.addEventListener("click", (event) => {
      const button = event.target.closest("[data-parent-folder]");
      if (button) selectPath(button.dataset.parentFolder);
    });
    els.visualFiles.addEventListener("click", (event) => {
      const button = event.target.closest("[data-visual-file]");
      if (button) selectRecord(button.dataset.visualFile, button);
    });
    els.showAllFolders.addEventListener("click", () => {
      const available = (childDirectories.get(state.path) || []).length;
      ui.folderLimit = ui.folderLimit >= available ? 12 : available;
      renderVisualView();
    });
    els.showMoreFiles.addEventListener("click", () => { ui.fileLimit += 24; renderVisualView(); });
    els.layoutButtons.forEach((button) => button.addEventListener("click", () => { state.visualLayout = button.dataset.layout; renderVisualView(); syncControls(); writeHashState(); }));
    els.inspectorTabs.forEach((button) => {
      button.addEventListener("click", () => { ui.inspectorTab = button.dataset.inspectorTab; renderInspector(); });
      button.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const visibleTabs = els.inspectorTabs.filter((tab) => !tab.hidden);
        const index = visibleTabs.indexOf(button);
        let nextIndex = index;
        if (event.key === "ArrowLeft") nextIndex = (index - 1 + visibleTabs.length) % visibleTabs.length;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % visibleTabs.length;
        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = visibleTabs.length - 1;
        visibleTabs[nextIndex].click();
        visibleTabs[nextIndex].focus();
      });
    });
    els.cloudAction.addEventListener("click", (event) => {
      const record = recordById.get(state.selectedId);
      if (!record?.cloud?.app) {
        event.preventDefault();
        return;
      }
      if (!record.cloud.available || !record.cloud.launch_url) {
        event.preventDefault();
        return;
      }
      const message = record.cloud.copy_mode === "save_copy_guidance"
        ? "Opening Colab. Save a personal Drive copy before editing."
        : `Opening a personal ${cloudAppName(record)} copy.`;
      showToast(message);
    });
    els.closeInspector.addEventListener("click", () => closeInspector());
    els.copyUrl.addEventListener("click", () => {
      const record = recordById.get(state.selectedId);
      if (isWebApp(record)) copyText(record.web_app.url, "URL copied to clipboard.");
    });
    els.webAppAction.addEventListener("click", () => showToast("Opening web app in a new tab."));
    els.overviewButton.addEventListener("click", () => {
      renderOverview();
      if (typeof els.overviewDialog.showModal === "function") els.overviewDialog.showModal(); else els.overviewDialog.setAttribute("open", "");
    });
    els.closeOverview.addEventListener("click", () => els.overviewDialog.close());
    els.overviewDialog.addEventListener("click", (event) => { if (event.target === els.overviewDialog) els.overviewDialog.close(); });
    els.mobileMenu.addEventListener("click", () => {
      const open = !els.sidebar.classList.contains("is-open");
      els.sidebar.classList.toggle("is-open", open);
      els.mobileMenu.setAttribute("aria-expanded", String(open));
      els.mobileScrim.hidden = !open;
    });
    els.mobileScrim.addEventListener("click", closeMobileNavigation);
    document.addEventListener("keydown", (event) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if ((event.key === "/" && !typing) || (event.key.toLocaleLowerCase() === "k" && (event.ctrlKey || event.metaKey))) {
        event.preventDefault();
        els.search.focus();
      }
      if (event.key === "Escape") {
        if (state.selectedId) closeInspector();
        if (els.overviewDialog.open) els.overviewDialog.close();
        closeMobileNavigation();
      }
    });
    window.addEventListener("hashchange", () => { readHashState(); updateTopicOptions(); render(); });
  }

  populateFilters();
  readHashState();
  updateTopicOptions();
  renderSummary();
  bindEvents();
  render();
})();
