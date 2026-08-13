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
"""Maintainer-side refresh of the committed esp_matter capability maps.

Maps each supported PICS version to a released esp_matter component, downloads
(or reads a local copy of) that component, and writes the committed
``data/caps_<picsver>.json``. Run when esp_matter ships a new version -- never at
consumer runtime. Network + zip handling use only the standard library.
"""

from __future__ import annotations

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .caps_build import _HEADERS, find_data_model, write_caps

# PICS spec version -> released esp_matter component version. 1.4.1 is yanked and
# there is no released 1.6 component yet, so those PICS versions have no entry and
# fall back to placeholder generation.
PICS_TO_COMPONENT = {
    "1.4": "1.4.0",
    "1.4.2": "1.4.2",
    "1.5": "1.5.0",
    "1.5.1": "1.5.1",
}

DATA_DIR = Path(__file__).resolve().parent / "data"
_REGISTRY = "https://components-file.espressif.com/components/espressif/esp_matter"


def component_version_for(pics_version: str) -> str | None:
    return PICS_TO_COMPONENT.get(pics_version)


def download_url(component_version: str) -> str:
    fname = "espressif__esp_matter-v" + component_version.replace("~", "_") + ".zip"
    return f"{_REGISTRY}/{component_version}/{fname}"


def refresh(
    pics_version: str,
    *,
    component_dir=None,
    download: bool = False,
    out_dir: str | Path | None = None,
) -> tuple[Path, int]:
    """Write ``caps_<pics_version>.json`` from a component; return (path, symbol_count)."""
    compver = component_version_for(pics_version)
    if compver is None:
        raise ValueError(
            f"no released esp_matter component maps to PICS {pics_version!r} "
            f"(known: {sorted(PICS_TO_COMPONENT)})"
        )
    out = Path(out_dir or DATA_DIR) / f"caps_{pics_version}.json"

    tmp = None
    try:
        if component_dir:
            dm = find_data_model(component_dir)
        elif download:
            tmp = Path(tempfile.mkdtemp(prefix="esp_matter_comp_"))
            zpath = tmp / "component.zip"
            urllib.request.urlretrieve(download_url(compver), zpath)  # noqa: S310 (trusted host)
            # Header location moved across releases (1.4.0: components/esp_matter/;
            # 1.4.2+: components/esp_matter/data_model/), so match by basename.
            wanted = set(_HEADERS)
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    if name.rsplit("/", 1)[-1] in wanted:
                        z.extract(name, tmp)
            dm = find_data_model(tmp)
        else:
            raise ValueError("provide component_dir=... or download=True")
        if dm is None:
            raise ValueError("could not locate esp_matter data_model headers")
        count = write_caps(dm, out, compver)
        return out, count
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
