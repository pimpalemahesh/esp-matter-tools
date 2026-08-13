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

"""Make the in-repo packages importable for pytest without any pip install."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# esp_matter_datamodel now lives inside pics_tool (pics_tool/esp-matter-datamodel);
# kept as a self-contained package so it can be split back out into its own tool.
for _path in (_HERE, _HERE / "esp-matter-datamodel"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_DATAMODELS = _HERE / "esp-matter-datamodel" / "esp_matter_datamodel" / "datamodels"


def pytest_collection_modifyitems(config, items):
    """The datamodel JSONs are generated (not tracked); most tests need them.
    If they're absent, skip with a clear pointer instead of a cryptic error."""
    if any(_DATAMODELS.glob("datamodel_*.json")):
        return
    import pytest

    skip = pytest.mark.skip(
        reason="Data models not built -- run ./build_tool.sh "
        "(or set MATTER_SDK_PATH to a connectedhomeip checkout) first."
    )
    for item in items:
        item.add_marker(skip)
