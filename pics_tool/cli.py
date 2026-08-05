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

"""Standalone entry point for the PICS generator -- no pip install needed.

Run it straight from the repo checkout, same as dm_diff_tool:

    python3 cli.py gen-pics --profile device-profile.yaml -o pics_out
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# pics_tool package + its vendored esp_matter_datamodel (kept standalone so it
# can be split back out into its own tool later).
for _path in (_HERE, _HERE / "esp-matter-datamodel"):
    sys.path.insert(0, str(_path))

from pics_tool.cli.main import main

if __name__ == "__main__":
    main()
