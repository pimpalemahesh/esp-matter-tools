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
pytest.importorskip("jinja2")

from pics_tool.generate.scaffold import generate_scaffold
from pics_tool.generate.scaffold.naming import esp_name
from pics_tool.generate.selection import Selection


def _gen(selection_dict, output_dir=None):
    model = loader.load_version("1.6")
    return generate_scaffold(Selection.from_dict(selection_dict), model, output_dir)


def test_single_endpoint_snippet(tmp_path):
    result = _gen({"spec_version": "1.6", "transport": ["wifi_2g"],
                   "device_type": "Extended Color Light"}, tmp_path)
    snippet = result.snippet

    assert result.device_namespace == "extended_color_light"
    assert "node::create(&node_config, app_attribute_update_cb, app_identification_cb)" in snippet
    assert "extended_color_light::config_t extended_color_light_config_1;" in snippet
    assert ("extended_color_light::create(node, &extended_color_light_config_1, "
            "ENDPOINT_FLAG_NONE, priv_data)") in snippet
    assert "endpoint::get_id(endpoint_1)" in snippet
    # A paste-in snippet: no wrapper/include/guard.
    assert "create_data_model" not in snippet and "#include" not in snippet

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
    # OO bit 0x02 is On/Off "OffOnly"; surfaced as precise TODO guidance.
    assert "Optional feature claimed in PICS: On/Off / OffOnly" in snippet
    assert "cluster::on_off::feature::off_only::add(" in snippet
    assert result.endpoints[0].optional_features[0].feature_namespace == "off_only"


def test_esp_name_matches_convention():
    assert esp_name("Extended Color Light") == "extended_color_light"
    assert esp_name("On/Off") == "on_off"
    assert esp_name("Temperature Sensor") == "temperature_sensor"
