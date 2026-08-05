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
"""The web payload with MULTIPLE application endpoints + per-endpoint claims."""

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool import webapp


def _answer(payload, tab, code):
    for it in payload["items"]:
        if it["tab"] == tab and it["code"] == code:
            return it["answer"]
    return None


def _profile():
    return {"spec_version": "1.6", "role": "commissionee", "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["OO.S.F02"]},
                {"device_types": ["On/Off Light"]},
            ]}


def test_one_tab_per_application_endpoint():
    p = webapp.generate_payload(_profile())
    ids = [t["id"] for t in p["tabs"]]
    assert ids == ["base", "0", "1", "2"]
    assert p["tabs"][2]["label"] == "Extended Color Light"
    assert p["tabs"][3]["label"] == "On/Off Light"


def test_per_endpoint_claim_scoping():
    p = webapp.generate_payload(_profile())
    assert _answer(p, "1", "OO.S.F02") == "yes"   # claimed on EP1
    assert _answer(p, "2", "OO.S.F02") == "no"     # not claimed on EP2
    assert _answer(p, "1", "OO.S") == "yes"         # both host On/Off
    assert _answer(p, "2", "OO.S") == "yes"


def test_export_routes_per_endpoint():
    files = webapp.export_pics_files(
        _profile(), {"1": ["OO.S", "OO.S.F02"], "2": ["OO.S"], "base": []})
    dirs = {f.split("/")[0] for f in files}
    assert "endpoint1" in dirs and "endpoint2" in dirs


def test_single_endpoint_backcompat():
    # Old UI payload (scalar device_type + flat claims arg) still works.
    p = webapp.generate_payload(
        {"spec_version": "1.6", "device_type": "On/Off Light", "transport": ["wifi_2g"]},
        claims=["OO.S.F02"])
    assert [t["id"] for t in p["tabs"]] == ["base", "0", "1"]
    assert _answer(p, "1", "OO.S.F02") == "yes"
