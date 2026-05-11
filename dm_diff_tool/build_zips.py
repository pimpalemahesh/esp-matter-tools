#!/usr/bin/env python3
"""Build per-version zip archives from the connectedhomeip data model.

Normal mode — build and write:
    export MATTER_SDK_PATH=/path/to/connectedhomeip
    python build_zips.py

Check mode — used by CI to detect drift:
    export MATTER_SDK_PATH=/path/to/connectedhomeip
    python build_zips.py --check

    Generates zips to a temp dir, compares their contents against the
    committed data_model/zips/ files and data_manifest.json.
    Exits non-zero if any drift is detected.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
CATEGORIES = ("clusters", "device_types")


def build(src_data_dir: Path, zips_dir: Path) -> dict:
    """Build one zip per version from src_data_dir into zips_dir. Returns manifest dict."""
    zips_dir.mkdir(parents=True, exist_ok=True)

    versions = sorted(
        [d for d in src_data_dir.iterdir() if d.is_dir() and VERSION_RE.match(d.name)],
        key=lambda p: [int(n) for n in p.name.split(".")],
    )
    if not versions:
        print(
            f"error: no version directories found under {src_data_dir}", file=sys.stderr
        )
        sys.exit(1)

    manifest = {}
    for ver_dir in versions:
        zip_path = zips_dir / f"{ver_dir.name}.zip"
        entry = {cat: [] for cat in CATEGORIES}
        with zipfile.ZipFile(
            zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for cat in CATEGORIES:
                cat_dir = ver_dir / cat
                if not cat_dir.is_dir():
                    continue
                for xml_file in sorted(
                    p for p in cat_dir.iterdir() if p.suffix == ".xml"
                ):
                    zf.write(xml_file, f"{cat}/{xml_file.name}")
                    entry[cat].append(xml_file.name)
        manifest[ver_dir.name] = entry

    return manifest


def zip_contents(zip_path: Path) -> dict:
    """Return {filename: bytes} for all files in a zip."""
    with zipfile.ZipFile(zip_path) as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith("/")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="detect drift against committed files; exits non-zero if anything differs",
    )
    args = parser.parse_args()

    sdk_path = os.environ.get("MATTER_SDK_PATH")
    if not sdk_path:
        print("error: MATTER_SDK_PATH is not set", file=sys.stderr)
        print("       export MATTER_SDK_PATH=/path/to/connectedhomeip", file=sys.stderr)
        return 1

    src_data_dir = Path(sdk_path) / "data_model"
    if not src_data_dir.is_dir():
        print(
            f"error: {src_data_dir} not found — is MATTER_SDK_PATH correct?",
            file=sys.stderr,
        )
        return 1

    root = Path(__file__).resolve().parent

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            new_zips_dir = Path(tmp) / "zips"
            new_manifest = build(src_data_dir, new_zips_dir)

            committed_zips_dir = root / "data_model" / "zips"
            committed_manifest = json.loads((root / "data_manifest.json").read_text())

            drift = False

            # --- Check manifest ---
            if new_manifest != committed_manifest:
                print("data_manifest.json is out of date:")
                all_vers = sorted(
                    set(new_manifest) | set(committed_manifest),
                    key=lambda v: [int(n) for n in v.split(".")],
                )
                for v in all_vers:
                    if v not in committed_manifest:
                        print(f"  + {v}  (new version, not in committed manifest)")
                    elif v not in new_manifest:
                        print(f"  - {v}  (no longer in upstream)")
                    elif new_manifest[v] != committed_manifest[v]:
                        print(f"  ~ {v}  (file list changed)")
                drift = True

            # --- Check zip contents ---
            for ver in sorted(
                new_manifest, key=lambda v: [int(n) for n in v.split(".")]
            ):
                new_zip = new_zips_dir / f"{ver}.zip"
                committed_zip = committed_zips_dir / f"{ver}.zip"

                if not committed_zip.exists():
                    print(f"{ver}.zip missing from data_model/zips/")
                    drift = True
                    continue

                new_files = zip_contents(new_zip)
                committed_files = zip_contents(committed_zip)
                added = sorted(set(new_files) - set(committed_files))
                removed = sorted(set(committed_files) - set(new_files))
                changed = sorted(
                    f
                    for f in set(new_files) & set(committed_files)
                    if new_files[f] != committed_files[f]
                )

                if added or removed or changed:
                    print(f"{ver}.zip differs from upstream:")
                    for f in added:
                        print(f"  + {f}")
                    for f in removed:
                        print(f"  - {f}")
                    for f in changed:
                        print(f"  ~ {f}")
                    drift = True

            if drift:
                print(
                    "\nRun 'python3 dm_diff_tool/build_zips.py' and commit the result."
                )
                return 1

            print(
                f"OK: all {len(new_manifest)} zip(s) and data_manifest.json match upstream."
            )
            return 0

    # --- Normal build mode ---
    zips_dir = root / "data_model" / "zips"
    manifest = build(src_data_dir, zips_dir)

    for ver, entry in manifest.items():
        count = sum(len(files) for files in entry.values())
        size_kb = (zips_dir / f"{ver}.zip").stat().st_size // 1024
        print(f"  {ver}: {count} files -> {ver}.zip ({size_kb} KB)")

    manifest_path = root / "data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nBuilt {len(manifest)} zip(s) in {zips_dir}")
    print(f"Updated {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
