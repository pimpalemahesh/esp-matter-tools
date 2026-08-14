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

from pics_tool.generate.scaffold import generate_scaffold
from pics_tool.generate.scaffold.naming import esp_name
from pics_tool.generate.selection import Selection

# 1.6 has no released esp_matter component, so generation uses the NEAREST bundled
# signatures (1.5.1). These tests assert the resulting real calls + structure; an
# element with no matching esp_matter function is omitted (see test_codegen_*).


def _gen(selection_dict, output_dir=None):
    model = loader.load_version("1.6")
    return generate_scaffold(Selection.from_dict(selection_dict), model, output_dir)


def test_single_endpoint_snippet(tmp_path):
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "device_type": "Extended Color Light",
        },
        tmp_path,
    )
    snippet = result.snippet

    assert result.device_namespace == "extended_color_light"
    assert (
        "node::create(&node_config, app_attribute_update_cb, app_identification_cb)"
        in snippet
    )
    assert "extended_color_light::config_t extended_color_light_config_1;" in snippet
    assert (
        "extended_color_light::create(node, &extended_color_light_config_1, "
        "ENDPOINT_FLAG_NONE, nullptr)"
    ) in snippet
    # A paste-in snippet: no wrapper/include/guard, and no trailing scratch var.
    assert "create_data_model" not in snippet and "#include" not in snippet
    assert "endpoint::get_id" not in snippet
    assert snippet.endswith(";\n") and not snippet.endswith("\n\n")

    assert result.file and Path(result.file).name == "app_data_model.cpp"
    assert Path(result.file).read_text() == snippet


def test_multi_endpoint_snippet():
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"]},
                {"device_types": ["Temperature Sensor"]},
            ],
        }
    )
    snippet = result.snippet
    assert "endpoint_1 = extended_color_light::create(" in snippet
    assert "endpoint_2 = temperature_sensor::create(" in snippet
    assert [ep.endpoint for ep in result.endpoints] == [1, 2]


def test_composed_device_types_use_add():
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["On/Off Light", "Occupancy Sensor"]},
            ],
        }
    )
    snippet = result.snippet
    assert "on_off_light::create(node," in snippet  # primary via create
    assert "occupancy_sensor::add(endpoint_1," in snippet  # composed via add
    assert result.endpoints[0].composed[0].name == "Occupancy Sensor"


def test_optional_feature_claim_is_surfaced():
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["OO.S.F02"]},
            ],
        }
    )
    snippet = result.snippet
    # OO bit 0x02 is On/Off "OffOnly"; surfaced as the door_lock enable idiom,
    # with no descriptive comment (just the code).
    assert "Optional" not in snippet and "claimed in your PICS" not in snippet
    # the feature is set PRE-create in the device-type config (feature_flags),
    # referenced by feature namespace -- no hardcoded cluster id anywhere.
    assert (
        "extended_color_light_config_1.on_off.feature_flags |= "
        "cluster::on_off::feature::off_only::get_id();" in snippet
    )
    assert "0x0006" not in snippet
    assert result.endpoints[0].optional_features[0].feature_namespace == "off_only"


def test_optional_features_grouped_and_use_chip_cluster_id():
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {
                    "device_types": ["Extended Color Light"],
                    "claims": ["CC.S.F00", "CC.S.F04"],
                },
            ],
        }
    )
    snippet = result.snippet
    # both Color Control features are set PRE-create on the same device-type
    # config (feature_flags), by feature namespace -- no cluster::get needed.
    assert (
        "extended_color_light_config_1.color_control.feature_flags |= "
        "cluster::color_control::feature::hue_saturation::get_id();" in snippet
    )
    assert (
        "extended_color_light_config_1.color_control.feature_flags |= "
        "cluster::color_control::feature::color_temperature::get_id();" in snippet
    )
    # continuation lines are not the old ragged 7-space indent
    assert "\n       cluster_t *" not in snippet


def test_optional_attributes_and_commands_are_added():
    # OnTransitionTime (LVL.S.A0012), OffTransitionTime (A0013) are optional Level
    # Control attributes; MoveToLevel (LVL.S.C00) an accepted command.
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {
                    "device_types": ["Extended Color Light"],
                    "claims": ["LVL.S.A0012", "LVL.S.A0013", "LVL.S.C00.Rsp"],
                },
            ],
        }
    )
    snippet = result.snippet
    # one cluster::get for Level Control, then create_ calls for each element
    assert snippet.count("cluster::get(endpoint_1, LevelControl::Id)") == 1
    assert (
        "cluster::level_control::attribute::create_on_transition_time(level_control_cluster_1, nullable<uint16_t>());"  # noqa: E501
        in snippet
    )
    assert (
        "cluster::level_control::attribute::create_off_transition_time(level_control_cluster_1, nullable<uint16_t>());"  # noqa: E501
        in snippet
    )
    assert (
        "cluster::level_control::command::create_move_to_level(level_control_cluster_1);"
        in snippet
    )
    ep = result.endpoints[0]
    assert [a.name for a in ep.optional_attributes] == [
        "OnTransitionTime",
        "OffTransitionTime",
    ]
    assert [c.name for c in ep.optional_commands] == ["MoveToLevel"]


def test_optional_event_is_added():
    # DRLK.S.E00 is the Door Lock DoorLockAlarm event; esp-matter exposes
    # cluster::<ns>::event::create_<name>(cluster).
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Door Lock"], "claims": ["DRLK.S.E00"]},
            ],
        }
    )
    snippet = result.snippet
    assert "cluster::get(endpoint_1, DoorLock::Id)" in snippet
    assert (
        "cluster::door_lock::event::create_door_lock_alarm(door_lock_cluster_1);"
        in snippet
    )
    assert [e.name for e in result.endpoints[0].optional_events] == ["DoorLockAlarm"]


def test_client_side_cluster_is_created_with_flag():
    # Extended Color Light has Level Control as a SERVER cluster by default;
    # claiming the CLIENT side (LVL.C) must emit an explicit client-cluster create.
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["LVL.C"]},
            ],
        }
    )
    snippet = result.snippet
    assert "cluster::level_control::config_t level_control_config_1;" in snippet
    assert (
        "cluster::level_control::create(endpoint_1, &level_control_config_1, "
        "CLUSTER_FLAG_CLIENT);"
    ) in snippet
    # not the old vague "add ... yourself" note
    assert "add the cluster/side" not in snippet
    s = result.endpoints[0].optional_sides[0]
    assert s.client and not s.server


def test_server_side_in_baseline_is_not_recreated():
    # LVL.S is already built by extended_color_light::create() -> no extra cluster::create
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["LVL.S"]},
            ],
        }
    )
    assert "cluster::level_control::create(" not in result.snippet
    assert result.endpoints[0].optional_sides == []


def test_unresolvable_element_becomes_a_comment_not_dropped():
    # ColorControl Primary3X: esp_matter 1.5.1 exposes only the generic
    # create_primary_n_x(value, index), so there's no create_primary_3_x. The
    # element must NOT be dropped -- it stays in the code as a comment that names
    # the API to look up, and is reported in .unresolved.
    result = _gen(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["CC.S.A0019"]},
            ],
        }
    )
    snippet = result.snippet
    # kept as a comment naming the full qualified call (same style as real calls)
    assert (
        "// cluster::color_control::attribute::create_primary_3_x() not found in "
        "esp_matter 1.5.1 -- add it manually"
    ) in snippet
    assert (
        "create_primary_3_x(color_control_cluster_1" not in snippet
    )  # a comment, not a real call
    assert any(
        u["name"] == "Primary3X"
        and u["kind"] == "attribute"
        and u["cluster"] == "Color Control"
        for u in result.unresolved
    )


def test_esp_name_matches_convention():
    assert esp_name("Extended Color Light") == "extended_color_light"
    assert esp_name("On/Off") == "on_off"
    assert esp_name("Temperature Sensor") == "temperature_sensor"


def test_root_endpoint_optional_clusters():
    """Optional Root Node clusters claimed on EP0 reach the code: the root
    endpoint is FETCHED (node::create builds it), explicitly-creatable
    clusters get cluster::create calls, and clusters node::create already
    covers (always or via sdkconfig) become explanatory comments -- never a
    duplicate create."""
    model = loader.load_version("1.6")
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "device_type": "Extended Color Light",
        }
    )
    result = generate_scaffold(
        sel, model, root_claims=["DLOG.S", "DGWIFI.S", "FLABEL.S", "ACL.S"]
    )
    s = result.snippet

    assert "endpoint_t *endpoint_0 = endpoint::get(node, 0);" in s
    assert (
        "cluster::diagnostic_logs::create(endpoint_0, &diagnostic_logs_config_0, CLUSTER_FLAG_SERVER);"  # noqa: E501
        in s
    )
    assert (
        "cluster::fixed_label::create(endpoint_0, &fixed_label_config_0, CLUSTER_FLAG_SERVER);"
        in s
    )
    # covered by node::create -> an sdkconfig comment, never a duplicate create
    assert "CONFIG_SUPPORT_WIFI_NETWORK_DIAGNOSTICS_CLUSTER" in s
    assert "cluster::wifi_network_diagnostics::create" not in s
    # a spec-mandatory root cluster (ACL) is already built: no call, no comment
    assert "cluster::access_control::create" not in s
    assert "access_control_config_0" not in s
    # the app endpoint still renders after the root block
    assert s.index("endpoint::get(node, 0)") < s.index("extended_color_light::create")


def test_root_claims_empty_means_no_root_block():
    model = loader.load_version("1.6")
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "device_type": "Extended Color Light",
        }
    )
    result = generate_scaffold(sel, model, root_claims=[])
    assert "endpoint::get(node, 0)" not in result.snippet


def test_optional_base_cluster_claim_on_app_endpoint():
    """A base-device-type OPTIONAL cluster (Fixed Label) claimed on an app
    endpoint is NOT treated as already-built: it gets a real create call
    (regression: the old baseline treated every base-DT cluster as built)."""
    model = loader.load_version("1.6")
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["FLABEL.S"]}
            ],
        }
    )
    result = generate_scaffold(sel, model)
    assert (
        "cluster::fixed_label::create(endpoint_1, &fixed_label_config_1, CLUSTER_FLAG_SERVER);"
        in result.snippet
    )


def test_created_cluster_pointer_reused_for_its_elements():
    """cluster::create() returns the cluster_t*: when the snippet creates a
    cluster AND adds elements to it, the pointer is captured from create and
    no redundant cluster::get is emitted. Clusters created elsewhere (by the
    device-type create) still use cluster::get."""
    model = loader.load_version("1.6")
    sel = Selection.from_dict(
        {
            "spec_version": "1.6",
            "transport": ["wifi_2g"],
            "endpoints": [
                {"device_types": ["Extended Color Light"], "claims": ["OO.S.F01"]}
            ],
        }
    )
    result = generate_scaffold(
        sel, model, root_claims=["TIMESYNC.S", "TIMESYNC.S.A0002"]
    )
    s = result.snippet
    assert (
        "cluster_t *time_synchronization_cluster_0 = "
        "cluster::time_synchronization::create(endpoint_0, "
        "&time_synchronization_config_0, CLUSTER_FLAG_SERVER);"
    ) in s
    assert "cluster::get(endpoint_0, TimeSynchronization::Id)" not in s
    assert "create_time_source(time_synchronization_cluster_0" in s
    # a device-type cluster's feature is set pre-create on the device config
    assert (
        "extended_color_light_config_1.on_off.feature_flags |= "
        "cluster::on_off::feature::dead_front_behavior::get_id();" in s
    )
