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
    "styles.css",
    "app.js",
    "data/catalog-data.js",
    "data/course-catalog.json",
)
DEPLOYABLE_TEXT = (
    "README.md",
    "index.html",
    "class-plan.html",
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
    "schedule-sha256": "3796db6c041317f195ca5c26e6a5068d5fd7f0a36513897837ff229936041dc5",
    "syllabus-sha256": "522ab70c1eca4f8d817d62702c0dd313770901666b972bdcea40a46eb9137887",
}
EXPECTED_CLASS_PLAN_SHA256 = "7e0b7e5971e14eba92915db12cb3e17e27d07b368202d5176c20c7001e29ab6e"


class ClassPlanNavigationParser(HTMLParser):
    """Collect real class-plan anchors and whether they occur in the Views section."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
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
        if values.get("href") == "class-plan.html":
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


def validate_class_plan_navigation(index_html: str) -> list[str]:
    parser = ClassPlanNavigationParser()
    parser.feed(index_html)
    parser.close()
    errors = list(parser.errors)
    if len(parser.anchors) != 1:
        errors.append("index.html must contain exactly one class-plan.html link")
    views_anchors = [anchor for anchor in parser.anchors if anchor["inside_views"]]
    if len(views_anchors) != 1:
        errors.append("index.html class-plan.html link must appear exactly once inside Views")
    if len(parser.anchors) == 1:
        anchor = parser.anchors[0]
        attrs = anchor["attrs"]
        assert isinstance(attrs, dict)
        if "Class Plan & Schedule" not in " ".join(str(anchor["text"]).split()):
            errors.append("index.html Class Plan & Schedule navigation text is missing")
        classes = (attrs.get("class") or "").split()
        style = (attrs.get("style") or "").replace(" ", "").casefold()
        if "nav-item" not in classes or "text-decoration:none" not in style:
            errors.append("Class Plan & Schedule navigation must use local nav-item styling")
        if "data-view" in attrs:
            errors.append("Class Plan & Schedule navigation must not use data-view")
    return errors


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

    readable = {}
    for relative in DEPLOYABLE_TEXT:
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

    for relative in ("index.html", "class-plan.html"):
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

    for value in re.findall(r"url\((?:['\"]?)([^)'\"\s]+)", readable.get("styles.css", "")):
        if value.startswith(("https://", "data:", "#")):
            continue
        if value.startswith(("/", "../")) or "/../" in value:
            errors.append(f"styles.css: unsafe asset path: {value}")

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
