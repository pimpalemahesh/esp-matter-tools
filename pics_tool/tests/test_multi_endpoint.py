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
"""Multi-endpoint generation + per-endpoint claims through the shared engine."""

import pytest

loader = pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool.generate.selection import Selection, build_endpoints_enabled


def _enabled(selection_dict):
    model = loader.load_version("1.6")
    return build_endpoints_enabled(model, Selection.from_dict(selection_dict))


def test_two_application_endpoints():
    enabled = _enabled(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"]},
                {"device_types": ["Temperature Sensor"]},
            ],
        }
    )
    assert set(enabled) >= {0, 1, 2}
    assert "OO.S" in enabled[1]  # On/Off on the light endpoint
    assert "TMP.S" in enabled[2]  # Temperature Measurement on EP2
    assert "OO.S" not in enabled[2]  # the light's clusters stay on EP1


def test_per_endpoint_claim_does_not_leak():
    # Same cluster (On/Off) on both endpoints; claim OO.S.F02 only on EP1.
    enabled = _enabled(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["On/Off Light"], "claims": ["OO.S.F02"]},
                {"device_types": ["On/Off Light"]},
            ],
        }
    )
    assert "OO.S.F02" in enabled[1]
    assert "OO.S.F02" not in enabled[2]


def test_composed_device_types_on_one_endpoint():
    enabled = _enabled(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [{"device_types": ["On/Off Light", "Occupancy Sensor"]}],
        }
    )
    assert "OO.S" in enabled[1]  # from On/Off Light
    assert "OCC.S" in enabled[1]  # from Occupancy Sensor (composed)


def test_mcore_claim_lands_on_endpoint_0():
    enabled = _enabled(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "mcore_claims": ["MCORE.DD.NFC"],
            "endpoints": [{"device_types": ["On/Off Light"]}],
        }
    )
    assert "MCORE.DD.NFC" in enabled[0]


def test_deterministic():
    doc = {
        "spec_version": "1.6",
        "transport": ["wifi_2g"],
        "endpoints": [
            {"device_types": ["Extended Color Light"], "claims": ["OO.S.F02"]}
        ],
    }
    assert _enabled(doc) == _enabled(doc)
