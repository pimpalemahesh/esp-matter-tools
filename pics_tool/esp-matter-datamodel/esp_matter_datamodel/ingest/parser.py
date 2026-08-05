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
"""Parse individual cluster and device-type XML documents into model objects."""

from __future__ import annotations

import logging
from xml.etree.ElementTree import Element

from ..model.conformance import Conformance
from ..model.elements import (
    Attribute,
    Cluster,
    ClusterRequirement,
    Command,
    DeviceType,
    Event,
    Feature,
)
from .conformance_parser import Resolver, find_conformance

logger = logging.getLogger(__name__)


def norm_id(value: str, width: int) -> str:
    """Normalize a hex id like ``0x6`` / ``0X0006`` to ``0x0006`` (lowercase)."""
    return f"0x{int(value, 16):0{width}x}"


# --------------------------------------------------------------------------- #
# Clusters
# --------------------------------------------------------------------------- #


def parse_cluster(root: Element) -> Cluster:
    # Abstract base clusters (hierarchy="base") have no id; they are not
    # standalone clusters but templates that derived clusters inherit from.
    cluster_id = norm_id(root.attrib["id"], 4) if root.attrib.get("id") else ""
    name = _cluster_name(root)
    classification = root.find("classification")
    pics = classification.attrib.get("picsCode", "") if classification is not None else ""
    revision = int(root.attrib.get("revision", "1"))

    resolver = _build_cluster_resolver(root, name)

    features: dict[int, Feature] = {}
    features_el = root.find("features")
    if features_el is not None:
        for fe in features_el.findall("feature"):
            bit = int(fe.attrib["bit"])
            features[bit] = Feature(
                bit=bit,
                mask=1 << bit,
                code=fe.attrib.get("code", ""),
                name=fe.attrib.get("name", ""),
                conformance=find_conformance(fe, resolver),
            )

    attributes: dict[str, Attribute] = {}
    attrs_el = root.find("attributes")
    if attrs_el is not None:
        for ae in attrs_el.findall("attribute"):
            aid = norm_id(ae.attrib["id"], 4)
            attributes[aid] = Attribute(id=aid, name=ae.attrib.get("name", ""),
                                        conformance=find_conformance(ae, resolver))

    accepted: dict[str, Command] = {}
    generated: dict[str, Command] = {}
    commands_el = root.find("commands")
    if commands_el is not None:
        for ce in commands_el.findall("command"):
            cid = norm_id(ce.attrib["id"], 2)
            command = Command(id=cid, name=ce.attrib.get("name", ""),
                              conformance=find_conformance(ce, resolver))
            direction = ce.attrib.get("direction", "commandToServer")
            # Server-generated (responses / commands to client) -> generated (.Tx);
            # server-received commands -> accepted (.Rsp).
            if direction in ("responseFromServer", "commandToClient"):
                generated[cid] = command
            else:
                accepted[cid] = command

    events: dict[str, Event] = {}
    events_el = root.find("events")
    if events_el is not None:
        for ee in events_el.findall("event"):
            eid = norm_id(ee.attrib["id"], 2)
            events[eid] = Event(id=eid, name=ee.attrib.get("name", ""),
                                priority=ee.attrib.get("priority"),
                                conformance=find_conformance(ee, resolver))

    return Cluster(
        id=cluster_id, name=name, pics=pics, revision=revision,
        features=features, attributes=attributes,
        accepted_commands=accepted, generated_commands=generated, events=events,
    )


def _cluster_name(root: Element) -> str:
    # Prefer the canonical short name from <clusterIds> (e.g. "On/Off") which is
    # how device types reference clusters; fall back to the root name.
    cluster_ids = root.find("clusterIds")
    if cluster_ids is not None:
        first = cluster_ids.find("clusterId")
        if first is not None and first.attrib.get("name"):
            return first.attrib["name"]
    return root.attrib.get("name", "")


def _build_cluster_resolver(root: Element, context: str) -> Resolver:
    from ..model.conformance import FeatureRef

    features_by_key: dict[str, FeatureRef] = {}
    features_el = root.find("features")
    if features_el is not None:
        for fe in features_el.findall("feature"):
            bit = int(fe.attrib["bit"])
            ref = FeatureRef(code=fe.attrib.get("code", ""), bit=bit)
            # Conformance terms reference features by code (usually) or name.
            if fe.attrib.get("code"):
                features_by_key[fe.attrib["code"]] = ref
            if fe.attrib.get("name"):
                features_by_key[fe.attrib["name"]] = ref

    attribute_ids_by_name: dict[str, str] = {}
    attrs_el = root.find("attributes")
    if attrs_el is not None:
        for ae in attrs_el.findall("attribute"):
            if ae.attrib.get("name"):
                attribute_ids_by_name[ae.attrib["name"]] = norm_id(ae.attrib["id"], 4)

    command_ids_by_name: dict[str, str] = {}
    commands_el = root.find("commands")
    if commands_el is not None:
        for ce in commands_el.findall("command"):
            if ce.attrib.get("name"):
                command_ids_by_name[ce.attrib["name"]] = norm_id(ce.attrib["id"], 2)

    return Resolver(features_by_key, attribute_ids_by_name, command_ids_by_name,
                    context=f"cluster {context}")


# --------------------------------------------------------------------------- #
# Device types
# --------------------------------------------------------------------------- #


def parse_device_type(root: Element, clusters_by_id: dict[str, Cluster]) -> DeviceType:
    # The Base Device Type has no id attribute; synthesize 0x0000 for it.
    dt_id = norm_id(root.attrib["id"], 4) if root.attrib.get("id") else "0x0000"
    name = root.attrib.get("name", "")
    revision = int(root.attrib.get("revision", "1"))

    server: dict[str, ClusterRequirement] = {}
    client: dict[str, ClusterRequirement] = {}

    clusters_el = root.find("clusters")
    if clusters_el is not None:
        for ce in clusters_el.findall("cluster"):
            req = _parse_cluster_requirement(ce, clusters_by_id, name)
            side = ce.attrib.get("side", "server")
            (client if side == "client" else server)[req.id] = req

    return DeviceType(id=dt_id, name=name, revision=revision,
                      server_clusters=server, client_clusters=client)


def _parse_cluster_requirement(ce: Element, clusters_by_id: dict[str, Cluster],
                               dt_name: str) -> ClusterRequirement:
    cid = norm_id(ce.attrib["id"], 4)
    cname = ce.attrib.get("name", "")
    definition = clusters_by_id.get(cid)
    resolver = _build_requirement_resolver(definition, f"{dt_name}/{cname}")

    conformance = find_conformance(ce, resolver)

    feature_overrides: dict[int, Conformance] = {}
    features_el = ce.find("features")
    if features_el is not None and definition is not None:
        code_to_bit = {f.code: f.bit for f in definition.features.values() if f.code}
        name_to_bit = {f.name: f.bit for f in definition.features.values() if f.name}
        for fe in features_el.findall("feature"):
            override = _override_conformance(fe, resolver)
            if override is None:
                continue
            key = fe.attrib.get("code") or fe.attrib.get("name")
            bit = code_to_bit.get(key, name_to_bit.get(key))
            if bit is None:
                logger.warning("device-type %s: unresolved feature %r on cluster %s",
                               dt_name, key, cname)
                continue
            feature_overrides[bit] = override

    attribute_overrides: dict[str, Conformance] = {}
    attrs_el = ce.find("attributes")
    if attrs_el is not None:
        for ae in attrs_el.findall("attribute"):
            override = _override_conformance(ae, resolver)
            if override is None:
                continue
            code = ae.attrib.get("code") or ae.attrib.get("id")
            if code is None:
                continue
            attribute_overrides[norm_id(code, 4)] = override

    command_overrides: dict[str, Conformance] = {}
    commands_el = ce.find("commands")
    if commands_el is not None:
        for cmd in commands_el.findall("command"):
            override = _override_conformance(cmd, resolver)
            if override is None:
                continue
            code = cmd.attrib.get("code") or cmd.attrib.get("id")
            if code is None:
                continue
            command_overrides[norm_id(code, 2)] = override

    return ClusterRequirement(
        id=cid, name=cname, conformance=conformance,
        feature_overrides=feature_overrides,
        attribute_overrides=attribute_overrides,
        command_overrides=command_overrides,
    )


def _override_conformance(el: Element, resolver: Resolver) -> Conformance | None:
    """Return an element's conformance override, or None if it has none.

    In device types many nested elements carry only a <constraint> (no conform),
    which imposes no requirement change and is skipped.
    """
    from .conformance_parser import _CONFORM_TAGS

    if not any(child.tag in _CONFORM_TAGS for child in el):
        return None
    return find_conformance(el, resolver)


def _build_requirement_resolver(definition: Cluster | None, context: str) -> Resolver:
    from ..model.conformance import FeatureRef

    features_by_key: dict[str, FeatureRef] = {}
    attribute_ids_by_name: dict[str, str] = {}
    command_ids_by_name: dict[str, str] = {}
    if definition is not None:
        for f in definition.features.values():
            ref = FeatureRef(code=f.code, bit=f.bit)
            if f.code:
                features_by_key[f.code] = ref
            if f.name:
                features_by_key[f.name] = ref
        attribute_ids_by_name = {a.name: a.id for a in definition.attributes.values() if a.name}
        for cmd in list(definition.accepted_commands.values()) + \
                list(definition.generated_commands.values()):
            if cmd.name:
                command_ids_by_name[cmd.name] = cmd.id
    return Resolver(features_by_key, attribute_ids_by_name, command_ids_by_name,
                    context=f"device-type {context}")
