"""Verify the safety and internal consistency of a public catalog export."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from export_public_catalog import (
    GOOGLE_HOSTS,
    PUBLIC_CLOUD_FIELDS,
    PUBLIC_FILE_FIELDS,
    PUBLIC_WEB_APP_DETAIL_FIELDS,
    PUBLIC_WEB_APP_FIELDS,
    derive_directories,
    derive_summary,
    forbidden_public_text_kind,
    is_safe_catalog_path,
    normalize_google_url,
    web_app_is_approved,
)


JS_PREFIX = "window.COURSE_LIBRARY_DATA="
FORBIDDEN_FIELDS = frozenset(
    {
        "absolute_path",
        "file_id",
        "file_uri",
        "folder_uri",
        "guide_url",
        "library_root_uri",
        "local_path",
        "local_uri",
        "note",
        "physical_area",
        "relative_path",
        "review_note",
        "source",
        "upload_path",
    }
)
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def load_js_payload(path):
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(JS_PREFIX) or not text.endswith(";\n"):
        raise ValueError("JS wrapper must contain exactly window.COURSE_LIBRARY_DATA=<json>;")
    return json.loads(text[len(JS_PREFIX) : -2])


def _walk(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _check_forbidden_content(payload, errors):
    for path, key, value in _walk(payload):
        if key in FORBIDDEN_FIELDS:
            errors.append(f"{path}: forbidden field {key!r}")
        if not isinstance(value, str):
            continue
        forbidden_kind = forbidden_public_text_kind(value)
        if forbidden_kind == "file_url":
            errors.append(f"{path}: file URL is forbidden")
        elif forbidden_kind == "windows_path":
            errors.append(f"{path}: Windows path is forbidden")
        elif forbidden_kind == "source_marker":
            errors.append(f"{path}: forbidden source/upload string")
        elif forbidden_kind == "secret":
            errors.append(f"{path}: secret value is forbidden")


def _check_urls(payload, errors):
    for path, key, value in _walk(payload):
        if not (key == "url" or key.endswith("_url")):
            continue
        if key == "launch_url" and value == "":
            continue
        if not isinstance(value, str):
            errors.append(f"{path}: URL must be a string")
            continue
        try:
            parts = urlsplit(value)
        except ValueError:
            errors.append(f"{path}: invalid URL")
            continue
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            errors.append(f"{path}: non-HTTPS URL")
            continue
        if key in {"source_url", "launch_url"}:
            if parts.hostname.lower() not in GOOGLE_HOSTS:
                errors.append(f"{path}: unexpected Google host {parts.hostname!r}")
            normalized = normalize_google_url(
                value,
                context="launch" if key == "launch_url" else "source",
            )
            if normalized is None:
                errors.append(f"{path}: invalid Google resource URL")
            if parts.query or parts.fragment:
                errors.append(f"{path}: Google URL must not contain query or fragment")
            if normalized is not None and value != normalized:
                errors.append(f"{path}: Google URL is not canonical")


def _check_record_shapes(records, errors):
    ids = []
    for index, record in enumerate(records):
        path = f"$.records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{path}: record must be an object")
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{path}: record id must be a nonempty string")
        else:
            ids.append(record_id)
        if not is_safe_catalog_path(record.get("catalog_path")):
            errors.append(f"{path}.catalog_path: unsafe catalog_path")
        kind = record.get("resource_kind")
        if kind == "file":
            unexpected = set(record) - PUBLIC_FILE_FIELDS
            missing = PUBLIC_FILE_FIELDS - set(record)
            if unexpected:
                errors.append(f"{path}: fields outside file allowlist: {sorted(unexpected)}")
            if missing:
                errors.append(f"{path}: missing file fields: {sorted(missing)}")
            cloud = record.get("cloud")
            if not (
                record.get("audience_normalized") in {"Student", "Shared"}
                and record.get("status") == "Organized"
                and isinstance(cloud, dict)
                and cloud.get("status") == "verified"
                and normalize_google_url(
                    cloud.get("source_url"), context="source"
                ) is not None
            ):
                errors.append(f"{path}: noncurated file record")
            if isinstance(cloud, dict):
                unexpected_cloud = set(cloud) - PUBLIC_CLOUD_FIELDS
                missing_cloud = PUBLIC_CLOUD_FIELDS - set(cloud)
                if unexpected_cloud:
                    errors.append(
                        f"{path}.cloud: fields outside cloud allowlist: {sorted(unexpected_cloud)}"
                    )
                if missing_cloud:
                    errors.append(
                        f"{path}.cloud: missing cloud fields: {sorted(missing_cloud)}"
                    )
        elif kind == "web_app":
            unexpected = set(record) - PUBLIC_WEB_APP_FIELDS
            missing = PUBLIC_WEB_APP_FIELDS - set(record)
            if unexpected:
                errors.append(f"{path}: fields outside web-app allowlist: {sorted(unexpected)}")
            if missing:
                errors.append(f"{path}: missing web-app fields: {sorted(missing)}")
            details = record.get("web_app")
            if isinstance(details, dict):
                unexpected_details = set(details) - PUBLIC_WEB_APP_DETAIL_FIELDS
                missing_details = PUBLIC_WEB_APP_DETAIL_FIELDS - set(details)
                if unexpected_details:
                    errors.append(
                        f"{path}.web_app: fields outside web-app detail allowlist: "
                        f"{sorted(unexpected_details)}"
                    )
                if missing_details:
                    errors.append(
                        f"{path}.web_app: missing web-app detail fields: "
                        f"{sorted(missing_details)}"
                    )
            else:
                errors.append(f"{path}.web_app: web-app details must be an object")
            if not web_app_is_approved(record):
                errors.append(f"{path}: nonapproved web_app record")
        else:
            errors.append(f"{path}: unsupported resource_kind {kind!r}")
    duplicate_ids = sorted(record_id for record_id in set(ids) if ids.count(record_id) > 1)
    if duplicate_ids:
        errors.append(f"$.records: duplicate record id(s): {duplicate_ids}")


def _check_summary(payload, errors):
    summary = payload.get("summary")
    records = payload.get("records")
    directories = payload.get("directories")
    if not isinstance(summary, dict):
        errors.append("$.summary: summary must be an object")
        return
    if not isinstance(records, list) or not isinstance(directories, list):
        return
    source_sha256 = summary.get("source_catalog_sha256")
    if not isinstance(source_sha256, str) or not SHA256_RE.fullmatch(source_sha256):
        errors.append("$.summary.source_catalog_sha256: invalid SHA256")
        source_sha256 = ""
    if summary.get("delivery_mode") != "public":
        errors.append("$.summary.delivery_mode: summary mismatch")
    try:
        expected = derive_summary(
            records,
            directories,
            catalog_version=summary.get("catalog_version"),
            generated_utc=summary.get("generated_utc"),
            source_sha256=source_sha256,
        )
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"$.summary: could not recompute summary: {error}")
        return
    for key, expected_value in expected.items():
        if summary.get(key) != expected_value:
            errors.append(
                f"$.summary.{key}: summary mismatch "
                f"(expected {expected_value!r}, got {summary.get(key)!r})"
            )


def _check_directories(payload, errors):
    records = payload.get("records")
    directories = payload.get("directories")
    if not isinstance(directories, list):
        errors.append("$.directories: directories must be an array")
        return
    directory_ids = [
        directory.get("id")
        for directory in directories
        if isinstance(directory, dict) and isinstance(directory.get("id"), str)
    ]
    duplicates = sorted(
        directory_id
        for directory_id in set(directory_ids)
        if directory_ids.count(directory_id) > 1
    )
    if duplicates:
        errors.append(f"$.directories: duplicate directory id(s): {duplicates}")
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        return
    try:
        expected = derive_directories(records)
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"$.directories: could not recompute directories: {error}")
        return
    if directories != expected:
        errors.append("$.directories: directory mismatch with filtered records")


def verify_catalog(payload, js_payload=None):
    errors = []
    if not isinstance(payload, dict):
        return ["$: catalog payload must be an object"]
    if js_payload is not None and payload != js_payload:
        errors.append("$: JSON and JS payloads differ")
    records = payload.get("records")
    if not isinstance(records, list):
        errors.append("$.records: records must be an array")
        records = []
    _check_forbidden_content(payload, errors)
    _check_urls(payload, errors)
    _check_record_shapes(records, errors)
    _check_summary(payload, errors)
    _check_directories(payload, errors)
    return errors


def verify_files(json_path, js_path):
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    js_payload = load_js_payload(js_path)
    return payload, verify_catalog(payload, js_payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "json_path",
        type=Path,
        nargs="?",
        default=Path("data/course-catalog.json"),
    )
    parser.add_argument(
        "js_path",
        type=Path,
        nargs="?",
        default=Path("data/catalog-data.js"),
    )
    args = parser.parse_args(argv)
    payload, errors = verify_files(args.json_path, args.js_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Verification failed with {len(errors)} error(s).")
        return 1
    summary = payload["summary"]
    print(
        f"Verified {summary['total_files']} files + "
        f"{summary['total_web_apps']} web apps = "
        f"{summary['total_resources']} public records; "
        f"{summary['directory_count']} directories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
