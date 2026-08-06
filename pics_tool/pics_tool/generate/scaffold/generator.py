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
"""Render the esp-matter data-model construction snippet from a Selection.

Emits ``node::create`` (Root Node on EP0) plus, for each application endpoint,
``endpoint::<device_type>::create`` -- with default config -- and, for composed
endpoints, ``endpoint::<type>::add`` for the extra device types. Optional PICS
claims (features / sides) are surfaced as precise ``// TODO`` guidance: whether a
given ``feature::add`` takes a config is esp-matter-specific and not derivable
from the data model, so we name the exact call rather than emit maybe-wrong code.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from esp_matter_datamodel.model.elements import DataModel

from ..claims import FEATURE_CODE_RE, GATEWAY_RE, pics_to_cluster
from .naming import chip_cluster_name, esp_name

logger = logging.getLogger(__name__)

ROOT_NODE = "Root Node"

# Server-side optional attribute / command PICS codes, e.g. "LVL.S.A0012",
# "LVL.S.C00.Rsp". (Features are FEATURE_CODE_RE; cluster sides are GATEWAY_RE.)
ATTR_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.A(?P<id>[0-9A-Fa-f]{4})$")
CMD_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.C(?P<id>[0-9A-Fa-f]{2})(?:\.(?:Rsp|Tx))?$")
EVENT_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.E(?P<id>[0-9A-Fa-f]{2})$")


@dataclass
class DeviceTypeInfo:
    name: str          # canonical spec name, e.g. "Extended Color Light"
    namespace: str     # esp-matter C++ namespace, e.g. "extended_color_light"
    id: str            # canonical 0xXXXX id
    baseline_cluster_ids: set[str] = field(default_factory=set)


@dataclass
class OptionalFeature:
    cluster_name: str
    cluster_namespace: str
    cluster_id: str
    cluster_chip: str          # chip Clusters identifier, e.g. "ColorControl" (for ::Id)
    feature_name: str
    feature_namespace: str


@dataclass
class OptionalElem:
    """An optional attribute or command the user claimed (added via create_<name>)."""
    cluster_name: str
    cluster_namespace: str
    cluster_chip: str
    name: str          # element display name, e.g. "OnTransitionTime"
    namespace: str     # esp snake_case, e.g. "on_transition_time"


@dataclass
class OptionalSide:
    """A cluster the user added by SIDE (X.S / X.C) beyond the device-type baseline.

    ``endpoint::<type>::create()`` builds the device type's *server* clusters, so a
    claimed *client* side -- or a *server* cluster the device type doesn't mandate
    -- needs an explicit ``cluster::<ns>::create(endpoint, &config, flags)``.
    """
    cluster_name: str
    cluster_namespace: str
    server: bool = False    # needs CLUSTER_FLAG_SERVER
    client: bool = False    # needs CLUSTER_FLAG_CLIENT

    @property
    def flags(self) -> str:
        parts = (["CLUSTER_FLAG_SERVER"] if self.server else []) + \
                (["CLUSTER_FLAG_CLIENT"] if self.client else [])
        return " | ".join(parts)

    @property
    def side_text(self) -> str:
        parts = (["server"] if self.server else []) + (["client"] if self.client else [])
        return " + ".join(parts) + " cluster" + ("s" if len(parts) > 1 else "")


@dataclass
class EndpointScaffold:
    endpoint: int
    primary: DeviceTypeInfo
    composed: list[DeviceTypeInfo] = field(default_factory=list)
    optional_features: list[OptionalFeature] = field(default_factory=list)
    optional_attributes: list[OptionalElem] = field(default_factory=list)
    optional_commands: list[OptionalElem] = field(default_factory=list)
    optional_events: list[OptionalElem] = field(default_factory=list)
    optional_sides: list[OptionalSide] = field(default_factory=list)
    unknown_sides: list[str] = field(default_factory=list)   # X.S/X.C for clusters not in the model

    @property
    def device_types(self) -> list[str]:
        return [self.primary.name] + [c.name for c in self.composed]


@dataclass
class ScaffoldResult:
    """The construction snippet plus a structured description of what it builds."""

    snippet: str
    file: str | None = None
    endpoints: list[EndpointScaffold] = field(default_factory=list)

    @property
    def device_type_name(self) -> str:
        return self.endpoints[0].primary.name if self.endpoints else ""

    @property
    def device_namespace(self) -> str:
        return self.endpoints[0].primary.namespace if self.endpoints else ""


def _resolve_device_type(model: DataModel, name: str) -> DeviceTypeInfo:
    dt = model.device_type_by_name(name)
    if dt is None:
        raise ValueError(
            f"device type {name!r} not found in the {model.spec_version} data model")
    # esp-matter's endpoint::<type>::create() builds the device type's own server
    # clusters PLUS the Base Device Type's (Descriptor, Binding, ...).
    baseline = set(dt.server_clusters.keys())
    if model.base_device_type is not None:
        baseline |= set(model.base_device_type.server_clusters.keys())
    return DeviceTypeInfo(dt.name, esp_name(dt.name), dt.id, baseline)


def _optionals(model: DataModel, claims, baseline_cluster_ids: set[str]):
    """Split an endpoint's claims into optional features, attributes, commands, sides.

    Features/attributes/commands the user switched ON beyond the device-type
    baseline become explicit ``feature::add`` / ``attribute::create_x`` /
    ``command::create_x`` calls; cluster-side (``X.S``/``X.C``) claims become notes.
    """
    clusters_by_pics = pics_to_cluster(model)
    features: list[OptionalFeature] = []
    attributes: list[OptionalElem] = []
    commands: list[OptionalElem] = []
    events: list[OptionalElem] = []
    sides: dict[str, OptionalSide] = {}     # cid -> OptionalSide (server/client flags OR'd)
    unknown_sides: list[str] = []

    def _elem(cluster, name):
        return OptionalElem(cluster.name, esp_name(cluster.name),
                            chip_cluster_name(cluster.name), name, esp_name(name))

    for code in claims or []:
        fm = FEATURE_CODE_RE.match(code)
        if fm:
            cid = clusters_by_pics.get(fm.group("pics"))
            if cid is None:
                continue
            cluster = model.clusters[cid]
            feat = cluster.features.get(int(fm.group("bit"), 16))
            if feat is not None:
                features.append(OptionalFeature(
                    cluster_name=cluster.name, cluster_namespace=esp_name(cluster.name),
                    cluster_id=cid, cluster_chip=chip_cluster_name(cluster.name),
                    feature_name=feat.name, feature_namespace=esp_name(feat.name)))
            continue
        am = ATTR_CODE_RE.match(code)
        if am:
            cid = clusters_by_pics.get(am.group("pics"))
            if cid is None:
                continue
            cluster = model.clusters[cid]
            attr = cluster.attributes.get("0x" + am.group("id").lower())
            if attr is not None:
                attributes.append(_elem(cluster, attr.name))
            continue
        cm = CMD_CODE_RE.match(code)
        if cm:
            cid = clusters_by_pics.get(cm.group("pics"))
            if cid is None:
                continue
            cluster = model.clusters[cid]
            key = "0x" + cm.group("id").lower()
            cmd = cluster.accepted_commands.get(key) or cluster.generated_commands.get(key)
            if cmd is not None:
                commands.append(_elem(cluster, cmd.name))
            continue
        em = EVENT_CODE_RE.match(code)
        if em:
            cid = clusters_by_pics.get(em.group("pics"))
            if cid is None:
                continue
            cluster = model.clusters[cid]
            event = cluster.events.get("0x" + em.group("id").lower())
            if event is not None:
                events.append(_elem(cluster, event.name))
            continue
        gm = GATEWAY_RE.match(code)
        if gm:
            cid = clusters_by_pics.get(gm.group("pics"))
            is_server = gm.group("side") == "S"
            if cid is None:
                unknown_sides.append(f"{gm.group('pics')} "
                                     f"({'server' if is_server else 'client'} side, {code})")
                continue
            # A server cluster the device type already builds needs nothing extra.
            if is_server and cid in baseline_cluster_ids:
                continue
            cluster = model.clusters[cid]
            side = sides.setdefault(cid, OptionalSide(cluster.name, esp_name(cluster.name)))
            if is_server:
                side.server = True
            else:
                side.client = True
    return features, attributes, commands, events, list(sides.values()), unknown_sides


def _cluster_groups(ep: "EndpointScaffold"):
    """Group an endpoint's optional elements by cluster (order preserved), so each
    cluster is fetched once and all its features/attributes/commands added
    together -- the door_lock example pattern."""
    order: list[str] = []
    groups: dict[str, dict] = {}

    def bucket(elem, kind):
        ns = elem.cluster_namespace
        if ns not in groups:
            groups[ns] = {"chip": elem.cluster_chip, "name": elem.cluster_name,
                          "features": [], "attributes": [], "commands": [], "events": []}
            order.append(ns)
        groups[ns][kind].append(elem)

    for f in ep.optional_features:
        bucket(f, "features")
    for a in ep.optional_attributes:
        bucket(a, "attributes")
    for c in ep.optional_commands:
        bucket(c, "commands")
    for e in ep.optional_events:
        bucket(e, "events")
    return [(ns, groups[ns]) for ns in order]


def _render(endpoints: list[EndpointScaffold]) -> str:
    """Render the construction snippet as plain text.

    Kept dependency-free on purpose (no Jinja2): the tool runs in the browser via
    Pyodide, and this avoids loading a template engine + bundling a template file
    just to interpolate a handful of lines.
    """
    L: list[str] = [
        "    /* Create a Matter node with the Root Node device type on endpoint 0. */",
        "    node::config_t node_config;",
        "    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);",
        '    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));',
        "",
    ]
    for ep in endpoints:
        ns, n = ep.primary.namespace, ep.endpoint
        types = " + ".join(ep.device_types)
        L.append(f"    /* Endpoint {n}: {types} (default config; set attribute defaults as needed). */")
        L.append(f"    {ns}::config_t {ns}_config_{n};")
        L.append(f"    endpoint_t *endpoint_{n} = {ns}::create(node, &{ns}_config_{n}, ENDPOINT_FLAG_NONE, priv_data);")
        L.append(f'    ABORT_APP_ON_FAILURE(endpoint_{n} != nullptr, ESP_LOGE(TAG, "Failed to create {ep.primary.name} endpoint"));')
        for c in ep.composed:
            L.append(f"    {c.namespace}::config_t {c.namespace}_config_{n};")
            L.append(f'    ABORT_APP_ON_FAILURE({c.namespace}::add(endpoint_{n}, &{c.namespace}_config_{n}) == ESP_OK, ESP_LOGE(TAG, "Failed to add {c.name} device type"));')
        # Optional elements, grouped per cluster: fetch the cluster once
        # (ClusterName::Id, as esp-matter examples do), then add each feature /
        # optional attribute / optional command -- the door_lock example pattern.
        # Each group is separated by a blank line (no comment; the code is
        # self-explanatory). The config/value is a `/* ... */` placeholder ON
        # PURPOSE: pasted as-is it won't compile, so you can't ship a
        # half-configured element by accident -- fill in each config_t / value.
        for cns, g in _cluster_groups(ep):
            L.append("")
            L.append(f"    cluster_t *{cns}_cluster_{n} = cluster::get(endpoint_{n}, {g['chip']}::Id);")
            for f in g["features"]:
                L.append(f"    cluster::{cns}::feature::{f.feature_namespace}::add({cns}_cluster_{n}, /* config */);")
            for a in g["attributes"]:
                L.append(f"    cluster::{cns}::attribute::create_{a.namespace}({cns}_cluster_{n}, /* value */);")
            for c in g["commands"]:
                L.append(f"    cluster::{cns}::command::create_{c.namespace}({cns}_cluster_{n});")
            for e in g["events"]:
                L.append(f"    cluster::{cns}::event::create_{e.namespace}({cns}_cluster_{n});")
        # Cluster sides beyond the device-type baseline: a claimed client cluster
        # (or a non-mandated server cluster) is created explicitly with the right
        # CLUSTER_FLAG_*. Config left default (esp-matter style: &<ns>_config).
        for s in ep.optional_sides:
            L.append("")
            L.append(f"    cluster::{s.cluster_namespace}::config_t {s.cluster_namespace}_config_{n};")
            L.append(f"    cluster::{s.cluster_namespace}::create(endpoint_{n}, &{s.cluster_namespace}_config_{n}, {s.flags});")
        # Only the un-generatable case keeps a note (nothing to emit against).
        for u in ep.unknown_sides:
            L.append(f"    /* Optional {u} claimed in PICS -- cluster not in the data model;"
                     " add it manually. */")
        L.append("")
    while L and L[-1] == "":       # no trailing blank line(s)
        L.pop()
    return "\n".join(L) + "\n"


def generate_scaffold(selection, model: DataModel,
                      output_dir: str | Path | None = None) -> ScaffoldResult:
    """Build the data-model construction snippet for ``selection``.

    ``selection`` is a :class:`pics_tool.generate.selection.Selection`. If
    ``output_dir`` is given, the snippet is also written to
    ``<output_dir>/app_data_model.cpp``.
    """
    endpoints: list[EndpointScaffold] = []
    for epid, ep in enumerate(selection.endpoints, start=1):
        dts = [_resolve_device_type(model, name) for name in ep.device_types]
        baseline: set[str] = set()
        for dt in dts:
            baseline |= dt.baseline_cluster_ids
        features, attributes, commands, events, sides, unknown = _optionals(model, ep.claims, baseline)
        endpoints.append(EndpointScaffold(
            endpoint=epid, primary=dts[0], composed=dts[1:],
            optional_features=features, optional_attributes=attributes,
            optional_commands=commands, optional_events=events,
            optional_sides=sides, unknown_sides=unknown))

    snippet = _render(endpoints)

    written: str | None = None
    if output_dir is not None:
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        dst = out / "app_data_model.cpp"
        dst.write_text(snippet, encoding="utf-8")
        written = str(dst)

    return ScaffoldResult(snippet=snippet, file=written, endpoints=endpoints)
