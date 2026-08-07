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
"""The web-UI bridge that emits the esp-matter data-model code.

``webapp.generate_scaffold_files`` drives the SAME ``generate_scaffold`` engine
as the CLI, so the browser and ``gen-scaffold`` produce identical code for
identical input. Optional features/sides the user switched on in the UI arrive
as ``claims_by_tab`` (the per-endpoint tab map from ``generate_payload``).
"""

import json

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool import webapp
from pics_tool.generate.scaffold import generate_scaffold
from pics_tool.generate.selection import Selection

loader = pytest.importorskip("esp_matter_datamodel.loader")

_PROFILE = {"spec_version": "1.6", "role": "commissionee", "transport": ["wifi_2g"]}


def _profile(**extra):
    return {**_PROFILE, **extra}


def test_basic_snippet_creates_node_and_endpoint():
    res = webapp.generate_scaffold_files(
        _profile(endpoints=[{"device_types": ["Extended Color Light"]}]))
    snippet = res["snippet"]
    assert res["file"] == "app_data_model.cpp"
    assert "node::create(&node_config" in snippet
    assert "endpoint_1 = extended_color_light::create(node," in snippet
    assert "endpoint::get_id" not in snippet          # no trailing scratch var
    # nothing optional claimed -> no feature guidance
    assert res["endpoints"][0]["features"] == []
    assert "Optional feature claimed" not in snippet


def test_optional_feature_from_ui_flows_into_code():
    """Enabling an optional feature in the UI (claims_by_tab) must appear in the
    generated code as precise enable-guidance -- 'does it create successfully'."""
    prof = _profile(endpoints=[{"device_types": ["Extended Color Light"]}])
    res = webapp.generate_scaffold_files(prof, {"1": ["CC.S.F04"]})
    snippet = res["snippet"]
    assert "cluster::get(endpoint_1, ColorControl::Id)" in snippet   # chip Id, not 0x0300
    # exact code (1.6 -> nearest 1.5.1): ColorTemperature has a config -> declared + &config
    assert ("cluster::color_control::feature::color_temperature::config_t "
            "color_control_color_temperature_config_1;") in snippet
    assert ("cluster::color_control::feature::color_temperature::add("
            "color_control_cluster_1, &color_control_color_temperature_config_1);") in snippet
    assert res["endpoints"][0]["features"] == ["Color Control / ColorTemperature"]


def test_optional_attribute_from_ui_flows_into_code():
    """The reported bug: an optional attribute ticked in the UI must appear in
    the code (the UI now sends attribute/command codes, not only features)."""
    prof = _profile(endpoints=[{"device_types": ["Extended Color Light"]}])
    res = webapp.generate_scaffold_files(prof, {"1": ["LVL.S.A0012", "LVL.S.A0013"]})
    snippet = res["snippet"]
    assert "cluster::get(endpoint_1, LevelControl::Id)" in snippet
    # exact code (1.6 -> nearest 1.5.1): nullable<uint16_t> value default + TODO
    assert "attribute::create_on_transition_time(level_control_cluster_1, nullable<uint16_t>());" in snippet
    assert "attribute::create_off_transition_time(level_control_cluster_1, nullable<uint16_t>());" in snippet
    assert res["endpoints"][0]["attributes"] == [
        "Level Control / OnTransitionTime", "Level Control / OffTransitionTime"]


def test_claims_are_scoped_per_endpoint_no_leak():
    prof = _profile(endpoints=[
        {"device_types": ["Extended Color Light"]},
        {"device_types": ["On/Off Light"]},
    ])
    # feature enabled only on EP2's tab
    res = webapp.generate_scaffold_files(prof, {"2": ["OO.S.F00"]})
    assert res["endpoints"][0]["features"] == []                    # EP1 untouched
    assert res["endpoints"][1]["features"] == ["On/Off / Lighting"]  # EP2 only
    assert "endpoint_2 = on_off_light::create(node," in res["snippet"]


def test_base_mcore_claims_do_not_affect_endpoint_code():
    prof = _profile(endpoints=[{"device_types": ["Extended Color Light"]}])
    plain = webapp.generate_scaffold_files(prof)
    with_mcore = webapp.generate_scaffold_files(prof, {"base": ["MCORE.DD.NFC"]})
    assert plain["snippet"] == with_mcore["snippet"]


def test_ui_and_cli_engine_agree():
    """The bridge must return byte-identical code to calling generate_scaffold
    directly (what the CLI does) for the same selection + claims."""
    sel_dict = _profile(endpoints=[
        {"device_types": ["Extended Color Light"], "claims": ["CC.S.F04"]},
    ])
    cli = generate_scaffold(Selection.from_dict(sel_dict), loader.load_version("1.6"))
    ui = webapp.generate_scaffold_files(
        _profile(endpoints=[{"device_types": ["Extended Color Light"]}]),
        {"1": ["CC.S.F04"]})
    assert ui["snippet"] == cli.snippet


def test_json_wrapper_roundtrips():
    out = webapp.generate_scaffold_json(
        json.dumps(_profile(endpoints=[{"device_types": ["Extended Color Light"]}])),
        json.dumps({"1": ["CC.S.F04"]}))
    res = json.loads(out)
    assert "color_temperature::add(" in res["snippet"]
    assert res["file"] == "app_data_model.cpp"
