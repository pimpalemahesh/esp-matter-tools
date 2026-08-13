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
from xml.etree.ElementTree import fromstring

from esp_matter_datamodel import validation
from esp_matter_datamodel.model.conformance import (
    ConformanceContext,
    Decision,
    evaluate,
)
from esp_matter_datamodel.ingest.parser import norm_id, parse_cluster, parse_device_type

CLUSTER_XML = """
<cluster id="0x0006" name="On/Off Cluster" revision="6">
  <clusterIds><clusterId id="0x0006" name="On/Off"/></clusterIds>
  <classification hierarchy="base" role="application" picsCode="OO" scope="Endpoint"/>
  <features>
    <feature bit="0" code="LT" name="Lighting"><optionalConform/></feature>
    <feature bit="2" code="OFFONLY" name="OffOnly"><optionalConform/></feature>
  </features>
  <attributes>
    <attribute id="0x0000" name="OnOff" type="bool"><mandatoryConform/></attribute>
    <attribute id="0x4000" name="GlobalSceneControl" type="bool">
      <mandatoryConform><feature name="LT"/></mandatoryConform>
    </attribute>
  </attributes>
  <commands>
    <command id="0x00" name="Off" direction="commandToServer"><mandatoryConform/></command>
    <command id="0x01" name="On" direction="commandToServer">
      <mandatoryConform><notTerm><feature name="OFFONLY"/></notTerm></mandatoryConform>
    </command>
    <command id="0x00" name="OffResponse" direction="responseFromServer">
      <mandatoryConform/>
    </command>
  </commands>
</cluster>
"""

DEVICE_TYPE_XML = """
<deviceType id="0x0100" name="On/Off Light" revision="3">
  <clusters>
    <cluster id="0x0006" name="On/Off" side="server">
      <mandatoryConform/>
      <features><feature code="LT"><mandatoryConform/></feature></features>
    </cluster>
    <cluster id="0x0008" name="Level Control" side="server">
      <optionalConform/>
      <attributes>
        <attribute code="0x0000" name="CurrentLevel">
          <constraint><between><from value="1"/><to value="254"/></between></constraint>
        </attribute>
      </attributes>
    </cluster>
  </clusters>
</deviceType>
"""


def test_norm_id():
    assert norm_id("0x6", 4) == "0x0006"
    assert norm_id("0X00", 2) == "0x00"
    assert norm_id("0x4000", 4) == "0x4000"


def test_parse_cluster_conformance():
    cluster = parse_cluster(fromstring(CLUSTER_XML))
    assert cluster.id == "0x0006" and cluster.pics == "OO" and cluster.name == "On/Off"
    assert set(cluster.features) == {0, 2}
    # responseFromServer commands are generated (.Tx), not accepted; same id as
    # the received command must not collide (separate dicts).
    assert set(cluster.accepted_commands) == {"0x00", "0x01"}
    assert set(cluster.generated_commands) == {"0x00"}
    assert cluster.generated_commands["0x00"].name == "OffResponse"

    ctx_none = ConformanceContext(feature_mask=0)
    ctx_lt = ConformanceContext(feature_mask=1 << 0)
    # A0000 always mandatory
    assert evaluate(cluster.attributes["0x0000"].conformance, ctx_none).is_mandatory()
    # A4000 mandatory only with LT
    assert evaluate(cluster.attributes["0x4000"].conformance, ctx_lt).is_mandatory()
    assert (
        evaluate(cluster.attributes["0x4000"].conformance, ctx_none).decision
        == Decision.NOT_APPLICABLE
    )
    # On command mandatory unless OFFONLY
    on = cluster.accepted_commands["0x01"].conformance
    assert evaluate(on, ctx_none).is_mandatory()
    assert (
        evaluate(on, ConformanceContext(feature_mask=1 << 2)).decision
        == Decision.NOT_APPLICABLE
    )


def test_parse_device_type_overrides():
    cluster = parse_cluster(fromstring(CLUSTER_XML))
    dt = parse_device_type(fromstring(DEVICE_TYPE_XML), {"0x0006": cluster})
    assert dt.id == "0x0100" and dt.name == "On/Off Light"
    oo = dt.server_clusters["0x0006"]
    assert oo.conformance.type == "mandatory"
    # LT feature forced mandatory by the device type (resolved code -> bit 0)
    assert 0 in oo.feature_overrides
    assert oo.feature_overrides[0].type == "mandatory"
    # Level Control is optional; its attribute had only a constraint -> no override
    lvl = dt.server_clusters["0x0008"]
    assert lvl.conformance.type == "optional"
    assert lvl.attribute_overrides == {}


def test_parse_device_type_serializes_valid():
    cluster = parse_cluster(fromstring(CLUSTER_XML))
    dt = parse_device_type(fromstring(DEVICE_TYPE_XML), {"0x0006": cluster})
    instance = {
        "schema_version": "1.0.0",
        "spec_version": "1.6",
        "clusters": {cluster.id: cluster.to_json()},
        "device_types": {dt.id: dt.to_json()},
    }
    validation.validate(instance)  # must not raise
