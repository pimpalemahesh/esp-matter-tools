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
"""The Selection -> esp-matter data-model construction snippet generator."""

from pathlib import Path

import pytest

loader = pytest.importorskip("esp_matter_datamodel.loader")

from pics_tool.generate.codegen.targets.esp_matter.knowledge import Knowledge
from pics_tool.generate.scaffold import generate_scaffold
from pics_tool.generate.scaffold.naming import esp_name
from pics_tool.generate.selection import Selection

# These tests exercise the PLACEHOLDER rendering path (structure, grouping, sides)
# independent of any esp_matter component -- a Knowledge whose symbol() always
# returns None forces the /* config */ / /* value */ output regardless of which
# version's caps happen to ship. (Exact-signature output is covered separately.)
_PLACEHOLDER_KB = Knowledge()


def _gen(selection_dict, output_dir=None):
    model = loader.load_version("1.6")
    return generate_scaffold(Selection.from_dict(selection_dict), model, output_dir,
                             knowledge=_PLACEHOLDER_KB)


def test_single_endpoint_snippet(tmp_path):
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"],
                   "device_type": "Extended Color Light"}, tmp_path)
    snippet = result.snippet

    assert result.device_namespace == "extended_color_light"
    assert "node::create(&node_config, app_attribute_update_cb, app_identification_cb)" in snippet
    assert "extended_color_light::config_t extended_color_light_config_1;" in snippet
    assert ("extended_color_light::create(node, &extended_color_light_config_1, "
            "ENDPOINT_FLAG_NONE, nullptr)") in snippet
    # A paste-in snippet: no wrapper/include/guard, and no trailing scratch var.
    assert "create_data_model" not in snippet and "#include" not in snippet
    assert "endpoint::get_id" not in snippet
    assert snippet.endswith(";\n") and not snippet.endswith("\n\n")

    assert result.file and Path(result.file).name == "app_data_model.cpp"
    assert Path(result.file).read_text() == snippet


def test_multi_endpoint_snippet():
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"]},
        {"device_types": ["Temperature Sensor"]},
    ]})
    snippet = result.snippet
    assert "endpoint_1 = extended_color_light::create(" in snippet
    assert "endpoint_2 = temperature_sensor::create(" in snippet
    assert [ep.endpoint for ep in result.endpoints] == [1, 2]


def test_composed_device_types_use_add():
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["On/Off Light", "Occupancy Sensor"]},
    ]})
    snippet = result.snippet
    assert "on_off_light::create(node," in snippet          # primary via create
    assert "occupancy_sensor::add(endpoint_1," in snippet   # composed via add
    assert result.endpoints[0].composed[0].name == "Occupancy Sensor"


def test_optional_feature_claim_is_surfaced():
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"], "claims": ["OO.S.F02"]},
    ]})
    snippet = result.snippet
    # OO bit 0x02 is On/Off "OffOnly"; surfaced as the door_lock enable idiom,
    # with no descriptive comment (just the code).
    assert "Optional" not in snippet and "claimed in your PICS" not in snippet
    # cluster fetched by ClusterName::Id (not a hardcoded 0x0006)
    assert "cluster::get(endpoint_1, OnOff::Id)" in snippet
    assert "0x0006" not in snippet
    # live code with a placeholder config so a copy-paste won't silently compile
    assert "cluster::on_off::feature::off_only::add(on_off_cluster_1, /* config */);" in snippet
    assert result.endpoints[0].optional_features[0].feature_namespace == "off_only"


def test_optional_features_grouped_and_use_chip_cluster_id():
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"], "claims": ["CC.S.F00", "CC.S.F04"]},
    ]})
    snippet = result.snippet
    # both Color Control features share one cluster::get, by ColorControl::Id
    assert snippet.count("cluster::get(endpoint_1, ColorControl::Id)") == 1
    assert "cluster::color_control::feature::hue_saturation::add(color_control_cluster_1," in snippet
    assert "cluster::color_control::feature::color_temperature::add(color_control_cluster_1," in snippet
    # continuation lines are not the old ragged 7-space indent
    assert "\n       cluster_t *" not in snippet


def test_optional_attributes_and_commands_are_added():
    # OnTransitionTime (LVL.S.A0012), OffTransitionTime (A0013) are optional Level
    # Control attributes; MoveToLevel (LVL.S.C00) an accepted command.
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"],
         "claims": ["LVL.S.A0012", "LVL.S.A0013", "LVL.S.C00.Rsp"]},
    ]})
    snippet = result.snippet
    # one cluster::get for Level Control, then create_ calls for each element
    assert snippet.count("cluster::get(endpoint_1, LevelControl::Id)") == 1
    assert "cluster::level_control::attribute::create_on_transition_time(level_control_cluster_1, /* value */);" in snippet
    assert "cluster::level_control::attribute::create_off_transition_time(level_control_cluster_1, /* value */);" in snippet
    assert "cluster::level_control::command::create_move_to_level(level_control_cluster_1);" in snippet
    ep = result.endpoints[0]
    assert [a.name for a in ep.optional_attributes] == ["OnTransitionTime", "OffTransitionTime"]
    assert [c.name for c in ep.optional_commands] == ["MoveToLevel"]


def test_optional_event_is_added():
    # DRLK.S.E00 is the Door Lock DoorLockAlarm event; esp-matter exposes
    # cluster::<ns>::event::create_<name>(cluster).
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Door Lock"], "claims": ["DRLK.S.E00"]},
    ]})
    snippet = result.snippet
    assert "cluster::get(endpoint_1, DoorLock::Id)" in snippet
    assert "cluster::door_lock::event::create_door_lock_alarm(door_lock_cluster_1);" in snippet
    assert [e.name for e in result.endpoints[0].optional_events] == ["DoorLockAlarm"]


def test_client_side_cluster_is_created_with_flag():
    # Extended Color Light has Level Control as a SERVER cluster by default;
    # claiming the CLIENT side (LVL.C) must emit an explicit client-cluster create.
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"], "claims": ["LVL.C"]},
    ]})
    snippet = result.snippet
    assert "cluster::level_control::config_t level_control_config_1;" in snippet
    assert ("cluster::level_control::create(endpoint_1, &level_control_config_1, "
            "CLUSTER_FLAG_CLIENT);") in snippet
    # not the old vague "add ... yourself" note
    assert "add the cluster/side" not in snippet
    s = result.endpoints[0].optional_sides[0]
    assert s.client and not s.server


def test_server_side_in_baseline_is_not_recreated():
    # LVL.S is already built by extended_color_light::create() -> no extra cluster::create
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"], "endpoints": [
        {"device_types": ["Extended Color Light"], "claims": ["LVL.S"]},
    ]})
    assert "cluster::level_control::create(" not in result.snippet
    assert result.endpoints[0].optional_sides == []


def test_esp_name_matches_convention():
    assert esp_name("Extended Color Light") == "extended_color_light"
    assert esp_name("On/Off") == "on_off"
    assert esp_name("Temperature Sensor") == "temperature_sensor"
