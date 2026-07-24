#!/usr/bin/env python3
"""Fail closed when the static GitHub Pages checkout contains private/local references."""

from __future__ import annotations

import argparse
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
    "styles.css",
    "app.js",
    "data/catalog-data.js",
    "data/course-catalog.json",
)
DEPLOYABLE_TEXT = (
    "README.md",
    "index.html",
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

    parser = AssetParser()
    parser.feed(index)
    for attribute, value in parser.assets:
        if value.startswith(("https://", "data:", "#")):
            continue
        parsed = urlsplit(value)
        if parsed.scheme or value.startswith(("/", "../")) or "/../" in value:
            errors.append(f"index.html: unsafe {attribute} asset path: {value}")
            continue
        asset = (root / parsed.path).resolve()
        try:
            asset.relative_to(root.resolve())
        except ValueError:
            errors.append(f"index.html: asset escapes checkout: {value}")
            continue
        if not asset.is_file():
            errors.append(f"index.html: referenced asset does not exist: {value}")

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
