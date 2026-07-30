#!/usr/bin/env python3

# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent           # .../pics_tool
REPO = ROOT.parent                                # .../esp-matter-tools

# (source package directory, arcname root inside the zip)
PACKAGES = [
    (REPO / "esp-matter-datamodel" / "esp_matter_datamodel", "esp_matter_datamodel"),
    (ROOT / "pics_tool", "pics_tool"),
]
# Only ship what the engine needs at runtime.
KEEP_SUFFIXES = {".py", ".json", ".xml", ".yaml", ".yml"}
SKIP_DIR_PARTS = {"__pycache__", "tests", ".pytest_cache"}

OUT_DIR = ROOT / "ui" / "web_bundle"
OUT_ZIP = OUT_DIR / "pics_bundle.zip"


def _included(path: Path) -> bool:
    if path.suffix.lower() not in KEEP_SUFFIXES:
        return False
    return not any(part in SKIP_DIR_PARTS for part in path.parts)


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src_dir, arc_root in PACKAGES:
            if not src_dir.is_dir():
                raise SystemExit(f"error: package dir not found: {src_dir}")
            for path in sorted(src_dir.rglob("*")):
                if path.is_file() and _included(path):
                    zf.write(path, f"{arc_root}/{path.relative_to(src_dir)}")
                    n += 1
    size_kb = OUT_ZIP.stat().st_size // 1024
    print(f"Bundled {n} files -> {OUT_ZIP.relative_to(REPO)} ({size_kb} KB)")


if __name__ == "__main__":
    build()
