#!/usr/bin/env python3

# Copyright 2026 Espressif Systems (Shanghai) PTE LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Bundle the PICS engine (source + data) into one zip for the Pyodide web app.

The browser fetches ``ui/web_bundle/pics_bundle.zip``, unpacks it into Pyodide's
virtual filesystem, and imports ``pics_tool.webapp`` from it. Because the data
model JSON and PICS templates already live in the repo, this is just "zip two
local package directories" -- no connectedhomeip clone needed.

Run from the pics_tool directory:  python3 build_web.py
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # .../pics_tool
DM_PKG = ROOT / "esp-matter-datamodel" / "esp_matter_datamodel"
PICS_PKG = ROOT / "pics_tool"

# (source package directory, arcname root inside the zip). esp_matter_datamodel
# is vendored inside pics_tool (pics_tool/esp-matter-datamodel) but stays a
# standalone package so it can be decoupled later.
PACKAGES = [(DM_PKG, "esp_matter_datamodel"), (PICS_PKG, "pics_tool")]
# Only ship what the engine needs at runtime.
KEEP_SUFFIXES = {".py", ".json", ".xml", ".yaml", ".yml"}
SKIP_DIR_PARTS = {"__pycache__", "tests", ".pytest_cache"}

OUT_DIR = ROOT / "ui" / "web_bundle"
CORE_ZIP = OUT_DIR / "pics_bundle.zip"  # engine only (no per-version data)
DATA_DIR = OUT_DIR / "data"  # per-version data zips, fetched on demand
MANIFEST = OUT_DIR / "versions.json"

_DATAMODEL_RE = re.compile(r"datamodel_(.+)\.json$")
_CAPS_RE = re.compile(r"caps_(.+)\.json$")

CAPS_DIR = PICS_PKG / "generate" / "codegen" / "targets" / "esp_matter" / "data"


def _vkey(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def _caps_versions() -> list[str]:
    if not CAPS_DIR.is_dir():
        return []
    return sorted(
        (
            m.group(1)
            for p in CAPS_DIR.glob("caps_*.json")
            if (m := _CAPS_RE.match(p.name))
        ),
        key=_vkey,
    )


def _included(path: Path) -> bool:
    if path.suffix.lower() not in KEEP_SUFFIXES:
        return False
    return not any(part in SKIP_DIR_PARTS for part in path.parts)


def _is_version_data(rel: Path) -> bool:
    """Per-version payload split out of the core bundle: cluster templates
    (pics_tool/templates/<v>/*), the datamodel JSONs (esp_matter_datamodel/
    datamodels/datamodel_<v>.json), and the esp_matter capability maps
    (.../esp_matter/data/caps_<v>.json). These are lazy-loaded, not in core."""
    parts = rel.parts
    return (
        "templates" in parts
        or "datamodels" in parts
        or (rel.name.startswith("caps_") and rel.suffix == ".json")
    )


def _versions() -> list[str]:
    """Versions that have BOTH a template dir and a datamodel JSON."""
    tmpl = (
        {p.name for p in (PICS_PKG / "templates").iterdir() if p.is_dir()}
        if (PICS_PKG / "templates").is_dir()
        else set()
    )
    models = {
        m.group(1)
        for p in (DM_PKG / "datamodels").glob("*.json")
        if (m := _DATAMODEL_RE.search(p.name))
    }
    return sorted(tmpl & models)


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for old in DATA_DIR.glob("*.zip"):
        old.unlink()

    # 1) Core bundle: all engine code + config, but NOT the per-version data.
    n = 0
    with zipfile.ZipFile(CORE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src_dir, arc_root in PACKAGES:
            if not src_dir.is_dir():
                raise SystemExit(f"error: package dir not found: {src_dir}")
            for path in sorted(src_dir.rglob("*")):
                rel = path.relative_to(src_dir)
                if path.is_file() and _included(path) and not _is_version_data(rel):
                    zf.write(path, f"{arc_root}/{rel}")
                    n += 1
    core_kb = CORE_ZIP.stat().st_size // 1024

    # 2) One data zip per version: its templates + its datamodel JSON, arced to
    #    the same package paths so unpacking into /bundle drops them in place.
    versions = _versions()
    for v in versions:
        with zipfile.ZipFile(
            DATA_DIR / f"{v}.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            for path in sorted((PICS_PKG / "templates" / v).rglob("*")):
                if path.is_file() and _included(path):
                    zf.write(
                        path,
                        f"pics_tool/templates/{v}/{path.relative_to(PICS_PKG / 'templates' / v)}",
                    )
            dm = DM_PKG / "datamodels" / f"datamodel_{v}.json"
            zf.write(dm, f"esp_matter_datamodel/datamodels/datamodel_{v}.json")
            # esp_matter capability map. If this version has its own, ship it;
            # else fill with the nearest lower version's caps (tagged nearest_for)
            # so the browser's per-version zip is self-contained (matches the CLI's
            # engine-level nearest fallback). Absent only if no caps ship at all.
            arc = f"pics_tool/generate/codegen/targets/esp_matter/data/caps_{v}.json"
            own = CAPS_DIR / f"caps_{v}.json"
            if own.is_file():
                zf.write(own, arc)
            else:
                avail = _caps_versions()
                lower = [x for x in avail if _vkey(x) <= _vkey(v)]
                pick = max(lower or avail, key=_vkey) if avail else None
                if pick:
                    data = json.loads(
                        (CAPS_DIR / f"caps_{pick}.json").read_text(encoding="utf-8")
                    )
                    data["nearest_for"] = v
                    zf.writestr(arc, json.dumps(data))

    # 3) Manifest so the web app can list versions without fetching any data.
    MANIFEST.write_text(json.dumps({"versions": versions}), encoding="utf-8")

    print(f"Core bundle: {n} files -> {CORE_ZIP.relative_to(ROOT)} ({core_kb} KB)")
    for v in versions:
        kb = (DATA_DIR / f"{v}.zip").stat().st_size // 1024
        print(f"  data/{v}.zip ({kb} KB)")
    print(f"Manifest: {MANIFEST.relative_to(ROOT)} -> {versions}")


if __name__ == "__main__":
    build()
