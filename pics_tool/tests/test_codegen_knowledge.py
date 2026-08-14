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
"""P2: exact esp_matter code via the committed capability map + synthesizer."""

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool.generate.codegen import generate_code
from pics_tool.generate.codegen.targets.esp_matter import caps_build, synth
from pics_tool.generate.codegen.targets.esp_matter.knowledge import load_bundled
from pics_tool.generate.selection import Selection

loader = pytest.importorskip("esp_matter_datamodel.loader")


# ---- the header parser (maintainer-side) ----
_FIXTURE = """
namespace esp_matter {
namespace cluster {
namespace demo {
cluster_t *create(endpoint_t *endpoint, config_t *config, uint8_t flags);
namespace feature {
namespace with_cfg {
typedef struct config { uint16_t x; config() : x(0) {} } config_t;
esp_err_t add(cluster_t *cluster, config_t *config);
}
namespace no_cfg {
esp_err_t add(cluster_t *cluster);
}
}
namespace attribute {
attribute_t *create_thing(cluster_t* cluster, nullable<uint16_t> value);
attribute_t *create_flag(cluster_t *cluster, bool value);
}
namespace command {
command_t *create_do_it(cluster_t *cluster);
}
}
}
}
"""


def test_parser_captures_signatures():
    syms = {}
    caps_build._parse_header(_FIXTURE, syms)
    assert syms["cluster::demo::feature::with_cfg::add"]["params"] == [
        {"type": "cluster_t*", "name": "cluster"},
        {"type": "config_t*", "name": "config"},
    ]
    assert syms["cluster::demo::feature::no_cfg::add"]["params"] == [
        {"type": "cluster_t*", "name": "cluster"}
    ]
    assert (
        syms["cluster::demo::attribute::create_thing"]["params"][1]["type"]
        == "nullable<uint16_t>"
    )
    assert "cluster::demo::command::create_do_it" in syms


# ---- the generic synthesizer ----
@pytest.mark.parametrize(
    "type_str,expected",
    [
        ("bool", "false"),
        ("uint8_t", "0"),
        ("uint32_t", "0"),
        ("nullable<uint16_t>", "nullable<uint16_t>()"),
        ("chip::app::Clusters::OnOff::Foo", "chip::app::Clusters::OnOff::Foo{}"),
    ],
)
def test_synth_value_for(type_str, expected):
    assert synth.value_for(type_str) == expected


# ---- the committed bundled knowledge ----
def test_element_namespace_resolution_binds_irregular_names():
    """Spec-derived element namespaces are reconciled against the component's
    actual naming, so irregular spellings bind to a real API instead of
    degrading to a manual comment. A name with NO component API stays derived
    (the caller keeps it as a comment)."""
    from pics_tool.generate.codegen.targets.esp_matter.naming import (
        resolve_element_ns,
    )

    kb = load_bundled("1.5.1")

    def feats(cns):
        return kb.available_namespaces(cns, "feature")

    # C++ keyword -> cluster-prefixed component name
    assert resolve_element_ns("fan_control", "feature", "auto", feats("fan_control")) \
        == "fan_auto"
    # acronym / word-split spelling (underscore-insensitive match)
    assert resolve_element_ns("energy_evse", "feature", "v_2_x", feats("energy_evse")) \
        == "v2x"
    assert resolve_element_ns(
        "energy_evse", "feature", "so_c_reporting", feats("energy_evse")
    ) == "soc_reporting"
    # feature-code alias (air-quality levels): the 1.4 component used the short
    # code names; 1.5.1 later adopted the full spelling, so this resolves
    # per-version against whatever that component actually exposes.
    kb14 = load_bundled("1.4")
    assert resolve_element_ns(
        "air_quality", "feature", "very_poor",
        kb14.available_namespaces("air_quality", "feature"),
    ) == "vpoor"
    # attribute spelling split
    attrs = kb.available_namespaces("wifi_network_diagnostics", "attribute")
    assert resolve_element_ns(
        "wifi_network_diagnostics", "attribute", "wi_fi_version", attrs
    ) == "wifi_version"
    # genuinely absent: no component API -> derived unchanged (becomes a comment)
    assert resolve_element_ns(
        "level_control", "feature", "frequency", feats("level_control")
    ) == "frequency"


def test_cluster_namespace_resolution_binds_irregular_names():
    """A spec cluster whose esp-matter namespace diverges (C++ keyword suffix,
    or a Wi-Fi-style spelling) is reconciled against the component's actual
    cluster namespaces, so the whole cluster's create() + element calls bind to
    a real API. A cluster with no component namespace stays derived."""
    from pics_tool.generate.codegen.targets.esp_matter.naming import (
        resolve_cluster_ns,
    )

    cns = load_bundled("1.5.1").cluster_namespaces()
    # C++ keyword -> component suffixes _cluster (explicit alias)
    assert resolve_cluster_ns("switch", cns) == "switch_cluster"
    # spelling divergence (underscore-insensitive match, no alias needed)
    assert resolve_cluster_ns("wi_fi_network_management", cns) == "wifi_network_management"
    # regular cluster unchanged
    assert resolve_cluster_ns("on_off", cns) == "on_off"
    # not in the component -> derived unchanged (emitted call stays a comment)
    assert resolve_cluster_ns("media_playback", cns) == "media_playback"


def test_switch_cluster_side_emits_real_call():
    """Regression: a claimed Switch cluster must emit cluster::switch_cluster::
    (the C++-keyword-safe component namespace), not a wrong cluster::switch:: or
    an 'add it manually' comment."""
    sel = Selection.from_dict(
        {
            "spec_version": "1.5.1",
            "transport": ["wifi_2g"],
            "endpoints": [{"device_types": ["Generic Switch"], "claims": ["SWTCH.S.F00"]}],
        }
    )
    out = generate_code(sel, loader.load_version("1.5.1"), target="esp_matter")
    assert "cluster::switch_cluster::feature::latching_switch::add(" in out.primary
    assert "cluster::switch::" not in out.primary
    assert "not found" not in out.primary


def test_fan_auto_feature_emits_real_call():
    """Regression: the Fan device's Auto feature must emit a real
    fan_auto::add() call, not an 'add it manually' comment."""
    sel = Selection.from_dict(
        {
            "spec_version": "1.5.1",
            "transport": ["wifi_2g"],
            "endpoints": [{"device_types": ["Fan"], "claims": ["FAN.S.F01"]}],
        }
    )
    out = generate_code(sel, loader.load_version("1.5.1"), target="esp_matter")
    assert "cluster::fan_control::feature::fan_auto::add(" in out.primary
    assert "not found" not in out.primary


def test_bundled_1_5_1_loads():
    kb = load_bundled("1.5.1")
    assert kb is not None and "1.5.1" in kb.source_label
    sig = kb.symbol("cluster::on_off::feature::lighting::add")
    assert sig is not None and sig.params[-1].type == "config_t*"
    assert load_bundled("1.6") is None  # no released 1.6 component


# ---- end to end: exact for 1.5.1, placeholders for 1.6 ----
def _sel(version):
    return Selection.from_dict(
        {
            "spec_version": version,
            "transport": ["wifi_2g"],
            "endpoints": [
                {
                    "device_types": ["Extended Color Light"],
                    "claims": [
                        "CC.S.F00",
                        "OO.S.F02",
                        "LVL.S.A0012",
                        "OO.S.A0000",
                        "LVL.S.C00.Rsp",
                    ],
                }
            ],
        }
    )


def test_exact_code_for_1_5_1():
    out = generate_code(
        _sel("1.5.1"), loader.load_version("1.5.1"), target="esp_matter"
    )
    s = out.primary
    assert out.exact is True and "1.5.1" in out.knowledge_source
    # feature WITH config -> declared config_t + &config
    assert (
        "cluster::color_control::feature::hue_saturation::config_t color_control_hue_saturation_config_1;"  # noqa: E501
        in s
    )
    assert (
        "feature::hue_saturation::add(color_control_cluster_1, &color_control_hue_saturation_config_1);"  # noqa: E501
        in s
    )
    # feature WITHOUT config -> no second argument (the placeholder path got this wrong)
    assert "cluster::on_off::feature::off_only::add(on_off_cluster_1);" in s
    # attributes -> type-correct default + TODO
    assert "create_on_off(on_off_cluster_1, false);" in s
    assert (
        "create_on_transition_time(level_control_cluster_1, nullable<uint16_t>());" in s
    )
    assert "// TODO" not in s and "/*" not in s  # no comments in generated code
    # command -> cluster only
    assert "command::create_move_to_level(level_control_cluster_1);" in s
    # no placeholder leftovers in exact mode
    assert "/* config */" not in s and "/* value */" not in s


def test_nearest_signatures_when_no_component_for_version():
    # 1.6 has no released component -> nearest lower (1.5.1) signatures, labeled.
    out = generate_code(_sel("1.6"), loader.load_version("1.6"), target="esp_matter")
    assert out.exact is True
    assert "1.5.1" in out.knowledge_source and "nearest" in out.knowledge_source
    # the shared clusters resolve against 1.5.1, so real calls (no placeholders)
    assert "feature::hue_saturation::add(" in out.primary
    assert "/* config */" not in out.primary and "/* value */" not in out.primary
