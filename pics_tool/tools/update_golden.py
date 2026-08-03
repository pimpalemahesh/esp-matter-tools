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
"""Regenerate the golden snapshots used by tests/test_golden.py.

Run this after an intended change to generation output, then review the diff.
"""

import json
import sys
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_TOOL_ROOT))            # so `import pics_tool` works
sys.path.insert(0, str(_TOOL_ROOT / "tests"))  # so `import test_golden` works
# the shared datamodel is the in-repo sibling, not a pip install
sys.path.insert(0, str(_TOOL_ROOT.parent / "esp-matter-datamodel"))
from test_golden import CASES, GOLDEN_DIR, _generate  # noqa: E402


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, profile_dict in CASES.items():
        golden = _generate(profile_dict)
        (GOLDEN_DIR / f"{name}.json").write_text(
            json.dumps(golden, indent=2) + "\n", encoding="utf-8")
        print(f"updated {name}: " + ", ".join(f"ep{k}={len(v)}" for k, v in golden.items()))


if __name__ == "__main__":
    main()
