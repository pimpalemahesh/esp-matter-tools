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
"""Input adapter: a PICS ``Selection`` -> target-neutral ``DataModelPlan``.

All PICS-specific knowledge (parsing claim codes into features / attributes /
commands / events / cluster sides, and deciding what the device-type baseline
already builds) lives here. The output IR carries only spec identity + names.
"""

from __future__ import annotations

import re

from esp_matter_datamodel.model.elements import DataModel

from ..claims import FEATURE_CODE_RE, GATEWAY_RE, pics_to_cluster
from .ir import ClusterSide, DataModelPlan, ElementRef, EndpointPlan

# Server-side optional attribute / command / event PICS codes, e.g. "LVL.S.A0012",
# "LVL.S.C00.Rsp", "DRLK.S.E00". (Features are FEATURE_CODE_RE; sides are GATEWAY_RE.)
ATTR_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.A(?P<id>[0-9A-Fa-f]{4})$")
CMD_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.C(?P<id>[0-9A-Fa-f]{2})(?:\.(?:Rsp|Tx))?$")
EVENT_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.E(?P<id>[0-9A-Fa-f]{2})$")


def _baseline_cluster_ids(model: DataModel, dt) -> set[str]:
    # endpoint::<type>::create() builds the device type's own server clusters
    # PLUS the Base Device Type's (Descriptor, Binding, ...).
    baseline = set(dt.server_clusters.keys())
    if model.base_device_type is not None:
        baseline |= set(model.base_device_type.server_clusters.keys())
    return baseline


def _classify(model: DataModel, claims, baseline_cluster_ids: set[str]):
    """Claim codes -> (features, attributes, commands, events, sides, unknown)."""
    clusters_by_pics = pics_to_cluster(model)
    features: list[ElementRef] = []
    attributes: list[ElementRef] = []
    commands: list[ElementRef] = []
    events: list[ElementRef] = []
    sides: dict[str, ClusterSide] = {}
    unknown: list[str] = []

    for code in claims or []:
        fm = FEATURE_CODE_RE.match(code)
        if fm:
            cid = clusters_by_pics.get(fm.group("pics"))
            if cid is None:
                continue
            cl = model.clusters[cid]
            feat = cl.features.get(int(fm.group("bit"), 16))
            if feat is not None:
                features.append(ElementRef(cid, cl.name, hex(int(fm.group("bit"), 16)), feat.name))
            continue
        am = ATTR_CODE_RE.match(code)
        if am:
            cid = clusters_by_pics.get(am.group("pics"))
            if cid is None:
                continue
            cl = model.clusters[cid]
            key = "0x" + am.group("id").lower()
            attr = cl.attributes.get(key)
            if attr is not None:
                attributes.append(ElementRef(cid, cl.name, key, attr.name))
            continue
        cm = CMD_CODE_RE.match(code)
        if cm:
            cid = clusters_by_pics.get(cm.group("pics"))
            if cid is None:
                continue
            cl = model.clusters[cid]
            key = "0x" + cm.group("id").lower()
            cmd = cl.accepted_commands.get(key) or cl.generated_commands.get(key)
            if cmd is not None:
                commands.append(ElementRef(cid, cl.name, key, cmd.name))
            continue
        em = EVENT_CODE_RE.match(code)
        if em:
            cid = clusters_by_pics.get(em.group("pics"))
            if cid is None:
                continue
            cl = model.clusters[cid]
            key = "0x" + em.group("id").lower()
            event = cl.events.get(key)
            if event is not None:
                events.append(ElementRef(cid, cl.name, key, event.name))
            continue
        gm = GATEWAY_RE.match(code)
        if gm:
            cid = clusters_by_pics.get(gm.group("pics"))
            is_server = gm.group("side") == "S"
            if cid is None:
                unknown.append(f"{gm.group('pics')} "
                               f"({'server' if is_server else 'client'} side, {code})")
                continue
            # A server cluster the device type already builds needs nothing extra.
            if is_server and cid in baseline_cluster_ids:
                continue
            cl = model.clusters[cid]
            side = sides.setdefault(cid, ClusterSide(cid, cl.name))
            if is_server:
                side.server = True
            else:
                side.client = True
    return features, attributes, commands, events, list(sides.values()), unknown


def build_plan(selection, model: DataModel) -> DataModelPlan:
    """Build the target-neutral plan for a PICS ``Selection``."""
    endpoints: list[EndpointPlan] = []
    for epid, ep in enumerate(selection.endpoints, start=1):
        names: list[str] = []
        baseline: set[str] = set()
        for name in ep.device_types:
            dt = model.device_type_by_name(name)
            if dt is None:
                raise ValueError(
                    f"device type {name!r} not found in the {model.spec_version} data model")
            names.append(dt.name)
            baseline |= _baseline_cluster_ids(model, dt)
        feats, attrs, cmds, evts, sides, unknown = _classify(model, ep.claims, baseline)
        endpoints.append(EndpointPlan(
            index=epid, device_types=names, features=feats, attributes=attrs,
            commands=cmds, events=evts, sides=sides, unknown_sides=unknown))
    return DataModelPlan(spec_version=model.spec_version, endpoints=endpoints)
