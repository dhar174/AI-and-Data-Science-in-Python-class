"""Apply the public denylist without reading the offline source catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from export_public_catalog import (
    filter_public_catalog,
    load_denylist,
    write_catalog_payload,
)


def apply_denylist(catalog_path, denylist_path, json_output, js_output):
    catalog_path = Path(catalog_path)
    source = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    denylist = load_denylist(denylist_path)
    payload = filter_public_catalog(source, denylist)
    write_catalog_payload(payload, json_output, js_output)
    return payload, denylist


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/course-catalog.json"))
    parser.add_argument("--denylist", type=Path, default=Path("data/public-denylist.json"))
    parser.add_argument("--json-output", type=Path, default=Path("data/course-catalog.json"))
    parser.add_argument("--js-output", type=Path, default=Path("data/catalog-data.js"))
    args = parser.parse_args(argv)
    before = json.loads(args.catalog.read_text(encoding="utf-8-sig"))
    payload, denylist = apply_denylist(
        args.catalog,
        args.denylist,
        args.json_output,
        args.js_output,
    )
    print(
        f"Applied {len(denylist)} denylisted ID(s); removed "
        f"{len(before.get('records', [])) - len(payload['records'])} record(s)."
    )
    print(
        f"Public catalog now contains {payload['summary']['total_files']} files + "
        f"{payload['summary']['total_web_apps']} web apps = "
        f"{payload['summary']['total_resources']} records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
