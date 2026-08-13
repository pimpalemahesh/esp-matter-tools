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
"""The canonical selection document model + loader."""

import pytest

from pics_tool.generate.selection import EndpointSpec, Selection, SelectionError


def test_multi_endpoint_from_dict():
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "role": "commissionee",
            "transport": ["wifi_2g"],
            "mcore_claims": ["MCORE.DD.NFC"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["OO.S.F02"]},
                {"device_types": ["On/Off Light", "Occupancy Sensor"]},
            ],
        }
    )
    assert len(sel.endpoints) == 2
    assert sel.endpoints[0] == EndpointSpec(["Extended Color Light"], ["OO.S.F02"])
    assert sel.endpoints[1].device_types == ["On/Off Light", "Occupancy Sensor"]
    assert sel.mcore_claims == ["MCORE.DD.NFC"]
    # EP1's primary device type represents the node profile.
    assert sel.profile.device_type == "Extended Color Light"
    assert sel.profile.transport == ["wifi_2g"]


def test_device_type_shorthand_is_single_endpoint():
    sel = Selection.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]}
    )
    assert sel.endpoints == [EndpointSpec(["On/Off Light"], [])]
    assert sel.mcore_claims == []


def test_endpoint_string_and_device_type_forms():
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                "On/Off Light",
                {"device_type": "Dimmable Light", "claims": ["LVL.S.F01"]},
            ],
        }
    )
    assert sel.endpoints[0] == EndpointSpec(["On/Off Light"], [])
    assert sel.endpoints[1] == EndpointSpec(["Dimmable Light"], ["LVL.S.F01"])


def test_from_profile_roundtrip():
    from pics_tool.generate.profile import DeviceProfile

    profile = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]}
    )
    sel = Selection.from_profile(profile)
    assert sel.endpoints == [EndpointSpec(["On/Off Light"])]
    assert sel.profile is profile


def test_errors():
    with pytest.raises(SelectionError):
        Selection.from_dict(
            {"spec_version": "1.6", "transport": ["wifi_2g"]}
        )  # no endpoints/device_type
    with pytest.raises(SelectionError):
        Selection.from_dict(
            {"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": []}
        )
    with pytest.raises(SelectionError):
        Selection.from_dict(
            {
                "spec_version": "1.6",
                "transport": ["wifi_2g"],
                "endpoints": [{"claims": ["OO.S.F02"]}],
            }
        )  # endpoint w/o device_types
