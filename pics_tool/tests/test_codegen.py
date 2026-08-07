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
"""The pluggable code-generation engine: neutral IR, target registry, facade.

Locks the P1 architecture: PICS -> DataModelPlan (target-neutral) -> esp_matter
target -> GeneratedOutput, driven by one facade, with the legacy scaffold entry
point preserved and producing identical output.
"""

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool.generate.codegen import generate_code, get_target, list_targets
from pics_tool.generate.codegen.from_pics import build_plan
from pics_tool.generate.scaffold import generate_scaffold
from pics_tool.generate.selection import Selection

loader = pytest.importorskip("esp_matter_datamodel.loader")


def _sel():
    return Selection.from_dict({
        "spec_version": "1.6", "transport": ["wifi_2g"],
        "endpoints": [{"device_types": ["Extended Color Light"],
                       "claims": ["CC.S.F04", "LVL.S.A0012", "LVL.C"]}]})


def test_registry_lists_esp_matter_target():
    assert "esp_matter" in list_targets()
    assert get_target("esp_matter").name == "esp_matter"


def test_unknown_target_is_a_clear_error():
    with pytest.raises(ValueError, match="unknown code target"):
        get_target("no_such_target")


def test_plan_is_target_neutral():
    # IR carries spec identity + names only -- no esp_matter namespaces/types.
    plan = build_plan(_sel(), loader.load_version("1.6"))
    assert plan.spec_version == "1.6"
    ep = plan.endpoints[0]
    assert ep.device_types == ["Extended Color Light"]
    assert any(f.name == "ColorTemperature" for f in ep.features)
    assert any(a.name == "OnTransitionTime" for a in ep.attributes)
    assert any(s.cluster_name == "Level Control" and s.client for s in ep.sides)


def test_facade_matches_legacy_scaffold():
    model = loader.load_version("1.6")
    sel = _sel()
    out = generate_code(sel, model, target="esp_matter")
    legacy = generate_scaffold(sel, model)
    assert out.primary == legacy.snippet          # one engine, identical output
    assert out.target == "esp_matter" and out.version == "1.6"
    assert out.files and out.files[0].path == "app_data_model.cpp"
    # 1.6 has no released component -> nearest (1.5.1) signatures, still exact.
    assert out.exact is True
    assert "1.5.1" in out.knowledge_source and "nearest" in out.knowledge_source
