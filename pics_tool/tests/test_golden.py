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
"""Golden/snapshot regression tests.

Each case regenerates the full enabled-PICS set and compares it to a checked-in
snapshot. If output legitimately changes, regenerate the snapshots with
``tools/update_golden.py`` and review the diff.
"""

import json
from pathlib import Path

import pytest

loader = pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool.generate.cluster_engine import all_enabled_cluster_ids, generate_cluster_pics
from pics_tool.generate.mcore_engine import compute_mcore_pics
from pics_tool.generate.profile import DeviceProfile

GOLDEN_DIR = Path(__file__).parent / "golden"

CASES = {
    "onoff_light_wifi": {"spec_version": "1.6", "device_type": "On/Off Light",
                         "transport": ["wifi_2g"]},
    "onoff_light_thread": {"spec_version": "1.6", "device_type": "On/Off Light",
                           "transport": ["thread"]},
    "dimmable_light_wifi": {"spec_version": "1.6", "device_type": "Dimmable Light",
                            "transport": ["wifi_2g"]},
    "onoff_light_wifi_ota": {"spec_version": "1.6", "device_type": "On/Off Light",
                             "transport": ["wifi_2g"], "node_device_types": ["OTA Requestor"]},
}


def _generate(profile_dict: dict) -> dict[str, list[str]]:
    model = loader.load_version("1.6")
    profile = DeviceProfile.from_dict(profile_dict)
    cluster_eps = generate_cluster_pics(model, profile)
    eps = {ep.endpoint: set(ep.pics) for ep in cluster_eps}
    eps.setdefault(0, set()).update(
        compute_mcore_pics(profile, "1.6", all_enabled_cluster_ids(cluster_eps)))
    return {str(k): sorted(v) for k, v in sorted(eps.items())}


@pytest.mark.parametrize("name", sorted(CASES))
def test_matches_golden(name):
    golden = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
    actual = _generate(CASES[name])
    assert actual == golden, (
        f"generated PICS for {name} differ from golden; "
        "if intended, run tools/update_golden.py"
    )
