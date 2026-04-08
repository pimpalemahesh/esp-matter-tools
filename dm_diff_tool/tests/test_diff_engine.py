"""
Comprehensive tests for MatterDMDiff diff_engine.py

Run:  python -m pytest tests/test_diff_engine.py -v
From: MatterDMDiff/
"""

import json
import sys
import os
from collections import OrderedDict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import diff_engine as de


# ---------------------------------------------------------------------------
# Fixtures — reusable XML fragments
# ---------------------------------------------------------------------------

MINIMAL_CLUSTER_XML = """\
<cluster id="0x0003" name="Identify" revision="4">
  <revisionHistory>
    <revision revision="4" summary="Initial"/>
  </revisionHistory>
  <classification hierarchy="base" role="server" picsCode="I" scope="Endpoint"/>
</cluster>"""

CLUSTER_WITH_FEATURES_XML = """\
<cluster id="0x0006" name="OnOff" revision="6">
  <revisionHistory>
    <revision revision="5" summary="Added lighting"/>
    <revision revision="6" summary="Added dead-front"/>
  </revisionHistory>
  <classification hierarchy="base" role="server" picsCode="OO" scope="Endpoint"/>
  <features>
    <feature bit="0" code="LT" name="Lighting" summary="Lighting behavior">
      <optionalConform/>
    </feature>
    <feature bit="1" code="DF" name="DeadFrontBehavior" summary="Dead front behavior">
      <optionalConform>
        <feature name="Lighting"/>
      </optionalConform>
    </feature>
  </features>
  <attributes>
    <attribute id="0x0000" name="OnOff" type="bool">
      <access read="true" readPrivilege="view"/>
      <quality changeOmitted="true"/>
      <mandatoryConform/>
    </attribute>
    <attribute id="0x4000" name="GlobalSceneControl" type="bool">
      <access read="true" readPrivilege="view"/>
      <mandatoryConform>
        <feature name="Lighting"/>
      </mandatoryConform>
    </attribute>
  </attributes>
  <commands>
    <command id="0x00" name="Off" direction="commandToServer">
      <access invokePrivilege="operate"/>
      <mandatoryConform/>
    </command>
    <command id="0x01" name="On" direction="commandToServer">
      <access invokePrivilege="operate"/>
      <mandatoryConform/>
    </command>
    <command id="0x02" name="Toggle" direction="commandToServer">
      <access invokePrivilege="operate"/>
      <mandatoryConform/>
    </command>
  </commands>
  <events>
    <event id="0x00" name="SwitchLatched" priority="info">
      <access readPrivilege="view"/>
      <mandatoryConform/>
      <field id="0" name="NewPosition" type="uint8"/>
    </event>
  </events>
</cluster>"""

CLUSTER_WITH_DATATYPES_XML = """\
<cluster id="0x0101" name="DoorLock" revision="7">
  <revisionHistory>
    <revision revision="7" summary="New data types"/>
  </revisionHistory>
  <classification hierarchy="base" role="server" picsCode="DRLK" scope="Endpoint"/>
  <dataTypes>
    <enum name="AlarmCodeEnum">
      <item value="0" name="LockJammed" summary="Lock jammed">
        <mandatoryConform/>
      </item>
      <item value="1" name="LockFactoryReset" summary="Factory reset">
        <mandatoryConform/>
      </item>
    </enum>
    <bitmap name="DaysMaskMap">
      <bitfield bit="0" name="Sunday" summary="Sunday">
        <mandatoryConform/>
      </bitfield>
    </bitmap>
    <struct name="CredentialStruct">
      <field id="0" name="CredentialType" type="CredentialTypeEnum">
        <mandatoryConform/>
      </field>
      <field id="1" name="CredentialIndex" type="uint16">
        <mandatoryConform/>
      </field>
    </struct>
  </dataTypes>
</cluster>"""

MINIMAL_DEVICE_TYPE_XML = """\
<deviceType id="0x0100" name="On/Off Light" revision="3">
  <revisionHistory>
    <revision revision="3" summary="Initial"/>
  </revisionHistory>
  <classification class="simple" scope="endpoint"/>
  <clusters>
    <cluster id="0x0003" name="Identify" side="server">
      <mandatoryConform/>
    </cluster>
    <cluster id="0x0004" name="Groups" side="server">
      <mandatoryConform/>
    </cluster>
  </clusters>
</deviceType>"""

DEVICE_TYPE_WITH_CONDITIONS_XML = """\
<deviceType id="0x000F" name="Generic Switch" revision="3">
  <revisionHistory>
    <revision revision="3" summary="Added conditions"/>
  </revisionHistory>
  <classification class="simple" scope="endpoint"/>
  <conditions>
    <condition name="Latching" summary="Latching switch"/>
    <condition name="Momentary" summary="Momentary switch"/>
  </conditions>
  <conditionRequirements>
    <deviceType id="0x000F" name="Generic Switch">
      <conditionRequirement name="Latching">
        <mandatoryConform/>
      </conditionRequirement>
      <conditionRequirement name="Momentary">
        <optionalConform/>
      </conditionRequirement>
    </deviceType>
  </conditionRequirements>
  <clusters>
    <cluster id="0x003B" name="Switch" side="server">
      <mandatoryConform/>
      <features>
        <feature code="LS">
          <mandatoryConform>
            <condition name="Latching"/>
          </mandatoryConform>
        </feature>
      </features>
    </cluster>
  </clusters>
</deviceType>"""


# ---------------------------------------------------------------------------
# XML Parsing — Clusters
# ---------------------------------------------------------------------------

class TestParseClusterXml:
    def test_minimal_cluster(self):
        result = de.parse_cluster_xml_string(MINIMAL_CLUSTER_XML)
        assert result is not None
        assert result["id"] == "0x0003"
        assert result["name"] == "Identify"
        assert result["revision"] == "4"

    def test_revision_history(self):
        result = de.parse_cluster_xml_string(MINIMAL_CLUSTER_XML)
        assert len(result["revisions"]) == 1
        assert result["revisions"][0]["revision"] == "4"
        assert result["revisions"][0]["summary"] == "Initial"

    def test_classification(self):
        result = de.parse_cluster_xml_string(MINIMAL_CLUSTER_XML)
        assert result["classification"]["hierarchy"] == "base"
        assert result["classification"]["role"] == "server"
        assert result["classification"]["picsCode"] == "I"
        assert result["classification"]["scope"] == "Endpoint"

    def test_empty_sections_on_minimal(self):
        result = de.parse_cluster_xml_string(MINIMAL_CLUSTER_XML)
        assert len(result["features"]) == 0
        assert len(result["attributes"]) == 0
        assert len(result["commands"]) == 0
        assert len(result["events"]) == 0
        assert len(result["dataTypes"]) == 0

    def test_features_parsing(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        feats = result["features"]
        assert "Lighting" in feats
        assert "DeadFrontBehavior" in feats
        assert feats["Lighting"]["bit"] == "0"
        assert feats["Lighting"]["code"] == "LT"
        assert feats["DeadFrontBehavior"]["bit"] == "1"

    def test_feature_conformance(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        assert "O" in result["features"]["Lighting"]["conformance"]
        assert "Lighting" in result["features"]["DeadFrontBehavior"]["conformance"]

    def test_attributes_parsing(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        attrs = result["attributes"]
        assert "0x0000" in attrs
        assert attrs["0x0000"]["name"] == "OnOff"
        assert attrs["0x0000"]["type"] == "bool"

    def test_attribute_access(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        access = result["attributes"]["0x0000"]["access"]
        assert "readable" in access
        assert "view" in access

    def test_attribute_quality(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        quality = result["attributes"]["0x0000"]["quality"]
        assert "changeOmitted" in quality

    def test_attribute_conformance_with_feature(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        assert result["attributes"]["0x4000"]["conformance"] == "Lighting"

    def test_commands_parsing(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        cmds = result["commands"]
        assert len(cmds) == 3
        off_cmd = None
        for k, v in cmds.items():
            if v["name"] == "Off":
                off_cmd = v
                break
        assert off_cmd is not None
        assert off_cmd["direction"] == "commandToServer"

    def test_command_access(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        for k, v in result["commands"].items():
            if v["name"] == "Off":
                assert "operate" in v["access"]

    def test_events_parsing(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        evts = result["events"]
        assert len(evts) == 1
        evt = list(evts.values())[0]
        assert evt["name"] == "SwitchLatched"
        assert evt["priority"] == "info"

    def test_event_fields(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_FEATURES_XML)
        evt = list(result["events"].values())[0]
        assert len(evt["fields"]) == 1
        assert evt["fields"][0]["name"] == "NewPosition"

    def test_data_types_enum(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_DATATYPES_XML)
        dt = result["dataTypes"]
        assert "enum:AlarmCodeEnum" in dt
        alarm = dt["enum:AlarmCodeEnum"]
        assert alarm["kind"] == "enum"
        assert len(alarm["items"]) == 2
        assert alarm["items"][0]["name"] == "LockJammed"

    def test_data_types_bitmap(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_DATATYPES_XML)
        dt = result["dataTypes"]
        assert "bitmap:DaysMaskMap" in dt
        bm = dt["bitmap:DaysMaskMap"]
        assert bm["kind"] == "bitmap"
        assert len(bm["fields"]) == 1
        assert bm["fields"][0]["name"] == "Sunday"

    def test_data_types_struct(self):
        result = de.parse_cluster_xml_string(CLUSTER_WITH_DATATYPES_XML)
        dt = result["dataTypes"]
        assert "struct:CredentialStruct" in dt
        s = dt["struct:CredentialStruct"]
        assert s["kind"] == "struct"
        assert len(s["fields"]) == 2
        assert s["fields"][0]["name"] == "CredentialType"

    def test_invalid_xml_returns_none(self):
        assert de.parse_cluster_xml_string("not xml at all") is None

    def test_wrong_root_tag_returns_none(self):
        assert de.parse_cluster_xml_string("<deviceType/>") is None

    def test_empty_xml_string(self):
        assert de.parse_cluster_xml_string("") is None

    def test_cluster_no_classification(self):
        xml = '<cluster id="0x0001" name="Test" revision="1"></cluster>'
        result = de.parse_cluster_xml_string(xml)
        assert result is not None
        assert result["classification"] == {}

    def test_cluster_attributes_sorted_by_id(self):
        xml = """\
<cluster id="0x0001" name="Test" revision="1">
  <attributes>
    <attribute id="0x0002" name="Second" type="uint8">
      <mandatoryConform/>
    </attribute>
    <attribute id="0x0001" name="First" type="uint8">
      <mandatoryConform/>
    </attribute>
  </attributes>
</cluster>"""
        result = de.parse_cluster_xml_string(xml)
        keys = list(result["attributes"].keys())
        assert keys == ["0x0001", "0x0002"]


# ---------------------------------------------------------------------------
# XML Parsing — Device Types
# ---------------------------------------------------------------------------

class TestParseDeviceTypeXml:
    def test_minimal_device_type(self):
        result = de.parse_device_type_xml_string(MINIMAL_DEVICE_TYPE_XML)
        assert result is not None
        assert result["id"] == "0x0100"
        assert result["name"] == "On/Off Light"
        assert result["revision"] == "3"

    def test_device_type_classification(self):
        result = de.parse_device_type_xml_string(MINIMAL_DEVICE_TYPE_XML)
        assert result["classification"]["class"] == "simple"
        assert result["classification"]["scope"] == "endpoint"

    def test_device_type_clusters(self):
        result = de.parse_device_type_xml_string(MINIMAL_DEVICE_TYPE_XML)
        clusters = result["clusters"]
        assert len(clusters) == 2
        assert "0x0003_server" in clusters
        assert clusters["0x0003_server"]["name"] == "Identify"
        assert clusters["0x0003_server"]["side"] == "server"

    def test_device_type_cluster_conformance(self):
        result = de.parse_device_type_xml_string(MINIMAL_DEVICE_TYPE_XML)
        assert result["clusters"]["0x0003_server"]["conformance"] == "M"

    def test_device_type_conditions(self):
        result = de.parse_device_type_xml_string(DEVICE_TYPE_WITH_CONDITIONS_XML)
        conds = result["conditions"]
        assert "Latching" in conds
        assert "Momentary" in conds
        assert conds["Latching"] == "Latching switch"

    def test_device_type_condition_requirements(self):
        result = de.parse_device_type_xml_string(DEVICE_TYPE_WITH_CONDITIONS_XML)
        cr = result["conditionRequirements"]
        assert len(cr) == 1
        key = list(cr.keys())[0]
        assert cr[key]["name"] == "Generic Switch"
        reqs = cr[key]["requirements"]
        assert "Latching" in reqs
        assert reqs["Latching"]["conformance"] == "M"
        assert "Momentary" in reqs
        assert "O" in reqs["Momentary"]["conformance"]

    def test_device_type_cluster_features(self):
        result = de.parse_device_type_xml_string(DEVICE_TYPE_WITH_CONDITIONS_XML)
        cluster = result["clusters"]["0x003B_server"]
        assert "LS" in cluster["features"]
        assert "Latching" in cluster["features"]["LS"]["conformance"]

    def test_invalid_xml_returns_none(self):
        assert de.parse_device_type_xml_string("<broken>") is None

    def test_wrong_root_tag_returns_none(self):
        assert de.parse_device_type_xml_string("<cluster/>") is None

    def test_empty_string_returns_none(self):
        assert de.parse_device_type_xml_string("") is None

    def test_device_type_no_clusters(self):
        xml = '<deviceType id="0x0001" name="Empty" revision="1"></deviceType>'
        result = de.parse_device_type_xml_string(xml)
        assert result is not None
        assert len(result["clusters"]) == 0

    def test_device_type_no_conditions(self):
        result = de.parse_device_type_xml_string(MINIMAL_DEVICE_TYPE_XML)
        assert len(result["conditions"]) == 0
        assert len(result["conditionRequirements"]) == 0


# ---------------------------------------------------------------------------
# Conformance Rendering
# ---------------------------------------------------------------------------

class TestConformanceRendering:
    def _conf(self, xml_fragment):
        """Parse a cluster attribute with the given conformance children and return the conformance string."""
        xml = f'<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8">{xml_fragment}</attribute></attributes></cluster>'
        result = de.parse_cluster_xml_string(xml)
        return result["attributes"]["0x00"]["conformance"]

    def test_mandatory(self):
        assert self._conf("<mandatoryConform/>") == "M"

    def test_optional(self):
        assert self._conf("<optionalConform/>") == "O"

    def test_provisional(self):
        assert self._conf("<provisionalConform/>") == "P"

    def test_deprecated(self):
        assert self._conf("<deprecateConform/>") == "D"

    def test_disallowed(self):
        assert self._conf("<disallowConform/>") == "X"

    def test_described(self):
        assert self._conf("<describedConform/>") == "desc"

    def test_mandatory_with_feature(self):
        result = self._conf('<mandatoryConform><feature name="TL"/></mandatoryConform>')
        assert result == "TL"

    def test_optional_with_feature(self):
        result = self._conf('<optionalConform><feature name="TL"/></optionalConform>')
        assert result == "[TL]"

    def test_optional_with_choice(self):
        result = self._conf('<optionalConform choice="a" more="true"/>')
        assert result == "O.a+"

    def test_otherwise_conform(self):
        result = self._conf('<otherwiseConform><mandatoryConform><feature name="A"/></mandatoryConform><optionalConform/></otherwiseConform>')
        assert "A" in result
        assert "O" in result

    def test_not_term(self):
        result = self._conf('<mandatoryConform><notTerm><feature name="LT"/></notTerm></mandatoryConform>')
        assert "!" in result
        assert "LT" in result

    def test_or_term(self):
        result = self._conf('<mandatoryConform><orTerm><feature name="A"/><feature name="B"/></orTerm></mandatoryConform>')
        assert "A" in result
        assert "B" in result
        assert "|" in result

    def test_and_term(self):
        result = self._conf('<mandatoryConform><andTerm><feature name="A"/><feature name="B"/></andTerm></mandatoryConform>')
        assert "A" in result
        assert "B" in result
        assert "&" in result

    def test_condition_conform(self):
        result = self._conf('<mandatoryConform><condition name="Latching"/></mandatoryConform>')
        assert result == "Latching"


# ---------------------------------------------------------------------------
# Access / Quality / Constraint Parsing
# ---------------------------------------------------------------------------

class TestAccessParsing:
    def _access(self, access_xml):
        xml = f'<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8">{access_xml}</attribute></attributes></cluster>'
        return de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["access"]

    def test_read_only(self):
        result = self._access('<access read="true" readPrivilege="view"/>')
        assert "readable" in result
        assert "view" in result

    def test_read_write(self):
        result = self._access('<access read="true" write="true" readPrivilege="view" writePrivilege="manage"/>')
        assert "read/write" in result
        assert "manage" in result

    def test_write_only(self):
        result = self._access('<access write="true" writePrivilege="admin"/>')
        assert "writable" in result
        assert "admin" in result

    def test_fabric_scoped(self):
        result = self._access('<access read="true" fabricScoped="true"/>')
        assert "fabric-scoped" in result

    def test_fabric_sensitive(self):
        result = self._access('<access read="true" fabricSensitive="true"/>')
        assert "fabric-sensitive" in result

    def test_timed(self):
        result = self._access('<access read="true" timed="true"/>')
        assert "timed" in result

    def test_invoke_privilege(self):
        result = self._access('<access invokePrivilege="operate"/>')
        assert "operate" in result

    def test_no_access_element(self):
        xml = '<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8"/></attributes></cluster>'
        result = de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["access"]
        assert result == ""


class TestQualityParsing:
    def _quality(self, quality_xml):
        xml = f'<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8">{quality_xml}</attribute></attributes></cluster>'
        return de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["quality"]

    def test_change_omitted(self):
        assert "changeOmitted" in self._quality('<quality changeOmitted="true"/>')

    def test_nullable(self):
        assert "nullable" in self._quality('<quality nullable="true"/>')

    def test_no_quality(self):
        xml = '<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8"/></attributes></cluster>'
        assert de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["quality"] == ""


class TestConstraintParsing:
    def _constraint(self, constraint_xml):
        xml = f'<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8">{constraint_xml}</attribute></attributes></cluster>'
        return de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["constraint"]

    def test_min_max(self):
        result = self._constraint('<constraint><min value="0"/><max value="100"/></constraint>')
        assert "min=0" in result
        assert "max=100" in result

    def test_between(self):
        result = self._constraint('<constraint><between><from value="1"/><to value="10"/></between></constraint>')
        assert "between" in result
        assert "1" in result
        assert "10" in result

    def test_desc(self):
        result = self._constraint('<constraint><desc/></constraint>')
        assert "desc" in result

    def test_max_length(self):
        result = self._constraint('<constraint><maxLength value="32"/></constraint>')
        assert "maxLength=32" in result

    def test_no_constraint(self):
        xml = '<cluster id="0x01" name="T" revision="1"><attributes><attribute id="0x00" name="A" type="uint8"/></attributes></cluster>'
        assert de.parse_cluster_xml_string(xml)["attributes"]["0x00"]["constraint"] == ""


# ---------------------------------------------------------------------------
# Diff Engine — Core
# ---------------------------------------------------------------------------

class TestDiffDicts:
    def test_added(self):
        added, removed, common = de.diff_dicts({}, {"a": 1, "b": 2})
        assert set(added) == {"a", "b"}
        assert removed == []
        assert common == []

    def test_removed(self):
        added, removed, common = de.diff_dicts({"a": 1, "b": 2}, {})
        assert added == []
        assert set(removed) == {"a", "b"}
        assert common == []

    def test_common(self):
        added, removed, common = de.diff_dicts({"a": 1}, {"a": 2})
        assert added == []
        assert removed == []
        assert common == ["a"]

    def test_mixed(self):
        added, removed, common = de.diff_dicts(
            {"a": 1, "b": 2},
            {"b": 3, "c": 4}
        )
        assert added == ["c"]
        assert removed == ["a"]
        assert common == ["b"]

    def test_both_empty(self):
        added, removed, common = de.diff_dicts({}, {})
        assert added == []
        assert removed == []
        assert common == []


class TestDiffSimpleDict:
    def test_no_changes(self):
        assert de.diff_simple_dict({"a": "1"}, {"a": "1"}) == []

    def test_value_changed(self):
        changes = de.diff_simple_dict({"a": "1"}, {"a": "2"})
        assert len(changes) == 1
        assert changes[0] == {"field": "a", "old": "1", "new": "2"}

    def test_key_added(self):
        changes = de.diff_simple_dict({}, {"a": "1"})
        assert len(changes) == 1
        assert changes[0]["old"] == ""
        assert changes[0]["new"] == "1"

    def test_key_removed(self):
        changes = de.diff_simple_dict({"a": "1"}, {})
        assert len(changes) == 1
        assert changes[0]["old"] == "1"
        assert changes[0]["new"] == ""


class TestDiffListOfDicts:
    def test_added_items(self):
        old = [{"name": "A", "value": "1"}]
        new = [{"name": "A", "value": "1"}, {"name": "B", "value": "2"}]
        result = de.diff_list_of_dicts(old, new)
        assert len(result["added"]) == 1
        assert result["added"][0]["name"] == "B"

    def test_removed_items(self):
        old = [{"name": "A"}, {"name": "B"}]
        new = [{"name": "A"}]
        result = de.diff_list_of_dicts(old, new)
        assert len(result["removed"]) == 1
        assert result["removed"][0]["name"] == "B"

    def test_modified_items(self):
        old = [{"name": "A", "val": "1"}]
        new = [{"name": "A", "val": "2"}]
        result = de.diff_list_of_dicts(old, new)
        assert len(result["modified"]) == 1
        assert result["modified"][0]["key"] == "A"

    def test_no_changes(self):
        items = [{"name": "A", "val": "1"}]
        result = de.diff_list_of_dicts(items, items)
        assert result["added"] == []
        assert result["removed"] == []
        assert result["modified"] == []

    def test_empty_lists(self):
        result = de.diff_list_of_dicts([], [])
        assert result == {"added": [], "removed": [], "modified": []}

    def test_custom_id_field(self):
        old = [{"id": "1", "val": "a"}]
        new = [{"id": "1", "val": "b"}]
        result = de.diff_list_of_dicts(old, new, id_field="id")
        assert len(result["modified"]) == 1


class TestDiffItem:
    def test_identical(self):
        item = {"id": "1", "name": "Test", "revision": "1"}
        assert de.diff_item(item, item) is None

    def test_simple_field_change(self):
        old = {"id": "1", "name": "Test", "revision": "1"}
        new = {"id": "1", "name": "Test", "revision": "2"}
        changes = de.diff_item(old, new)
        assert "revision" in changes
        assert changes["revision"]["old"] == "1"
        assert changes["revision"]["new"] == "2"

    def test_nested_ordered_dict_diff(self):
        old = {"features": OrderedDict([("A", {"bit": "0"})])}
        new = {"features": OrderedDict([("A", {"bit": "0"}), ("B", {"bit": "1"})])}
        changes = de.diff_item(old, new)
        assert "features" in changes
        assert "B" in changes["features"]["added"]

    def test_list_diff(self):
        old = {"revisions": [{"name": "r1", "summary": "first"}]}
        new = {"revisions": [{"name": "r1", "summary": "first"}, {"name": "r2", "summary": "second"}]}
        changes = de.diff_item(old, new)
        assert "revisions" in changes
        assert len(changes["revisions"]["added"]) == 1


class TestComputeDiff:
    def test_added_cluster(self):
        old = OrderedDict()
        new = OrderedDict([("OnOff.xml", {"id": "0x0006", "name": "OnOff", "revision": "6"})])
        result = de.compute_diff(old, new)
        assert "OnOff.xml" in result["added"]
        assert result["removed"] == {}
        assert len(result["unchanged"]) == 0

    def test_removed_cluster(self):
        old = OrderedDict([("OnOff.xml", {"id": "0x0006", "name": "OnOff", "revision": "6"})])
        new = OrderedDict()
        result = de.compute_diff(old, new)
        assert "OnOff.xml" in result["removed"]

    def test_unchanged_cluster(self):
        item = {"id": "0x0006", "name": "OnOff", "revision": "6"}
        old = OrderedDict([("OnOff.xml", item)])
        new = OrderedDict([("OnOff.xml", item)])
        result = de.compute_diff(old, new)
        assert "OnOff.xml" in result["unchanged"]
        assert len(result["modified"]) == 0

    def test_modified_cluster(self):
        old = OrderedDict([("OnOff.xml", {"id": "0x0006", "name": "OnOff", "revision": "5"})])
        new = OrderedDict([("OnOff.xml", {"id": "0x0006", "name": "OnOff", "revision": "6"})])
        result = de.compute_diff(old, new)
        assert "OnOff.xml" in result["modified"]
        assert result["modified"]["OnOff.xml"]["changes"]["revision"]["old"] == "5"
        assert result["modified"]["OnOff.xml"]["changes"]["revision"]["new"] == "6"


# ---------------------------------------------------------------------------
# Search / Filter
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase(self):
        assert de._normalize("OnOff") == "onoff"

    def test_strip_spaces(self):
        assert de._normalize("On Off") == "onoff"

    def test_strip_hyphens(self):
        assert de._normalize("fabric-scoped") == "fabricscoped"

    def test_strip_underscores(self):
        assert de._normalize("door_lock") == "doorlock"

    def test_combined(self):
        assert de._normalize("Door Lock-Test_Name") == "doorlocktestname"


class TestDeepMatch:
    def test_string_match(self):
        assert de._deep_match("OnOff Cluster", "onoff") is True

    def test_string_no_match(self):
        assert de._deep_match("DoorLock", "onoff") is False

    def test_dict_match(self):
        assert de._deep_match({"name": "OnOff", "id": "0x0006"}, "onoff") is True

    def test_dict_no_match(self):
        assert de._deep_match({"name": "DoorLock"}, "onoff") is False

    def test_list_match(self):
        assert de._deep_match(["foo", "OnOff"], "onoff") is True

    def test_nested_match(self):
        data = {"items": [{"name": "OnOff"}]}
        assert de._deep_match(data, "onoff") is True

    def test_non_string_non_container(self):
        assert de._deep_match(42, "onoff") is False


class TestElementNameMatch:
    def test_matches_name_field(self):
        obj = {"name": "Identify", "summary": "something else"}
        assert de._element_name_match(obj, "identify") is True

    def test_matches_code_field(self):
        obj = {"code": "IDENT", "summary": "unrelated"}
        assert de._element_name_match(obj, "ident") is True

    def test_ignores_summary_field(self):
        obj = {"name": "Other", "summary": "the identifying data"}
        assert de._element_name_match(obj, "identify") is False

    def test_ignores_deeply_nested_summary(self):
        obj = {"items": [{"name": "Foo", "summary": "identify the reason"}]}
        assert de._element_name_match(obj, "identify") is False

    def test_nested_dict_with_matching_name(self):
        obj = {"attributes": {"0x00": {"name": "IdentifyTime", "type": "uint16"}}}
        assert de._element_name_match(obj, "identify") is True

    def test_no_match_at_all(self):
        obj = {"name": "DoorLock", "attributes": {"0x00": {"name": "LockState"}}}
        assert de._element_name_match(obj, "identify") is False

    def test_list_of_dicts(self):
        obj = [{"name": "A"}, {"name": "Identify"}]
        assert de._element_name_match(obj, "identify") is True

    def test_plain_string_exact_match(self):
        assert de._element_name_match("identify", "identify") is True

    def test_plain_string_no_substring(self):
        # Plain string uses exact match, not substring
        assert de._element_name_match("identifying", "identify") is False

    def test_non_string_scalar(self):
        assert de._element_name_match(42, "identify") is False


class TestBroadSearchExcludesSummary:
    """Verify the broad fallback doesn't match prose text like summaries."""

    def _make_broad_diff(self):
        """A diff where no cluster names match 'identify', forcing broad fallback.
        Tests that only the diff delta is searched, not unchanged old/new data."""
        return {
            "added": {},
            "removed": {},
            "modified": OrderedDict([
                # Has "identifying" in summary of old/new — should NOT match
                ("ContentLauncher.xml", {
                    "name": "ContentLauncher",
                    "old": {"id": "0x050A", "name": "ContentLauncher",
                            "dataTypes": OrderedDict([
                                ("enum:ParameterEnum", {
                                    "kind": "enum", "name": "ParameterEnum",
                                    "items": [{"value": "1", "name": "Channel",
                                               "summary": "Channel represents the identifying data"}]
                                }),
                            ])},
                    "new": {"id": "0x050A", "name": "ContentLauncher",
                            "dataTypes": OrderedDict([
                                ("enum:ParameterEnum", {
                                    "kind": "enum", "name": "ParameterEnum",
                                    "items": [{"value": "1", "name": "Channel",
                                               "summary": "Channel represents the identifying data"}]
                                }),
                            ])},
                    "changes": {"dataTypes": {"added": OrderedDict(), "removed": OrderedDict(), "modified": OrderedDict()}},
                }),
                # Has "AddGroupIfIdentifying" in old/new but NOT in changes — should NOT match
                ("Groups.xml", {
                    "name": "Groups",
                    "old": {"id": "0x0004", "name": "Groups",
                            "commands": OrderedDict([
                                ("0x05_AddGroupIfIdentifying", {"name": "AddGroupIfIdentifying", "id": "0x05"}),
                            ])},
                    "new": {"id": "0x0004", "name": "Groups",
                            "commands": OrderedDict([
                                ("0x05_AddGroupIfIdentifying", {"name": "AddGroupIfIdentifying", "id": "0x05"}),
                            ])},
                    "changes": {"revision": {"old": "4", "new": "5"}},
                }),
                # Has "IdentifyTime" as an ADDED attribute in changes — SHOULD match
                ("Scenes.xml", {
                    "name": "Scenes",
                    "old": {"id": "0x0005", "name": "Scenes"},
                    "new": {"id": "0x0005", "name": "Scenes",
                            "attributes": OrderedDict([
                                ("0x0010", {"name": "IdentifyTime", "type": "uint16"}),
                            ])},
                    "changes": {
                        "attributes": {
                            "added": OrderedDict([("0x0010", {"name": "IdentifyTime", "type": "uint16"})]),
                            "removed": OrderedDict(),
                            "modified": OrderedDict(),
                        },
                    },
                }),
            ]),
            "unchanged": [],
        }

    def test_broad_excludes_summary_in_old_new(self):
        diff = self._make_broad_diff()
        result = de.filter_diff(diff, "identify")
        # ContentLauncher: "identifying" is only in old/new summary, not in changes
        assert "ContentLauncher.xml" not in result["modified"]

    def test_broad_excludes_unchanged_element_in_old_new(self):
        diff = self._make_broad_diff()
        result = de.filter_diff(diff, "identify")
        # Groups: "AddGroupIfIdentifying" exists in old/new but wasn't changed
        assert "Groups.xml" not in result["modified"]

    def test_broad_includes_matching_change_delta(self):
        diff = self._make_broad_diff()
        result = de.filter_diff(diff, "identify")
        # Scenes: "IdentifyTime" was ADDED in the changes delta
        assert "Scenes.xml" in result["modified"]


class TestFilterDiff:
    def _make_diff(self):
        return {
            "added": {
                "OnOff.xml": {"id": "0x0006", "name": "OnOff", "revision": "6",
                              "attributes": OrderedDict([("0x0000", {"name": "OnOff", "type": "bool"})])},
                "DoorLock.xml": {"id": "0x0101", "name": "DoorLock", "revision": "7",
                                 "attributes": OrderedDict([("0x0000", {"name": "LockState", "type": "enum8"})])},
            },
            "removed": {
                "Old.xml": {"id": "0x0099", "name": "OldCluster", "revision": "1"},
            },
            "modified": OrderedDict([
                ("Test.xml", {
                    "name": "TestCluster",
                    "old": {"id": "0x0050", "name": "TestCluster", "revision": "1",
                            "attributes": OrderedDict()},
                    "new": {"id": "0x0050", "name": "TestCluster", "revision": "2",
                            "attributes": OrderedDict([("0x0001", {"name": "OnOff", "type": "bool"})])},
                    "changes": {
                        "revision": {"old": "1", "new": "2"},
                        "attributes": {
                            "added": OrderedDict([("0x0001", {"name": "OnOff", "type": "bool"})]),
                            "removed": OrderedDict(),
                            "modified": OrderedDict(),
                        },
                    },
                }),
            ]),
            "unchanged": ["Unchanged.xml"],
        }

    def test_filter_by_cluster_name(self):
        diff = self._make_diff()
        result = de.filter_diff(diff, "onoff")
        assert "OnOff.xml" in result["added"]

    def test_filter_excludes_non_matching(self):
        diff = self._make_diff()
        result = de.filter_diff(diff, "doorlock")
        assert "OnOff.xml" not in result["added"] or result["_focused"]

    def test_filter_by_element_name(self):
        diff = self._make_diff()
        result = de.filter_diff(diff, "onoff")
        # Should match the modified cluster that has an OnOff attribute added
        assert result["_focused"] is True

    def test_filter_empty_term_not_called(self):
        # The engine skips filtering on empty string, tested here as a safeguard
        diff = self._make_diff()
        # Calling with empty string should not crash
        result = de.filter_diff(diff, "")
        # Empty term matches nothing via _normalize (empty string is in everything)
        assert isinstance(result, dict)

    def test_filter_no_match_falls_back_to_broad(self):
        diff = self._make_diff()
        result = de.filter_diff(diff, "zzzznonexistent")
        # Should return a dict with _focused = False
        assert result["_focused"] is False

    def test_filter_unchanged_by_name(self):
        diff = self._make_diff()
        result = de.filter_diff(diff, "unchanged")
        assert "Unchanged.xml" in result["unchanged"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestMakeSerializable:
    def test_ordered_dict_to_dict(self):
        od = OrderedDict([("a", 1), ("b", OrderedDict([("c", 2)]))])
        result = de.make_serializable(od)
        assert isinstance(result, dict)
        assert isinstance(result["b"], dict)
        assert not isinstance(result, OrderedDict)

    def test_list_preserved(self):
        result = de.make_serializable([OrderedDict([("a", 1)])])
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_scalar_passthrough(self):
        assert de.make_serializable("hello") == "hello"
        assert de.make_serializable(42) == 42
        assert de.make_serializable(None) is None


# ---------------------------------------------------------------------------
# run_diff — End-to-End Integration
# ---------------------------------------------------------------------------

class TestRunDiff:
    def test_cluster_diff_json_output(self):
        old_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        new_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        result_json = de.run_diff(old_map, new_map, "clusters", "", "clusters")
        result = json.loads(result_json)
        assert "OnOff.xml" in result["unchanged"]

    def test_cluster_added(self):
        old_map = {}
        new_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "", "clusters"))
        assert "OnOff.xml" in result["added"]

    def test_cluster_removed(self):
        old_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        new_map = {}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "", "clusters"))
        assert "OnOff.xml" in result["removed"]

    def test_cluster_modified(self):
        modified_xml = CLUSTER_WITH_FEATURES_XML.replace('revision="6"', 'revision="7"', 1)
        old_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        new_map = {"OnOff.xml": modified_xml}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "", "clusters"))
        assert "OnOff.xml" in result["modified"]

    def test_device_type_diff(self):
        old_map = {"Light.xml": MINIMAL_DEVICE_TYPE_XML}
        new_map = {"Light.xml": MINIMAL_DEVICE_TYPE_XML}
        result = json.loads(de.run_diff(old_map, new_map, "device_types", "", "device_types"))
        assert "Light.xml" in result["unchanged"]

    def test_device_type_added(self):
        old_map = {}
        new_map = {"Light.xml": MINIMAL_DEVICE_TYPE_XML}
        result = json.loads(de.run_diff(old_map, new_map, "device_types", "", "device_types"))
        assert "Light.xml" in result["added"]

    def test_filter_applied(self):
        old_map = {}
        new_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML,
                    "DoorLock.xml": CLUSTER_WITH_DATATYPES_XML}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "OnOff", "clusters"))
        assert "OnOff.xml" in result["added"]

    def test_invalid_xml_skipped(self):
        old_map = {"bad.xml": "not xml"}
        new_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "", "clusters"))
        assert "OnOff.xml" in result["added"]
        assert "bad.xml" not in result["added"]
        assert "bad.xml" not in result["removed"]

    def test_both_empty_maps(self):
        result = json.loads(de.run_diff({}, {}, "clusters", "", "clusters"))
        assert result["added"] == {}
        assert result["removed"] == {}
        assert result["unchanged"] == []

    def test_result_is_valid_json(self):
        old_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        new_map = {"OnOff.xml": CLUSTER_WITH_FEATURES_XML}
        result_str = de.run_diff(old_map, new_map, "clusters", "", "clusters")
        parsed = json.loads(result_str)
        assert isinstance(parsed, dict)

    def test_multiple_clusters_mixed(self):
        """Test with multiple files: one added, one removed, one modified, one unchanged."""
        old_cluster_a = '<cluster id="0x0001" name="A" revision="1"></cluster>'
        old_cluster_b = '<cluster id="0x0002" name="B" revision="1"></cluster>'
        new_cluster_b = '<cluster id="0x0002" name="B" revision="2"></cluster>'
        new_cluster_c = '<cluster id="0x0003" name="C" revision="1"></cluster>'
        old_cluster_d = '<cluster id="0x0004" name="D" revision="1"></cluster>'

        old_map = {"a.xml": old_cluster_a, "b.xml": old_cluster_b, "d.xml": old_cluster_d}
        new_map = {"b.xml": new_cluster_b, "c.xml": new_cluster_c, "d.xml": old_cluster_d}
        result = json.loads(de.run_diff(old_map, new_map, "clusters", "", "clusters"))

        assert "a.xml" in result["removed"]
        assert "c.xml" in result["added"]
        assert "b.xml" in result["modified"]
        assert "d.xml" in result["unchanged"]


# ---------------------------------------------------------------------------
# Integration — Real XML Files (if available)
# ---------------------------------------------------------------------------

class TestRealXmlFiles:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_model")

    @pytest.fixture
    def has_data(self):
        if not os.path.isdir(self.DATA_DIR):
            pytest.skip("data_model directory not found")
        versions = [d for d in os.listdir(self.DATA_DIR) if os.path.isdir(os.path.join(self.DATA_DIR, d))]
        if len(versions) < 2:
            pytest.skip("need at least 2 versions")
        versions.sort(key=lambda v: [int(x) for x in v.split(".")])
        return versions

    def _load_xml_map(self, version, category):
        cat_dir = os.path.join(self.DATA_DIR, version, category)
        if not os.path.isdir(cat_dir):
            return {}
        result = {}
        for f in os.listdir(cat_dir):
            if f.endswith(".xml"):
                with open(os.path.join(cat_dir, f)) as fh:
                    result[f] = fh.read()
        return result

    def test_parse_all_cluster_xmls(self, has_data):
        """Every cluster XML across all versions should parse without error."""
        for ver in has_data:
            xml_map = self._load_xml_map(ver, "clusters")
            for fname, xml_str in xml_map.items():
                result = de.parse_cluster_xml_string(xml_str)
                # Some files may be non-cluster roots (skip those), but should never crash
                if result is not None:
                    assert result["name"], f"{ver}/clusters/{fname} has no name"

    def test_parse_all_device_type_xmls(self, has_data):
        """Every device type XML across all versions should parse without error."""
        for ver in has_data:
            xml_map = self._load_xml_map(ver, "device_types")
            for fname, xml_str in xml_map.items():
                result = de.parse_device_type_xml_string(xml_str)
                if result is not None:
                    assert result["name"], f"{ver}/device_types/{fname} has no name"

    def test_diff_adjacent_versions(self, has_data):
        """Diff between adjacent versions should produce valid JSON output."""
        v1, v2 = has_data[0], has_data[1]
        for cat in ("clusters", "device_types"):
            old_map = self._load_xml_map(v1, cat)
            new_map = self._load_xml_map(v2, cat)
            result_str = de.run_diff(old_map, new_map, cat, "", cat)
            result = json.loads(result_str)
            assert "added" in result
            assert "removed" in result
            assert "modified" in result
            assert "unchanged" in result

    def test_diff_first_to_last_version(self, has_data):
        """Diff between the first and last version should work end-to-end."""
        v_first, v_last = has_data[0], has_data[-1]
        old_map = self._load_xml_map(v_first, "clusters")
        new_map = self._load_xml_map(v_last, "clusters")
        result_str = de.run_diff(old_map, new_map, "clusters", "", "clusters")
        result = json.loads(result_str)
        # Over many versions, there should be at least some added or modified clusters
        total_changes = len(result["added"]) + len(result["modified"])
        assert total_changes > 0, "Expected at least some changes between first and last version"

    def test_diff_with_search_filter(self, has_data):
        """Filtering a real diff with a common term should not crash."""
        v1, v2 = has_data[-2], has_data[-1]
        old_map = self._load_xml_map(v1, "clusters")
        new_map = self._load_xml_map(v2, "clusters")
        result_str = de.run_diff(old_map, new_map, "clusters", "OnOff", "clusters")
        result = json.loads(result_str)
        assert isinstance(result, dict)
