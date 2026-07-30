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
"""pics_tool: offline Matter PICS generator.

A consumer of the shared ``esp-matter-datamodel`` standard. It generates a
device's PICS from a spec version + device type + a minimal device profile,
with no live device. It owns all PICS-specific concepts; the shared package
stays PICS-neutral.

Nothing here is pip-installed: like dm_diff_tool, the tool runs straight from
the repo checkout, so ``esp_matter_datamodel`` is resolved from the sibling
``esp-matter-datamodel/`` directory when it is not already importable (in the
Pyodide web bundle both packages sit side by side and the fallback is a no-op).
"""

import sys as _sys
from pathlib import Path as _Path

try:
    import esp_matter_datamodel  # noqa: F401
except ImportError:
    _sibling = _Path(__file__).resolve().parents[2] / "esp-matter-datamodel"
    if (_sibling / "esp_matter_datamodel").is_dir():
        _sys.path.insert(0, str(_sibling))
