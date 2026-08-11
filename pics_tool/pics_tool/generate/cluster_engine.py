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
    app_endpoints: list[list[str]] | None = None,
    per_endpoint_feature_seeds: dict[int, dict[str, set[str]]] | None = None,
) -> list[EndpointPics]:
    """Generate per-endpoint PICS.

    ``extra_feature_seeds`` ({cluster_id: {feature_code, ...}}) forces optional
    features ON node-wide (e.g. the web UI's single-endpoint claims); the
    conformance fixpoint then pulls in everything those features make mandatory.

    ``app_endpoints`` (list of device-type-name lists, one per application
    endpoint) places EP1..EPN; each endpoint may host several device types
    (composed device types). Defaults to a single EP1 = ``[profile.device_type]``.

    ``per_endpoint_feature_seeds`` ({endpoint_id: {cluster_id: {feature_code}}})
    forces optional features ON for ONE endpoint only, so a claim on EP1 does not
    leak to the same cluster on EP2.
    """
    transport_map = transport_map or load_transport_map()
    conditions = active_conditions(profile, transport_map)
    # Node-wide seeds: transport + any global extra (applies to every endpoint).
    node_seeds = transport_feature_seeds(profile, transport_map)
    for cid, codes in (extra_feature_seeds or {}).items():
        node_seeds.setdefault(cid, set()).update(codes)

    node_dts = [_resolve_device_type(model, n) for n in profile.node_device_types]
    root_dt = model.device_types.get(ROOT_NODE_DEVICE_TYPE_ID)

    if app_endpoints is None:
        app_endpoints = [[profile.device_type]]
    resolved_app = [[_resolve_device_type(model, n) for n in dts] for dts in app_endpoints]

    # EP0 = Root Node + any node-level device types (OTA Requestor, Aggregator, ...);
    # EP1..EPN = the application device types. Base device type merges into all.
    ep0_dts = ([root_dt] if root_dt is not None else []) + node_dts
    layout: list[tuple[int, list[DeviceType]]] = []
    if ep0_dts:
        layout.append((0, ep0_dts))
    for epid, dts in enumerate(resolved_app, start=1):
        layout.append((epid, dts))

    endpoints: list[EndpointPics] = []
    for epid, dts in layout:
        seeds = _endpoint_seeds(node_seeds, per_endpoint_feature_seeds, epid)
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


def _endpoint_seeds(node_seeds: dict[str, set[str]],
                    per_endpoint: dict[int, dict[str, set[str]]] | None,
                    epid: int) -> dict[str, set[str]]:
    """Node-wide seeds unioned with this endpoint's own claim seeds (no mutation)."""
    per = (per_endpoint or {}).get(epid)
    if not per:
        return node_seeds
    merged = {cid: set(codes) for cid, codes in node_seeds.items()}
    for cid, codes in per.items():
        merged.setdefault(cid, set()).update(codes)
    return merged


def all_enabled_cluster_ids(endpoints: list[EndpointPics]) -> set[str]:
    ids: set[str] = set()
    for ep in endpoints:
        ids |= ep.cluster_ids
    return ids


def controlled_conditions(transport_map: dict) -> frozenset[str]:
    """Condition names whose truth the profile inputs FULLY determine.

    Transport conditions are exhaustive (the transport input decides each one
    both ways) and the ICD flag decides SIT/LIT/Active. Any OTHER condition a
    device-type requirement references (LanguageLocale, Simple, ...) is a
    product fact the inputs cannot see.
    """
    known: set[str] = {"SIT", "LIT", "Active"}
    for entry in transport_map.get("transports", {}).values():
        known.update(entry.get("conditions", []))
    return frozenset(known)


def condition_refs(node) -> set[str]:
    """Every ConditionRef name mentioned anywhere in a conformance tree."""
    out: set[str] = set()
    if node is None or isinstance(node, (str, int, float, bool)):
        return out
    if type(node).__name__ == "ConditionRef":
        name = getattr(node, "name", None)
        if isinstance(name, str):
            out.add(name)
        return out
    for attr in ("condition", "items", "args", "arg", "payload", "left", "right"):
        value = getattr(node, attr, None)
        if isinstance(value, (list, tuple)):
            for child in value:
                out |= condition_refs(child)
        elif value is not None:
            out |= condition_refs(value)
    return out


def offered_cluster_sides(model: DataModel, device_types: list[DeviceType],
                          conditions: frozenset[str], controlled: frozenset[str],
                          enabled_server: set[str], enabled_client: set[str],
                          ) -> dict[tuple[str, str], str]:
    """Cluster sides the SPEC lists for these device types but the baseline
    did not enable: the endpoint's optional-cluster offerings.

    Returns {(cluster_id, side): kind} with side "S"/"C" and kind:

    * ``optional``     -- the requirement evaluates Optional right now: a plain
                          vendor choice ("O", "O if Wi-Fi" on a Wi-Fi device);
    * ``product_fact`` -- it evaluates Not-Applicable ONLY because a condition
                          no input controls (LanguageLocale, Simple&Client, ...)
                          is unknown; claiming the side answers that condition,
                          and absence of information is never a "No".

    A requirement blocked purely by CONTROLLED conditions (Thread diagnostics
    on a Wi-Fi-only device, ICD Management without the ICD flag) is a
    defendable input-decided No and is NOT offered. Disallowed/deprecated and
    provisional requirements are never offered.
    """
    from esp_matter_datamodel.model.conformance import Decision

    out: dict[tuple[str, str], str] = {}
    presence = ConformanceContext(active_conditions=conditions)
    for side, enabled in (("S", enabled_server), ("C", enabled_client)):
        merged = _merge_requirements(device_types, model.base_device_type,
                                     "server" if side == "S" else "client")
        for cid, req in merged.items():
            if cid in enabled or model.clusters.get(cid) is None:
                continue
            res = evaluate(req.conformance, presence)
            if res.decision == Decision.OPTIONAL:
                out[(cid, side)] = "optional"
                continue
            if res.decision != Decision.NOT_APPLICABLE:
                continue  # disallowed/deprecated/provisional: never offered
            unknown = condition_refs(req.conformance) - controlled
            if not unknown:
                continue  # blocked purely by input-decided conditions: a real No
            # Would it apply if the product facts held? Exact check: re-evaluate
            # with every uncontrolled condition assumed true.
            assumed = ConformanceContext(active_conditions=conditions | unknown)
            if evaluate(req.conformance, assumed).decision in (
                    Decision.MANDATORY, Decision.OPTIONAL):
                out[(cid, side)] = "product_fact"
    return out


@dataclass
class _BaselineRequirement:
    """Stand-in requirement for a USER-claimed cluster side.

    No device type mandates the side, so there are no per-device-type
    overrides; the cluster spec baseline applies and presence is forced.
    """

    id: str
    feature_overrides: dict = field(default_factory=dict)
    attribute_overrides: dict = field(default_factory=dict)
    command_overrides: dict = field(default_factory=dict)
    conformance: object = None  # never evaluated (force=True)


def claim_cluster_side(model: DataModel, cluster_id: str, side: str,
                       conditions: frozenset[str],
                       seed_feature_codes: set[str] | None = None) -> set[str]:
    """PICS codes the spec mandates once the USER claims a cluster side.

    Option-b of the gateway model: claiming ``X.C`` (or ``X.S``) is a fact, and
    the spec then dictates the side's mandatory elements -- pure derivation,
    no guessing. Returns the full enabled set for that side.
    """
    definition = model.clusters.get(cluster_id)
    if definition is None or not definition.pics:
        return set()
    req = _BaselineRequirement(cluster_id)
    if side == pics_codes.CLIENT:
        return _enable_client_cluster(req, definition, conditions, force=True)
    return _enable_cluster(req, definition, conditions,
                           set(seed_feature_codes or ()), force=True)


def _enable_cluster(
    req: ClusterRequirement,
    definition: Cluster | None,
    conditions: frozenset[str],
    seed_codes: set[str],
    force: bool = False,
) -> set[str]:
    # Cluster presence never depends on cluster element state -> empty ctx + conditions.
    # ``force`` = the user claimed the side; elements still follow conformance.
    presence_ctx = ConformanceContext(active_conditions=conditions)
    if not force and not evaluate(req.conformance, presence_ctx).is_mandatory():
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
    force: bool = False,
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
    if not force and not evaluate(req.conformance, presence_ctx).is_mandatory():
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
