# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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
"""Cluster PICS engine: device type + profile -> enabled cluster PICS codes.

Strict mandatory-only (design decision): a cluster/element is enabled iff the
data-model conformance makes it MANDATORY for the resolved device state. The
device state comes from the profile: transport -> active conditions + seeded
CNET features (D11), the device type's element overrides winning over the
cluster baseline (D12), and a monotone feature-mask fixpoint (D10).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.resources import files

import yaml
from esp_matter_datamodel.model.conformance import ConformanceContext, evaluate
from esp_matter_datamodel.model.elements import (
    Cluster,
    ClusterRequirement,
    DataModel,
    DeviceType,
)

from . import pics_codes
from .profile import DeviceProfile

logger = logging.getLogger(__name__)

ROOT_NODE_DEVICE_TYPE_ID = "0x0016"


@dataclass
class EndpointPics:
    endpoint: int
    device_type_id: str
    device_type_name: str
    pics: set[str] = field(default_factory=set)
    cluster_ids: set[str] = field(default_factory=set)  # ids of server clusters actually enabled
    # ids of clusters this endpoint is a mandatory CLIENT of. Kept separate from
    # cluster_ids on purpose: node facts (OTA/bridge) must reflect what the node
    # HOSTS, not what it talks to.
    client_cluster_ids: set[str] = field(default_factory=set)


def load_transport_map() -> dict:
    resource = files("pics_tool").joinpath("transport_map.yaml")
    return yaml.safe_load(resource.read_text(encoding="utf-8"))


def active_conditions(profile: DeviceProfile, transport_map: dict) -> frozenset[str]:
    conditions: set[str] = set()
    transports = transport_map.get("transports", {})
    for t in profile.transport:
        entry = transports.get(t, {})
        conditions.update(entry.get("conditions", []))
    if profile.is_icd:
        conditions.add("LIT" if profile.icd_mode == "lit" else "SIT")
    else:
        conditions.add("Active")
    return frozenset(conditions)


def transport_feature_seeds(profile: DeviceProfile, transport_map: dict) -> dict[str, set[str]]:
    """Return {cluster_id: {feature_code, ...}} the transport forces on."""
    seeds: dict[str, set[str]] = {}
    transports = transport_map.get("transports", {})
    for t in profile.transport:
        for cid, codes in transports.get(t, {}).get("cluster_features", {}).items():
            seeds.setdefault(cid, set()).update(codes)
    return seeds


def _merge_requirements(device_types: list[DeviceType], base: DeviceType | None,
                        side: str = "server") -> dict[str, ClusterRequirement]:
    """Cluster requirements for an endpoint: base + all device types, one side.

    On a duplicate cluster id, a mandatory requirement wins over a
    non-mandatory one so a node-level device type can't weaken a base/root req.
    """
    merged: dict[str, ClusterRequirement] = {}
    sources = ([base] if base is not None else []) + list(device_types)
    for src in sources:
        reqs = src.server_clusters if side == "server" else src.client_clusters
        for cid, req in reqs.items():
            existing = merged.get(cid)
            if existing is None or (existing.conformance.type != "mandatory"
                                    and req.conformance.type == "mandatory"):
                merged[cid] = req
    return merged


def _resolve_device_type(model: DataModel, name: str) -> DeviceType:
    dt = model.device_type_by_name(name)
    if dt is None:
        raise ValueError(f"device type {name!r} not found in data model")
    return dt


def generate_cluster_pics(
    model: DataModel, profile: DeviceProfile, transport_map: dict | None = None,
    extra_feature_seeds: dict[str, set[str]] | None = None,
) -> list[EndpointPics]:
    """Generate per-endpoint PICS.

    ``extra_feature_seeds`` ({cluster_id: {feature_code, ...}}) lets a caller
    force optional features ON (e.g. the user's answers in the web UI); the
    conformance fixpoint then pulls in everything those features make mandatory,
    so a user choice re-enters the engine instead of being a raw row flip.
    """
    transport_map = transport_map or load_transport_map()
    conditions = active_conditions(profile, transport_map)
    seeds = transport_feature_seeds(profile, transport_map)
    for cid, codes in (extra_feature_seeds or {}).items():
        seeds.setdefault(cid, set()).update(codes)

    app_dt = _resolve_device_type(model, profile.device_type)
    node_dts = [_resolve_device_type(model, n) for n in profile.node_device_types]
    root_dt = model.device_types.get(ROOT_NODE_DEVICE_TYPE_ID)

    # EP0 = Root Node + any node-level device types (OTA Requestor, Aggregator, ...);
    # EP1 = the application device type. Base device type merges into both.
    ep0_dts = ([root_dt] if root_dt is not None else []) + node_dts
    layout: list[tuple[int, list[DeviceType]]] = []
    if ep0_dts:
        layout.append((0, ep0_dts))
    layout.append((1, [app_dt]))

    endpoints: list[EndpointPics] = []
    for epid, dts in layout:
        result = EndpointPics(epid, dts[0].id, dts[0].name)
        for cid, req in _merge_requirements(dts, model.base_device_type).items():
            enabled = _enable_cluster(req, model.clusters.get(cid), conditions,
                                      seeds.get(cid, set()))
            if enabled:
                result.pics |= enabled
                result.cluster_ids.add(cid)
        for cid, req in _merge_requirements(dts, model.base_device_type, "client").items():
            enabled = _enable_client_cluster(req, model.clusters.get(cid), conditions)
            if enabled:
                result.pics |= enabled
                result.client_cluster_ids.add(cid)
        endpoints.append(result)
    return endpoints


def all_enabled_cluster_ids(endpoints: list[EndpointPics]) -> set[str]:
    ids: set[str] = set()
    for ep in endpoints:
        ids |= ep.cluster_ids
    return ids


def _enable_cluster(
    req: ClusterRequirement,
    definition: Cluster | None,
    conditions: frozenset[str],
    seed_codes: set[str],
) -> set[str]:
    # Cluster presence never depends on cluster element state -> empty ctx + conditions.
    presence_ctx = ConformanceContext(active_conditions=conditions)
    if not evaluate(req.conformance, presence_ctx).is_mandatory():
        return set()

    if definition is None or not definition.pics:
        logger.warning("cluster %s present but no definition/pics; emitting usage only", req.id)
        return set()

    pics = definition.pics
    enabled = {pics_codes.cluster_role(pics)}

    mask = _feature_mask_fixpoint(definition, req, conditions, seed_codes)
    for f in definition.features.values():
        if mask & f.mask:
            enabled.add(pics_codes.feature(pics, f.bit))

    attr_ids, accepted_ids, generated_ids = _element_fixpoint(
        definition, req, conditions, mask
    )
    for aid in attr_ids:
        enabled.add(pics_codes.attribute(pics, aid))
    for cid in accepted_ids:
        enabled.add(pics_codes.accepted_command(pics, cid))
    for cid in generated_ids:
        enabled.add(pics_codes.generated_command(pics, cid))

    ctx = _ctx(mask, conditions, definition.revision, attr_ids, accepted_ids | generated_ids)
    for eid, ev in definition.events.items():
        if evaluate(ev.conformance, ctx).is_mandatory():
            enabled.add(pics_codes.event(pics, eid))

    return enabled


def _enable_client_cluster(
    req: ClusterRequirement,
    definition: Cluster | None,
    conditions: frozenset[str],
) -> set[str]:
    """Client-side PICS for a device type's mandatory client cluster.

    A client's testable surface is the commands it transmits: the templates
    carry ``<PICS>.C`` plus ``<PICS>.C.Cxx.Tx`` mirroring the cluster's accepted
    commands (a Dimmer Switch client sends On/Off/Toggle). We enable the client
    role and the Tx codes for every command that is mandatory at the cluster
    baseline (feature-gated optional commands stay off -- the *server* picks the
    features, and the client cannot know them at generation time).
    """
    presence_ctx = ConformanceContext(active_conditions=conditions)
    if not evaluate(req.conformance, presence_ctx).is_mandatory():
        return set()
    if definition is None or not definition.pics:
        logger.warning("client cluster %s present but no definition/pics", req.id)
        return set()

    pics = definition.pics
    enabled = {pics_codes.cluster_role(pics, pics_codes.CLIENT)}
    ctx = _ctx(0, conditions, definition.revision, set(), set())
    for cid, cmd in definition.accepted_commands.items():
        conf = req.command_overrides.get(cid, cmd.conformance)
        if evaluate(conf, ctx).is_mandatory():
            enabled.add(pics_codes.client_tx_command(pics, cid))
    return enabled


def _ctx(mask, conditions, revision, attr_ids, cmd_ids) -> ConformanceContext:
    return ConformanceContext(
        feature_mask=mask,
        attribute_ids=frozenset(attr_ids),
        command_ids=frozenset(cmd_ids),
        cluster_revision=revision,
        active_conditions=conditions,
    )


def _feature_conformance(req: ClusterRequirement, bit: int, fallback):
    # D12: device-type override wins when present, else the cluster spec.
    return req.feature_overrides.get(bit, fallback)


def _feature_mask_fixpoint(definition, req, conditions, seed_codes) -> int:
    code_to_bit = {f.code: f.bit for f in definition.features.values() if f.code}
    mask = 0
    for code in seed_codes:
        bit = code_to_bit.get(code)
        if bit is not None:
            mask |= 1 << bit
        else:
            logger.warning("cluster %s: seeded feature code %r not found", definition.id, code)

    changed = True
    while changed:  # monotone: mask only grows, bounded by #features
        changed = False
        ctx = _ctx(mask, conditions, definition.revision, set(), set())
        for f in definition.features.values():
            if mask & f.mask:
                continue
            conf = _feature_conformance(req, f.bit, f.conformance)
            if evaluate(conf, ctx).is_mandatory():
                mask |= f.mask
                changed = True
    return mask


def _element_fixpoint(definition, req, conditions, mask):
    attr_ids: set[str] = set()
    accepted_ids: set[str] = set()
    generated_ids: set[str] = set()

    changed = True
    while changed:
        changed = False
        ctx = _ctx(mask, conditions, definition.revision, attr_ids,
                   accepted_ids | generated_ids)
        for aid, attr in definition.attributes.items():
            if aid in attr_ids:
                continue
            conf = req.attribute_overrides.get(aid, attr.conformance)
            if evaluate(conf, ctx).is_mandatory():
                attr_ids.add(aid)
                changed = True
        for cid, cmd in definition.accepted_commands.items():
            if cid in accepted_ids:
                continue
            conf = req.command_overrides.get(cid, cmd.conformance)
            if evaluate(conf, ctx).is_mandatory():
                accepted_ids.add(cid)
                changed = True
        for cid, cmd in definition.generated_commands.items():
            if cid in generated_ids:
                continue
            conf = req.command_overrides.get(cid, cmd.conformance)
            if evaluate(conf, ctx).is_mandatory():
                generated_ids.add(cid)
                changed = True

    return attr_ids, accepted_ids, generated_ids
