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
import pytest

from esp_matter_datamodel.model.conformance import conformance_from_json as cj
from esp_matter_datamodel.model.elements import (
    Attribute,
    Cluster,
    ClusterRequirement,
    Feature,
)
from pics_tool.generate import cluster_engine as ce

datamodel_loader = pytest.importorskip("esp_matter_datamodel.loader")


def _feature(bit, code, conf):
    return Feature(bit=bit, mask=1 << bit, code=code, name=code, conformance=conf)


def test_feature_mask_fixpoint_chain():
    # Feature A mandatory; feature B mandatory only if A -> both must end up set.
    cluster = Cluster(
        id="0x1234",
        name="X",
        pics="X",
        revision=1,
        features={
            0: _feature(0, "A", cj({"type": "mandatory"})),
            1: _feature(
                1,
                "B",
                cj(
                    {
                        "type": "mandatory",
                        "condition": {"op": "feature", "code": "A", "bit": 0},
                    }
                ),
            ),
            2: _feature(2, "C", cj({"type": "optional"})),
        },
    )
    req = ClusterRequirement(
        id="0x1234", name="X", conformance=cj({"type": "mandatory"})
    )
    mask = ce._feature_mask_fixpoint(cluster, req, frozenset(), set())
    assert mask & 0b001 and mask & 0b010  # A and B
    assert not (mask & 0b100)  # C optional -> off


def test_attribute_depends_on_feature():
    cluster = Cluster(
        id="0x1234",
        name="X",
        pics="X",
        revision=1,
        features={0: _feature(0, "A", cj({"type": "mandatory"}))},
        attributes={
            "0x0000": Attribute("0x0000", "Base", cj({"type": "mandatory"})),
            "0x0001": Attribute(
                "0x0001",
                "GatedOnA",
                cj(
                    {
                        "type": "mandatory",
                        "condition": {"op": "feature", "code": "A", "bit": 0},
                    }
                ),
            ),
            "0x0002": Attribute("0x0002", "Opt", cj({"type": "optional"})),
        },
    )
    req = ClusterRequirement(
        id="0x1234", name="X", conformance=cj({"type": "mandatory"})
    )
    enabled = ce._enable_cluster(req, cluster, frozenset(), set())
    assert "X.S" in enabled
    assert "X.S.A0000" in enabled and "X.S.A0001" in enabled
    assert "X.S.A0002" not in enabled


def test_transport_seed_forces_choice_feature():
    # A choice feature (optional) is not mandatory but is seeded by transport.
    cluster = Cluster(
        id="0x0031",
        name="Network Commissioning",
        pics="CNET",
        revision=1,
        features={
            0: _feature(
                0,
                "WI",
                cj({"type": "optional", "choice": {"marker": "a", "more": False}}),
            )
        },
    )
    req = ClusterRequirement(
        id="0x0031", name="Network Commissioning", conformance=cj({"type": "mandatory"})
    )
    enabled = ce._enable_cluster(req, cluster, frozenset(), {"WI"})
    assert "CNET.S.F00" in enabled


def test_optional_cluster_excluded():
    req = ClusterRequirement(
        id="0x0008", name="Level Control", conformance=cj({"type": "optional"})
    )
    cluster = Cluster(id="0x0008", name="Level Control", pics="LVL", revision=1)
    assert ce._enable_cluster(req, cluster, frozenset(), set()) == set()


# --- integration against the shipped 1.6 data model ------------------------ #


def _pics_for(device_type, transport):
    from pics_tool.generate.profile import DeviceProfile

    model = datamodel_loader.load_version("1.6")
    prof = DeviceProfile.from_dict(
        {"spec_version": "1.6", "device_type": device_type, "transport": transport}
    )
    return {ep.endpoint: ep.pics for ep in ce.generate_cluster_pics(model, prof)}


def test_onoff_light_wifi_expected_codes():
    pics = _pics_for("On/Off Light", ["wifi_2g"])
    ep1 = pics[1]
    for code in [
        "OO.S",
        "OO.S.A0000",
        "OO.S.A4000",
        "OO.S.C00.Rsp",
        "OO.S.C01.Rsp",
        "OO.S.F00",
        "DESC.S",
    ]:
        assert code in ep1, code
    # Generated response commands (.Tx) must be emitted (regression: response
    # commands use direction="responseFromServer").
    assert "G.S.C00.Tx" in ep1  # Groups AddGroupResponse
    assert "S.S.C00.Tx" in ep1  # Scenes AddSceneResponse
    assert "LVL.S" not in ep1  # optional cluster, strict mandatory-only

    ep0 = pics[0]
    for code in [
        "BINFO.S",
        "ACL.S",
        "CGEN.S",
        "CNET.S",
        "CNET.S.F00",
        "OPCREDS.S",
        "GRPKEY.S",
        "DGGEN.S",
    ]:
        assert code in ep0, code
    assert "CNET.S.F01" not in ep0 and "CNET.S.F02" not in ep0


def test_transport_thread_selects_th_feature():
    pics = _pics_for("On/Off Light", ["thread"])
    assert "CNET.S.F01" in pics[0]
    assert "CNET.S.F00" not in pics[0]
