#!/usr/bin/env python3
"""Fail closed when the static GitHub Pages checkout contains private/local references."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED_FILES = (
    ".nojekyll",
    "README.md",
    "index.html",
    "class-plan.html",
    "student-guides.html",
    "student-day-01.html",
    "student-day-02.html",
    "student-guides.css",
    "student-guides.js",
    "styles.css",
    "app.js",
    "data/catalog-data.js",
    "data/course-catalog.json",
)
DEPLOYABLE_TEXT = (
    "README.md",
    "index.html",
    "class-plan.html",
    "student-guides.html",
    "student-day-01.html",
    "student-day-02.html",
    "student-guides.css",
    "student-guides.js",
    "styles.css",
    "app.js",
)
FORBIDDEN_UI = (
    'data-mode="Instructor"',
    "Archive &amp; Review",
    'id="openFile"',
    'id="openFolder"',
    'id="copyPath"',
    'id="cloudGuideDialog"',
    "Copy local path",
    "Upload to a Google app",
    "record.absolute_path",
    "recordAbsolutePath",
    "recordFolderHref",
    "directoryHref",
    "showCloudGuide",
    "Google link source",
    "Absolute path",
    "Review note",
)
FORBIDDEN_CATALOG_KEYS = {
    "absolute_path",
    "file_uri",
    "folder_uri",
    "library_root_uri",
    "review_note",
    "upload_guidance",
    "local_path",
    "local_uri",
    "drive_audit_note",
    "drive_source_note",
}
BINARY_SUFFIXES = {
    ".7z", ".aac", ".avi", ".bmp", ".doc", ".docx", ".exe", ".flac", ".gif",
    ".gz", ".jpeg", ".jpg", ".m4a", ".m4v", ".mov", ".mp3", ".mp4", ".ogg",
    ".ogv", ".pdf", ".png", ".ppt", ".pptx", ".rar", ".tar", ".wav", ".webm",
    ".webp", ".xls", ".xlsx", ".zip",
}
WINDOWS_PATH = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/](?!/)|\\\\[^\\/\s]+[\\/])")
FILE_URL = re.compile(r"(?i)\bfile:(?:/{1,3}|\\)")
EXPECTED_CLASS_PLAN_SOURCE_HASHES = {
    "schedule-sha256": "4d832a648d386cad52ded0f4fb87ffeed7fc7bc040a36b6651e428f13f888b80",
    "syllabus-sha256": "834e1831762ab00aa683087bfb1d276ddc4788849d6c38a62211787d22275cfa",
}
EXPECTED_CLASS_PLAN_SHA256 = "33ada3e93ba1fa7e3f496d2ce20cbfb699fd1610ef1b9f36cdf77b41573929f3"
EXPECTED_DAY_ONE_PHASES = (
    ("orientation", "5:30–6:10 p.m."),
    ("analytic-approaches", "6:10–6:35 p.m."),
    ("guided-practice", "6:35–7:25 p.m."),
    ("capstone-domains", "7:25–7:55 p.m."),
    ("break", "7:55–8:25 p.m."),
    ("case-study-lab", "8:25–9:20 p.m."),
    ("assessment", "9:20–9:50 p.m."),
    ("exit", "9:50–10:00 p.m."),
)
EXPECTED_DAY_TWO_PHASES = (
    ("storytelling-bridge", "5:30–5:50 p.m."),
    ("python-launch", "5:50–6:10 p.m."),
    ("values-tracing", "6:10–6:40 p.m."),
    ("control-flow-functions", "6:40–7:10 p.m."),
    ("clean-mean", "7:10–7:35 p.m."),
    ("diagnostic", "7:35–7:55 p.m."),
    ("break", "7:55–8:25 p.m."),
    ("pyquest", "8:25–9:20 p.m."),
    ("debug-mini-script", "9:20–9:45 p.m."),
    ("exit", "9:45–10:00 p.m."),
)
STUDENT_GUIDE_EXTERNAL_HOSTS = {
    "drive.google.com",
    "docs.google.com",
    "colab.research.google.com",
    "data-storyteller-quest-ue4r4kw7oq-ue.a.run.app",
    "pyquest-ue4r4kw7oq-uw.a.run.app",
    "python-quest-ue4r4kw7oq-uw.a.run.app",
}
STUDENT_GUIDE_FORBIDDEN = (
    "retrieval_questions",
    "worked_example",
    "modelling_steps",
    "hinge_question",
    "hinge_rule",
    "required_resource_ids",
    "featured_optional_ids",
    "absolute_path",
    "relative_path",
    "review_note",
    "Instructor-only",
)


class ClassPlanNavigationParser(HTMLParser):
    """Collect real target anchors and whether they occur in the Views section."""

    def __init__(self, target_href: str = "class-plan.html") -> None:
        super().__init__(convert_charrefs=True)
        self.target_href = target_href
        self.section_stack: list[bool] = []
        self.anchors: list[dict[str, object]] = []
        self.current_anchor: dict[str, object] | None = None
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "section":
            values = dict(attrs)
            classes = (values.get("class") or "").split()
            is_views = "nav-group" in classes and values.get("aria-labelledby") == "viewsLabel"
            self.section_stack.append(is_views)
            return
        if tag != "a":
            return
        seen: set[str] = set()
        duplicate_names: set[str] = set()
        for name, _value in attrs:
            if name in seen:
                duplicate_names.add(name)
            seen.add(name)
        if duplicate_names:
            self.errors.append(
                "index.html anchor contains duplicate attribute name(s): "
                + ", ".join(sorted(duplicate_names))
            )
            self.current_anchor = None
            return
        values = dict(attrs)
        if values.get("href") == self.target_href:
            anchor: dict[str, object] = {
                "attrs": values,
                "inside_views": any(self.section_stack),
                "text": "",
            }
            self.anchors.append(anchor)
            self.current_anchor = anchor

    def handle_data(self, data: str) -> None:
        if self.current_anchor is not None:
            self.current_anchor["text"] = str(self.current_anchor["text"]) + data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current_anchor = None
        if tag == "section" and self.section_stack:
            self.section_stack.pop()


def validate_navigation_link(index_html: str, href: str, label: str) -> list[str]:
    parser = ClassPlanNavigationParser(href)
    parser.feed(index_html)
    parser.close()
    errors = list(parser.errors)
    if len(parser.anchors) != 1:
        errors.append(f"index.html must contain exactly one {href} link")
    views_anchors = [anchor for anchor in parser.anchors if anchor["inside_views"]]
    if len(views_anchors) != 1:
        errors.append(f"index.html {href} link must appear exactly once inside Views")
    if len(parser.anchors) == 1:
        anchor = parser.anchors[0]
        attrs = anchor["attrs"]
        assert isinstance(attrs, dict)
        if label not in " ".join(str(anchor["text"]).split()):
            errors.append(f"index.html {label} navigation text is missing")
        classes = (attrs.get("class") or "").split()
        style = (attrs.get("style") or "").replace(" ", "").casefold()
        if "nav-item" not in classes or "text-decoration:none" not in style:
            errors.append(f"{label} navigation must use local nav-item styling")
        if "data-view" in attrs:
            errors.append(f"{label} navigation must not use data-view")
    return errors


def validate_class_plan_navigation(index_html: str) -> list[str]:
    return validate_navigation_link(index_html, "class-plan.html", "Class Plan & Schedule")


def validate_student_guides_navigation(index_html: str) -> list[str]:
    return validate_navigation_link(index_html, "student-guides.html", "Student Day Guides")


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                self.assets.append((attribute, value))


class StudentGuideContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.day_entries: list[dict[str, object]] = []
        self.current_day: dict[str, object] | None = None
        self.phases: list[dict[str, object]] = []
        self.current_phase: dict[str, object] | None = None
        self.in_summary = False
        self.external_links: list[dict[str, str | None]] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [name for name, _value in attrs]
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        if duplicates:
            self.errors.append(
                "student guide contains duplicate attribute name(s): "
                + ", ".join(duplicates)
            )
            return
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "li" and "day-entry" in classes:
            self.current_day = {"text": "", "statuses": set(), "hrefs": []}
        elif self.current_day is not None and tag == "span":
            statuses = self.current_day["statuses"]
            assert isinstance(statuses, set)
            statuses.update(classes & {"ready", "soon"})
        if self.current_day is not None and tag == "a" and values.get("href"):
            hrefs = self.current_day["hrefs"]
            assert isinstance(hrefs, list)
            hrefs.append(values["href"])
        if tag == "details" and "phase-card" in classes:
            self.current_phase = {
                "id": values.get("id"),
                "classes": classes,
                "summary": "",
            }
        elif self.current_phase is not None and tag == "summary":
            self.in_summary = True
        href = values.get("href")
        if tag == "a" and href and href.startswith("https://"):
            self.external_links.append(values)

    def handle_data(self, data: str) -> None:
        if self.current_day is not None:
            self.current_day["text"] = str(self.current_day["text"]) + " " + data
        if self.current_phase is not None and self.in_summary:
            self.current_phase["summary"] = str(self.current_phase["summary"]) + " " + data

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self.current_day is not None:
            self.day_entries.append(self.current_day)
            self.current_day = None
        elif tag == "summary":
            self.in_summary = False
        elif tag == "details" and self.current_phase is not None:
            self.phases.append(self.current_phase)
            self.current_phase = None


def parse_student_guide(document: str) -> StudentGuideContractParser:
    parser = StudentGuideContractParser()
    parser.feed(document)
    parser.close()
    return parser


def validate_student_guides_hub(document: str) -> list[str]:
    parser = parse_student_guide(document)
    errors = list(parser.errors)
    if len(parser.day_entries) != 33:
        errors.append("student-guides.html must contain exactly 33 day entries")
        return errors
    day_numbers = []
    for entry in parser.day_entries:
        match = re.search(r"\bDay\s+(\d+)\b", " ".join(str(entry["text"]).split()))
        day_numbers.append(int(match.group(1)) if match else None)
    if day_numbers != list(range(1, 34)):
        errors.append("student-guides.html day entries must be ordered Day 1 through Day 33")
    ready = [entry for entry in parser.day_entries if "ready" in entry["statuses"]]
    soon = [entry for entry in parser.day_entries if "soon" in entry["statuses"]]
    if len(ready) != 33:
        errors.append("student-guides.html must contain exactly 33 Ready days")
    if soon:
        errors.append("student-guides.html must not contain Coming soon days")
    expected_links = [f"student-day-{number:02d}.html" for number in range(1, 34)]
    actual_links = [entry["hrefs"][0] if entry["hrefs"] else "" for entry in parser.day_entries]
    if actual_links != expected_links:
        errors.append("student-guides.html Ready days must link to student-day-01.html through student-day-33.html")
    return errors


def validate_student_day_one(document: str) -> list[str]:
    parser = parse_student_guide(document)
    errors = list(parser.errors)
    expected_ids = [phase_id for phase_id, _time_range in EXPECTED_DAY_ONE_PHASES]
    actual_ids = [phase["id"] for phase in parser.phases]
    if actual_ids != expected_ids:
        errors.append("student-day-01.html must contain the eight ordered Day 1 phases")
    if len(parser.phases) == len(EXPECTED_DAY_ONE_PHASES):
        for phase, (_phase_id, time_range) in zip(parser.phases, EXPECTED_DAY_ONE_PHASES):
            if time_range not in str(phase["summary"]):
                errors.append(
                    f"student-day-01.html phase {phase['id']!r} is missing time {time_range}"
                )
    break_phases = [
        phase for phase in parser.phases if "break-phase" in phase["classes"]
    ]
    if len(break_phases) != 1 or break_phases[0]["id"] != "break":
        errors.append("student-day-01.html must contain one protected break phase")
    if "Break: 7:55–8:25 p.m." not in document:
        errors.append("student-day-01.html is missing the protected break banner")
    errors.extend(validate_student_day_external_links(document, parser, "student-day-01.html", 5))
    return errors


def validate_student_day_external_links(
    document: str, parser: StudentGuideContractParser, filename: str, minimum_unique_urls: int
) -> list[str]:
    errors: list[str] = []
    unique_urls = {
        attributes["href"]
        for attributes in parser.external_links
        if attributes.get("href")
    }
    if len(unique_urls) < minimum_unique_urls:
        errors.append(f"{filename} must contain at least {minimum_unique_urls} unique external resource links")
    for attributes in parser.external_links:
        href = attributes.get("href") or ""
        host = (urlsplit(href).hostname or "").lower()
        rel = set((attributes.get("rel") or "").split())
        if host not in STUDENT_GUIDE_EXTERNAL_HOSTS:
            errors.append(f"{filename} uses an unapproved external host: {host!r}")
        if attributes.get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(rel):
            errors.append(f"{filename} external links must open safely in a new tab")
    return errors


def validate_student_day_two(document: str) -> list[str]:
    parser = parse_student_guide(document)
    errors = list(parser.errors)
    expected_ids = [phase_id for phase_id, _time_range in EXPECTED_DAY_TWO_PHASES]
    actual_ids = [phase["id"] for phase in parser.phases]
    if actual_ids != expected_ids:
        errors.append("student-day-02.html must contain the ten ordered Day 2 phases")
    if len(parser.phases) == len(EXPECTED_DAY_TWO_PHASES):
        for phase, (_phase_id, time_range) in zip(parser.phases, EXPECTED_DAY_TWO_PHASES):
            if time_range not in str(phase["summary"]):
                errors.append(
                    f"student-day-02.html phase {phase['id']!r} is missing time {time_range}"
                )
    break_phases = [
        phase for phase in parser.phases if "break-phase" in phase["classes"]
    ]
    if len(break_phases) != 1 or break_phases[0]["id"] != "break":
        errors.append("student-day-02.html must contain one protected break phase")
    if "Break: 7:55–8:25 p.m." not in document:
        errors.append("student-day-02.html is missing the protected break banner")
    for required in (
        "Data Storyteller Quest",
        "Python foundations for analysis",
        "clean_mean",
        "PyQuest",
        "alternate class activity",
        "45 minutes",
        "https://data-storyteller-quest-ue4r4kw7oq-ue.a.run.app",
        "https://pyquest-ue4r4kw7oq-uw.a.run.app",
    ):
        if required not in document:
            errors.append(f"student-day-02.html is missing its Day 2 contract: {required}")
    errors.extend(validate_student_day_external_links(document, parser, "student-day-02.html", 5))
    return errors


def catalog_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from catalog_keys(child)


def catalog_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from catalog_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from catalog_strings(child)
    elif isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from catalog_keys(child)


def verify(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")
    for number in range(2, 34):
        relative = f"student-day-{number:02d}.html"
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")

    readable = {}
    deployable = list(DEPLOYABLE_TEXT) + [f"student-day-{number:02d}.html" for number in range(2, 34)]
    for relative in deployable:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        readable[relative] = text
        if FILE_URL.search(text):
            errors.append(f"{relative}: contains a file URL")
        if WINDOWS_PATH.search(text):
            errors.append(f"{relative}: contains a Windows/UNC path")

    index = readable.get("index.html", "")
    app = readable.get("app.js", "")
    combined_ui = index + app
    for marker in FORBIDDEN_UI:
        if marker in combined_ui:
            errors.append(f"public UI contains forbidden marker: {marker}")

    for relative in (
        "index.html",
        "class-plan.html",
        "student-guides.html",
        *[f"student-day-{number:02d}.html" for number in range(1, 34)],
    ):
        parser = AssetParser()
        parser.feed(readable.get(relative, ""))
        for attribute, value in parser.assets:
            if value.startswith(("https://", "data:", "#")):
                continue
            parsed = urlsplit(value)
            if parsed.scheme or value.startswith(("/", "../")) or "/../" in value:
                errors.append(f"{relative}: unsafe {attribute} asset path: {value}")
                continue
            asset = (root / parsed.path).resolve()
            try:
                asset.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{relative}: asset escapes checkout: {value}")
                continue
            if not asset.is_file():
                errors.append(f"{relative}: referenced asset does not exist: {value}")

    errors.extend(validate_class_plan_navigation(index))
    errors.extend(validate_student_guides_navigation(index))

    student_guides = readable.get("student-guides.html", "")
    student_day_one = readable.get("student-day-01.html", "")
    student_day_two = readable.get("student-day-02.html", "")
    if student_guides:
        errors.extend(validate_student_guides_hub(student_guides))
    if student_day_one:
        errors.extend(validate_student_day_one(student_day_one))
    if student_day_two:
        errors.extend(validate_student_day_two(student_day_two))
    combined_student_guides = "\n".join(
        readable.get(relative, "")
        for relative in (
            "student-guides.html",
            *[f"student-day-{number:02d}.html" for number in range(1, 34)],
            "student-guides.css",
            "student-guides.js",
        )
    )
    for forbidden in STUDENT_GUIDE_FORBIDDEN:
        if forbidden in combined_student_guides:
            errors.append(f"student guides expose private/internal content: {forbidden}")
    if re.search(r"web-[0-9a-f]{12,}", combined_student_guides, re.IGNORECASE):
        errors.append("student guides expose an internal web activity ID")
    if re.search(r"\b[0-9a-f]{12}-\d{4}\b", combined_student_guides, re.IGNORECASE):
        errors.append("student guides expose an internal stable ID")

    class_plan = readable.get("class-plan.html", "")
    if class_plan:
        for marker in (
            'href="index.html"',
            'schedule-sha256',
            'syllabus-sha256',
            "At a glance",
            "Three-module roadmap",
            "Nine-week summary",
            "Compact 33-session schedule",
            "Daily class details",
            "Course expectations",
        ):
            if marker not in class_plan:
                errors.append(f"class-plan.html: missing required contract: {marker}")
        if class_plan.count('class="session-detail"') != 33:
            errors.append("class-plan.html: must contain exactly 33 session-detail sections")
        if "<script" in class_plan.casefold() or 'rel="stylesheet"' in class_plan.casefold() or re.search(r"\bsrc=", class_plan, re.IGNORECASE):
            errors.append("class-plan.html: must be self-contained without scripts or external assets")
        for name, expected in EXPECTED_CLASS_PLAN_SOURCE_HASHES.items():
            if f'<meta name="{name}" content="{expected}">' not in class_plan:
                errors.append(f"class-plan.html: {name} does not match the expected promoted source")
        class_plan_path = root / "class-plan.html"
        actual_class_plan_hash = hashlib.sha256(class_plan_path.read_bytes()).hexdigest()
        if actual_class_plan_hash != EXPECTED_CLASS_PLAN_SHA256:
            errors.append("class-plan.html SHA-256 does not match the deterministic approved page")
        for forbidden in (
            "retrieval_questions", "worked_example", "modelling_steps", "hinge_question", "hinge_rule",
            "required_resource_ids", "featured_optional_ids", "scheduled_resource_count",
            "scheduled_optional_count", "scheduled_instructor_count", "absolute_path", "relative_path",
            "review_note", "Instructor-only",
        ):
            if forbidden in class_plan:
                errors.append(f"class-plan.html: exposes private/internal content: {forbidden}")
        if re.search(r"web-[0-9a-f]{12,}", class_plan, re.IGNORECASE):
            errors.append("class-plan.html: exposes an internal web activity ID")
        if re.search(r"\b[0-9a-f]{12}-\d{4}\b", class_plan, re.IGNORECASE):
            errors.append("class-plan.html: exposes an internal stable ID")

    for relative in ("styles.css", "student-guides.css"):
        for value in re.findall(r"url\((?:['\"]?)([^)'\"\s]+)", readable.get(relative, "")):
            if value.startswith(("https://", "data:", "#")):
                continue
            if value.startswith(("/", "../")) or "/../" in value:
                errors.append(f"{relative}: unsafe asset path: {value}")

    catalog_path = root / "data" / "course-catalog.json"
    if catalog_path.is_file():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"data/course-catalog.json: invalid JSON: {exc}")
        else:
            leaked_keys = sorted(set(catalog_keys(catalog)) & FORBIDDEN_CATALOG_KEYS)
            if leaked_keys:
                errors.append(f"catalog contains forbidden private fields: {', '.join(leaked_keys)}")
            for value in catalog_strings(catalog):
                if FILE_URL.search(value):
                    errors.append("catalog contains a file URL")
                    break
            for value in catalog_strings(catalog):
                if WINDOWS_PATH.search(value):
                    errors.append("catalog contains a Windows/UNC path")
                    break

    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            errors.append(f"course binary must not be committed: {path.relative_to(root)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors = verify(root)
    if errors:
        print("Public-site verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Verified public GitHub Pages UI: relative assets, no local paths, no private UI, no course binaries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
