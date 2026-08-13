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
"""P3: live-component Knowledge override, the PICS->component map, and the
webapp reporting which esp_matter signature source produced the code."""

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool import webapp
from pics_tool.generate.codegen.targets.esp_matter import refresh
from pics_tool.generate.codegen.targets.esp_matter.knowledge import from_component

_FIXTURE = """
namespace esp_matter { namespace cluster { namespace demo {
namespace feature { namespace with_cfg {
typedef struct config { uint16_t x; config() : x(0) {} } config_t;
esp_err_t add(cluster_t *cluster, config_t *config);
} }
namespace attribute {
attribute_t *create_thing(cluster_t* cluster, nullable<uint16_t> value);
}
} } }
"""


def test_from_component_parses_a_live_dir(tmp_path):
    # headers can sit under components/esp_matter/data_model/ (1.4.2+) ...
    dm = tmp_path / "components" / "esp_matter" / "data_model"
    dm.mkdir(parents=True)
    (dm / "esp_matter_feature.h").write_text(_FIXTURE)
    kb = from_component(tmp_path)
    sig = kb.symbol("cluster::demo::feature::with_cfg::add")
    assert sig is not None and sig.params[-1].type == "config_t*"
    assert "live component" in kb.source_label


def test_from_component_missing_headers_raises(tmp_path):
    with pytest.raises(ValueError, match="no esp_matter data_model headers"):
        from_component(tmp_path)


def test_pics_to_component_map():
    assert refresh.component_version_for("1.5.1") == "1.5.1"
    assert refresh.component_version_for("1.4") == "1.4.0"
    assert refresh.component_version_for("1.4.1") is None  # yanked component
    assert refresh.component_version_for("1.6") is None  # not released yet


def test_download_url_scheme():
    assert refresh.download_url("1.5.1").endswith(
        "/1.5.1/espressif__esp_matter-v1.5.1.zip"
    )
    assert refresh.download_url("1.4.2~2").endswith(
        "espressif__esp_matter-v1.4.2_2.zip"
    )


def test_refresh_unmapped_version_errors():
    with pytest.raises(ValueError, match="no released esp_matter component"):
        refresh.refresh("1.6", download=True)


def test_webapp_reports_knowledge_source():
    base = {
        "transport": ["wifi_2g"],
        "endpoints": [{"device_types": ["Extended Color Light"]}],
    }
    own = webapp.generate_scaffold_files(
        {**base, "spec_version": "1.5.1"}, {"1": ["CC.S.F00"]}
    )
    assert own["exact"] is True and "1.5.1" in own["knowledge_source"]
    assert "nearest" not in own["knowledge_source"]  # 1.5.1 has its own component
    near = webapp.generate_scaffold_files(
        {**base, "spec_version": "1.6"}, {"1": ["CC.S.F00"]}
    )
    assert (
        near["exact"] is True and "nearest" in near["knowledge_source"]
    )  # 1.6 -> 1.5.1
