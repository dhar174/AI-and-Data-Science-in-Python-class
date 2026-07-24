"""Export a curated, path-safe catalog for the public course portal."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


GOOGLE_HOSTS = frozenset(
    {
        "colab.research.google.com",
        "docs.google.com",
        "drive.google.com",
        "sheets.google.com",
        "slides.google.com",
    }
)
GOOGLE_RESOURCE_PREFIXES = {
    "drive.google.com": (("file", "d"),),
    "docs.google.com": (
        ("document", "d"),
        ("presentation", "d"),
        ("spreadsheets", "d"),
    ),
    "colab.research.google.com": (("drive",),),
    "sheets.google.com": (("d",),),
    "slides.google.com": (("d",),),
}
GOOGLE_SOURCE_SUFFIXES = {
    "drive.google.com": frozenset({"", "view", "preview"}),
    "docs.google.com": frozenset({"", "view", "edit", "preview"}),
    "colab.research.google.com": frozenset({""}),
    "sheets.google.com": frozenset({"", "view", "edit", "preview"}),
    "slides.google.com": frozenset({"", "view", "edit", "preview"}),
}
GOOGLE_LAUNCH_SUFFIXES = {
    **GOOGLE_SOURCE_SUFFIXES,
    "docs.google.com": GOOGLE_SOURCE_SUFFIXES["docs.google.com"] | {"copy"},
    "sheets.google.com": GOOGLE_SOURCE_SUFFIXES["sheets.google.com"] | {"copy"},
    "slides.google.com": GOOGLE_SOURCE_SUFFIXES["slides.google.com"] | {"copy"},
}
GOOGLE_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
ENCODED_PATH_HAZARD_RE = re.compile(r"%(?:2E|2F|5C)", re.IGNORECASE)
BACKTICK_LOCAL_RE = re.compile(
    r"(?i)`(?=[^`\r\n]*(?:file:/|[A-Z]:[\\/]|\\\\|"
    r"(?:drive_folder|local_path|upload_path):))[^`\r\n]*`"
)
FILE_URL_RE = re.compile(r"(?i)(?<![A-Za-z0-9])file:/{1,3}[^\s`\"'<>,;]+")
WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s`\"'<>,;]+"
)
UNC_PATH_RE = re.compile(r"(?<!\\)\\\\[^\s`\"'<>,;]+")
SOURCE_MARKER_RE = re.compile(
    r"(?i)\b(?:drive_folder|local_path|upload_path):[^\s`\"'<>,;]+"
)
SECRET_TOKEN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{30,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{35}|"
    r"xox[baprs]-[0-9A-Za-z-]{20,}"
    r")"
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

PUBLIC_FILE_FIELDS = frozenset(
    {
        "action",
        "audience",
        "audience_normalized",
        "bundle_id",
        "catalog_path",
        "classification_basis",
        "cloud",
        "confidence",
        "dependency_sensitive",
        "dependency_status",
        "display_name",
        "duplicate_group",
        "extension",
        "id",
        "is_review",
        "item_type",
        "modified_utc",
        "module",
        "name",
        "preview_text",
        "preview_truncated",
        "resource_kind",
        "search_text",
        "sha256",
        "size_bytes",
        "status",
        "topic",
    }
)
PUBLIC_WEB_APP_FIELDS = frozenset(
    {
        "audience",
        "audience_normalized",
        "catalog_path",
        "id",
        "is_review",
        "item_type",
        "module",
        "name",
        "resource_kind",
        "search_text",
        "status",
        "topic",
        "web_app",
    }
)
PUBLIC_CLOUD_FIELDS = frozenset(
    {
        "app",
        "available",
        "copy_mode",
        "launch_url",
        "mime_type",
        "provider",
        "reason",
        "source_url",
        "status",
    }
)
PUBLIC_WEB_APP_DETAIL_FIELDS = frozenset(
    {"description", "last_checked_utc", "link_status", "service_name", "url"}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def forbidden_public_text_kind(value) -> str | None:
    """Classify local/upload content that cannot appear in public strings."""
    if not isinstance(value, str):
        return None
    if FILE_URL_RE.search(value):
        return "file_url"
    if WINDOWS_PATH_RE.search(value) or UNC_PATH_RE.search(value):
        return "windows_path"
    if SOURCE_MARKER_RE.search(value):
        return "source_marker"
    if SECRET_TOKEN_RE.search(value) or PRIVATE_KEY_RE.search(value):
        return "secret"
    return None


def contains_forbidden_public_text(value) -> bool:
    return forbidden_public_text_kind(value) is not None


def sanitize_public_text(value) -> str:
    """Redact local/upload references while retaining surrounding course text."""
    if not isinstance(value, str):
        return ""
    text = BACKTICK_LOCAL_RE.sub("`[local reference removed]`", value)
    text = FILE_URL_RE.sub("[file URL removed]", text)
    text = WINDOWS_PATH_RE.sub("[local path removed]", text)
    text = UNC_PATH_RE.sub("[local path removed]", text)
    text = SOURCE_MARKER_RE.sub("[source reference removed]", text)
    text = SECRET_TOKEN_RE.sub("[secret removed]", text)
    return PRIVATE_KEY_RE.sub("[secret removed]", text)


def _safe_text(value, default=""):
    return sanitize_public_text(value if isinstance(value, str) else default)


def _is_https_url(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme.lower() == "https"
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


def normalize_google_url(value, *, context="source") -> str | None:
    """Return a canonical Google resource URL, or None when it is invalid."""
    if context not in {"source", "launch"}:
        raise ValueError(f"Unsupported Google URL context: {context!r}")
    if not _is_https_url(value) or contains_forbidden_public_text(value):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if (
        host not in GOOGLE_RESOURCE_PREFIXES
        or port is not None
        or parts.netloc.lower() != host
        or not parts.path.startswith("/")
        or "\\" in parts.path
        or "//" in parts.path
        or ENCODED_PATH_HAZARD_RE.search(parts.path)
    ):
        return None
    path_segments = parts.path.strip("/").split("/")
    if (
        not path_segments
        or any(not segment or segment in {".", ".."} for segment in path_segments)
    ):
        return None
    canonical_segments = []
    index = 0
    while index < len(path_segments):
        if (
            path_segments[index] == "u"
            and index + 1 < len(path_segments)
            and path_segments[index + 1].isdigit()
        ):
            index += 2
            continue
        canonical_segments.append(path_segments[index])
        index += 1
    allowed_suffixes = (
        GOOGLE_LAUNCH_SUFFIXES if context == "launch" else GOOGLE_SOURCE_SUFFIXES
    )[host]
    for prefix in GOOGLE_RESOURCE_PREFIXES[host]:
        id_index = len(prefix)
        if (
            tuple(canonical_segments[:id_index]) != prefix
            or len(canonical_segments) <= id_index
        ):
            continue
        resource_id = canonical_segments[id_index]
        if not GOOGLE_RESOURCE_ID_RE.fullmatch(resource_id):
            return None
        suffix_segments = canonical_segments[id_index + 1 :]
        if len(suffix_segments) > 1:
            return None
        suffix = suffix_segments[0] if suffix_segments else ""
        if suffix not in allowed_suffixes:
            return None
        canonical_path = "/" + "/".join(
            segment for segment in (*prefix, resource_id, suffix) if segment
        )
        return urlunsplit(("https", host, canonical_path, "", ""))
    return None


def is_safe_catalog_path(value) -> bool:
    """Return whether a logical catalog path is relative and traversal-free."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or contains_forbidden_public_text(value)
    ):
        return False
    if value.startswith("/") or URI_SCHEME_RE.match(value):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _search_text(*values) -> str:
    text = " ".join(
        str(value).strip()
        for value in values
        if value not in (None, "", False)
    ).lower()
    return sanitize_public_text(text)


def _sanitize_preview_text(value) -> str:
    return _safe_text(value)


def _file_is_public(record) -> bool:
    cloud = record.get("cloud")
    return (
        record.get("resource_kind") == "file"
        and record.get("audience_normalized") in {"Student", "Shared"}
        and record.get("status") == "Organized"
        and isinstance(cloud, dict)
        and cloud.get("status") == "verified"
        and normalize_google_url(cloud.get("source_url"), context="source") is not None
        and is_safe_catalog_path(record.get("catalog_path"))
    )


def _sanitize_file(record) -> dict:
    cloud = record["cloud"]
    source_url = normalize_google_url(cloud.get("source_url"), context="source")
    launch_url = (
        normalize_google_url(cloud.get("launch_url"), context="launch") or ""
    )
    app = _safe_text(cloud.get("app"))
    available = bool(cloud.get("available") and launch_url)
    public_cloud = {
        "provider": _safe_text(cloud.get("provider"), "google_drive"),
        "status": "verified",
        "source_url": source_url,
        "mime_type": _safe_text(cloud.get("mime_type")),
        "app": app,
        "launch_url": launch_url,
        "copy_mode": _safe_text(cloud.get("copy_mode"), "none"),
        "available": available,
        "reason": (
            "Verified Google app link available."
            if available
            else "Verified Google Drive link available."
        ),
    }
    public = {
        "id": _safe_text(record.get("id")),
        "name": _safe_text(record.get("name")),
        "display_name": _safe_text(record.get("display_name")) or _safe_text(record.get("name")),
        "resource_kind": "file",
        "catalog_path": record["catalog_path"],
        "extension": _safe_text(record.get("extension")),
        "size_bytes": record.get("size_bytes") if isinstance(record.get("size_bytes"), int) else 0,
        "modified_utc": _safe_text(record.get("modified_utc")),
        "sha256": _safe_text(record.get("sha256")),
        "module": _safe_text(record.get("module")),
        "topic": _safe_text(record.get("topic")),
        "item_type": _safe_text(record.get("item_type")),
        "audience": _safe_text(record.get("audience")),
        "audience_normalized": record["audience_normalized"],
        "bundle_id": _safe_text(record.get("bundle_id")),
        "classification_basis": _safe_text(record.get("classification_basis")),
        "confidence": _safe_text(record.get("confidence")),
        "dependency_status": _safe_text(record.get("dependency_status")),
        "dependency_sensitive": bool(record.get("dependency_sensitive")),
        "duplicate_group": _safe_text(record.get("duplicate_group")),
        "action": _safe_text(record.get("action")),
        "status": "Organized",
        "is_review": bool(record.get("is_review")),
        "preview_text": _sanitize_preview_text(record.get("preview_text")),
        "preview_truncated": bool(record.get("preview_truncated")),
        "cloud": public_cloud,
    }
    public["search_text"] = _search_text(
        public["name"],
        public["display_name"],
        public["catalog_path"],
        public["module"],
        public["topic"],
        public["item_type"],
        public["audience_normalized"],
        public["status"],
        public["extension"],
        public["dependency_status"],
        public["classification_basis"],
        public["cloud"]["app"],
        public["cloud"]["status"],
    )
    return public


def web_app_is_approved(record) -> bool:
    """Return whether a catalog web app meets the approved public contract."""
    details = record.get("web_app")
    return (
        record.get("resource_kind") == "web_app"
        and record.get("status") == "Available"
        and record.get("audience_normalized") == "Student"
        and record.get("is_review") is False
        and isinstance(details, dict)
        and details.get("link_status") == "available"
        and _is_https_url(details.get("url"))
        and not contains_forbidden_public_text(details.get("url"))
        and is_safe_catalog_path(record.get("catalog_path"))
    )


def _sanitize_web_app(record) -> dict:
    details = record["web_app"]
    public_details = {
        "service_name": _safe_text(details.get("service_name")),
        "url": details["url"],
        "description": _safe_text(details.get("description")),
        "link_status": _safe_text(details.get("link_status")),
        "last_checked_utc": _safe_text(details.get("last_checked_utc")),
    }
    public = {
        "id": _safe_text(record.get("id")),
        "name": _safe_text(record.get("name")),
        "resource_kind": "web_app",
        "catalog_path": record["catalog_path"],
        "module": _safe_text(record.get("module")),
        "topic": _safe_text(record.get("topic")),
        "item_type": _safe_text(record.get("item_type")),
        "audience": _safe_text(record.get("audience")),
        "audience_normalized": _safe_text(record.get("audience_normalized")),
        "status": _safe_text(record.get("status")),
        "is_review": bool(record.get("is_review")),
        "web_app": public_details,
    }
    public["search_text"] = _search_text(
        public["name"],
        public_details["service_name"],
        public_details["url"],
        public_details["description"],
        public["catalog_path"],
        public["module"],
        public["topic"],
        public["item_type"],
        public["audience_normalized"],
        public["status"],
        "web app",
    )
    return public


def record_parent_path(record) -> str:
    return record["catalog_path"].rsplit("/", 1)[0] if "/" in record["catalog_path"] else ""


def parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _directory_id(path: str) -> str:
    if not path:
        return "dir-root"
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    return f"dir-{digest}"


def derive_directories(records) -> list[dict]:
    paths = set()
    for record in records:
        parts = record["catalog_path"].split("/")
        for index in range(1, len(parts)):
            paths.add("/".join(parts[:index]))
    all_paths = ["", *sorted(paths, key=lambda value: (value.casefold(), value))]
    directories = []
    for path in all_paths:
        prefix = f"{path}/" if path else ""
        direct_records = [record for record in records if record_parent_path(record) == path]
        descendants = [
            record
            for record in records
            if not path or record["catalog_path"].startswith(prefix)
        ]
        direct_files = sum(record["resource_kind"] == "file" for record in direct_records)
        descendant_files = sum(record["resource_kind"] == "file" for record in descendants)
        direct_apps = sum(record["resource_kind"] == "web_app" for record in direct_records)
        descendant_apps = sum(record["resource_kind"] == "web_app" for record in descendants)
        parts = path.split("/") if path else []
        directories.append(
            {
                "id": _directory_id(path),
                "path": path,
                "name": parts[-1] if parts else "Course Library",
                "parent_path": parent_path(path) if path else None,
                "depth": len(parts),
                "physical_exists": True,
                "direct_file_count": direct_files,
                "descendant_file_count": descendant_files,
                "direct_web_app_count": direct_apps,
                "descendant_web_app_count": descendant_apps,
                "direct_resource_count": len(direct_records),
                "descendant_resource_count": len(descendants),
                "child_folder_count": sum(
                    bool(candidate) and parent_path(candidate) == path
                    for candidate in all_paths
                ),
            }
        )
    return directories


def _counts(records, field, *, kind=None) -> dict[str, int]:
    values = Counter(
        record.get(field)
        for record in records
        if (kind is None or record["resource_kind"] == kind) and record.get(field)
    )
    return dict(sorted(values.items(), key=lambda item: (item[0].casefold(), item[0])))


def derive_summary(
    records,
    directories,
    *,
    catalog_version,
    generated_utc,
    source_sha256,
) -> dict:
    files = [record for record in records if record["resource_kind"] == "file"]
    apps = [record for record in records if record["resource_kind"] == "web_app"]
    return {
        "catalog_version": catalog_version,
        "delivery_mode": "public",
        "generated_utc": generated_utc,
        "source_catalog_sha256": source_sha256.upper(),
        "total_files": len(files),
        "total_web_apps": len(apps),
        "total_resources": len(records),
        "directory_count": max(0, len(directories) - 1),
        "max_directory_depth": max((directory["depth"] for directory in directories), default=0),
        "module_counts": _counts(records, "module", kind="file"),
        "resource_module_counts": _counts(records, "module"),
        "item_type_counts": _counts(records, "item_type"),
    }


def build_public_catalog(source_catalog, source_sha256, generated_utc=None):
    """Build a public payload exclusively from explicitly allowlisted fields."""
    source_records = source_catalog.get("records")
    if not isinstance(source_records, list):
        raise ValueError("Source catalog must contain a records array.")
    records = []
    for record in source_records:
        if not isinstance(record, dict):
            continue
        if _file_is_public(record):
            records.append(_sanitize_file(record))
        elif web_app_is_approved(record):
            records.append(_sanitize_web_app(record))
    directories = derive_directories(records)
    source_summary = source_catalog.get("summary")
    source_version = (
        source_summary.get("catalog_version")
        if isinstance(source_summary, dict)
        else None
    )
    catalog_version = source_version if isinstance(source_version, int) else 4
    timestamp = _safe_text(generated_utc or _utc_now())
    summary = derive_summary(
        records,
        directories,
        catalog_version=catalog_version,
        generated_utc=timestamp,
        source_sha256=source_sha256,
    )
    return {"summary": summary, "directories": directories, "records": records}


def export_catalog(source_path, json_path, js_path, generated_utc=None):
    source_path = Path(source_path)
    json_path = Path(json_path)
    js_path = Path(js_path)
    source_bytes = source_path.read_bytes()
    source_catalog = json.loads(source_bytes.decode("utf-8-sig"))
    payload = build_public_catalog(
        source_catalog,
        hashlib.sha256(source_bytes).hexdigest().upper(),
        generated_utc=generated_utc,
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    js_path.write_bytes(
        (
            "window.COURSE_LIBRARY_DATA="
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + ";\n"
        ).encode("utf-8")
    )
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source course-catalog.json")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("data/course-catalog.json"),
    )
    parser.add_argument(
        "--js-output",
        type=Path,
        default=Path("data/catalog-data.js"),
    )
    args = parser.parse_args(argv)
    payload = export_catalog(args.source, args.json_output, args.js_output)
    summary = payload["summary"]
    print(
        f"Exported {summary['total_files']} files + "
        f"{summary['total_web_apps']} web apps = "
        f"{summary['total_resources']} public records."
    )
    print(f"JSON: {args.json_output}")
    print(f"JS:   {args.js_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
