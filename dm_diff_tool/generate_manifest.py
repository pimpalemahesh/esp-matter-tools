#!/usr/bin/env python3
"""Generate data_manifest.json listing every version and XML file under data_model/."""

import json
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
CATEGORIES = ("clusters", "device_types")


def build_manifest(data_dir: Path) -> dict:
    manifest = {}
    for ver_dir in data_dir.iterdir():
        if not ver_dir.is_dir() or not VERSION_RE.match(ver_dir.name):
            continue
        entry = {cat: [] for cat in CATEGORIES}
        for cat in CATEGORIES:
            cat_dir = ver_dir / cat
            if cat_dir.is_dir():
                entry[cat] = sorted(p.name for p in cat_dir.iterdir() if p.suffix == ".xml")
        manifest[ver_dir.name] = entry
    return {k: manifest[k] for k in sorted(manifest, key=lambda v: [int(n) for n in v.split(".")])}


def main() -> int:
    root = Path(__file__).resolve().parent
    data_dir = root / "data_model"
    if not data_dir.is_dir():
        print(f"error: {data_dir} not found", file=sys.stderr)
        return 1
    out = root / "data_manifest.json"
    manifest = build_manifest(data_dir)
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {out} ({len(manifest)} versions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
