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
"""End-to-end generation test against the shipped 1.6 data model + templates."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

loader = pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool.generate.cluster_engine import all_enabled_cluster_ids, generate_cluster_pics
from pics_tool.generate.mcore_engine import compute_mcore_pics
from pics_tool.generate.profile import DeviceProfile
from pics_tool.generate.writer import write_pics


def _supported(path: Path) -> set[str]:
    root = ET.parse(str(path)).getroot()
    return {pi.find("itemNumber").text.strip()
            for pi in root.iter("picsItem")
            if (pi.find("support") is not None and (pi.find("support").text or "").strip() == "true")}


def test_onoff_light_wifi_end_to_end(tmp_path):
    model = loader.load_version("1.6")
    profile = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]})

    cluster_eps = generate_cluster_pics(model, profile)
    endpoints = {ep.endpoint: set(ep.pics) for ep in cluster_eps}
    endpoints.setdefault(0, set()).update(
        compute_mcore_pics(profile, "1.6", all_enabled_cluster_ids(cluster_eps)))
    write_pics("1.6", endpoints, tmp_path)

    ep1_onoff = _supported(tmp_path / "endpoint1" / "On-Off Cluster Test Plan.xml")
    assert {"OO.S", "OO.S.A0000", "OO.S.A4000", "OO.S.C00.Rsp",
            "OO.S.C01.Rsp", "OO.S.F00"} <= ep1_onoff

    ep0_cnet = _supported(tmp_path / "endpoint0" / "Network Commissioning Cluster Test Plan.xml")
    assert "CNET.S" in ep0_cnet and "CNET.S.F00" in ep0_cnet
    assert "CNET.S.F01" not in ep0_cnet and "CNET.S.F02" not in ep0_cnet

    ep0_base = _supported(tmp_path / "endpoint0" / "Base.xml")
    assert {"MCORE.COM.WIFI_2P4GHZ", "MCORE.COM.WIFI", "MCORE.COM.WIRELESS",
            "MCORE.ROLE.COMMISSIONEE"} <= ep0_base
    assert "MCORE.ROLE.COMMISSIONER" not in ep0_base

    # endpoint1 should not carry MCORE / root-node-only clusters
    assert not (tmp_path / "endpoint1" / "Base.xml").exists()


def test_optional_cluster_not_emitted(tmp_path):
    model = loader.load_version("1.6")
    profile = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]})
    endpoints = {ep.endpoint: set(ep.pics) for ep in generate_cluster_pics(model, profile)}
    write_pics("1.6", endpoints, tmp_path)
    # Level Control is optional for On/Off Light -> no Level Control file on endpoint1.
    assert not (tmp_path / "endpoint1" / "Level Control Cluster Test Plan.xml").exists()
