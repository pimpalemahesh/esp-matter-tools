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
"""esp-matter output target.

Renders a neutral ``DataModelPlan`` into the esp-matter ``node::create`` /
``endpoint::<device_type>::create`` construction code. Optional features /
attributes / commands / events become explicit ``feature::add`` /
``attribute::create_x`` / ... calls; cluster sides become ``cluster::<ns>::create``
with the right ``CLUSTER_FLAG_*``.

P1: no Knowledge source yet, so argument values are ``/* ... */`` placeholders
(compile-or-flag, never silently wrong). P2 swaps in the signature index.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...ir import DataModelPlan, EndpointPlan
from ..base import CodeTarget, GeneratedFile, GeneratedOutput
from .knowledge import load_nearest
from .naming import chip_cluster_name, esp_name
from .synth import build_call


# --- esp-matter render model (also the back-compat ScaffoldResult shape) --------

@dataclass
class DeviceTypeInfo:
    name: str          # canonical spec name, e.g. "Extended Color Light"
    namespace: str     # esp-matter C++ namespace, e.g. "extended_color_light"
    id: str = ""       # canonical 0xXXXX id (unused by rendering)


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
    """An optional attribute / command / event (added via create_<name>)."""
    cluster_name: str
    cluster_namespace: str
    cluster_chip: str
    name: str          # element display name, e.g. "OnTransitionTime"
    namespace: str     # esp snake_case, e.g. "on_transition_time"


@dataclass
class OptionalSide:
    """A cluster added by SIDE (X.S / X.C) beyond the device-type baseline.

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
    """Back-compat result of the legacy ``generate_scaffold`` entry point."""
    snippet: str
    file: str | None = None
    endpoints: list[EndpointScaffold] = field(default_factory=list)
    exact: bool = False              # real signatures (knowledge used) vs placeholders
    knowledge_source: str = "none (placeholders)"

    @property
    def device_type_name(self) -> str:
        return self.endpoints[0].primary.name if self.endpoints else ""

    @property
    def device_namespace(self) -> str:
        return self.endpoints[0].primary.namespace if self.endpoints else ""


def _cluster_groups(ep: EndpointScaffold):
    """Group an endpoint's optional elements by cluster (order preserved), so each
    cluster is fetched once and all its features/attributes/commands/events added
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


class EspMatterTarget(CodeTarget):
    name = "esp_matter"
    default_filename = "app_data_model.cpp"

    def default_knowledge(self, version):
        # Committed signature index for this version, else the nearest lower
        # shipped version's (labeled); None only if no caps ship at all.
        return load_nearest(version)

    # ---- IR -> esp-matter render model ----
    def build_endpoints(self, plan: DataModelPlan) -> list[EndpointScaffold]:
        out: list[EndpointScaffold] = []
        for ep in plan.endpoints:
            dts = [DeviceTypeInfo(name=nm, namespace=esp_name(nm)) for nm in ep.device_types]

            def elem(r):
                return OptionalElem(r.cluster_name, esp_name(r.cluster_name),
                                    chip_cluster_name(r.cluster_name), r.name, esp_name(r.name))

            feats = [OptionalFeature(
                cluster_name=r.cluster_name, cluster_namespace=esp_name(r.cluster_name),
                cluster_id=r.cluster_id, cluster_chip=chip_cluster_name(r.cluster_name),
                feature_name=r.name, feature_namespace=esp_name(r.name)) for r in ep.features]
            sides = [OptionalSide(cluster_name=s.cluster_name,
                                  cluster_namespace=esp_name(s.cluster_name),
                                  server=s.server, client=s.client) for s in ep.sides]
            out.append(EndpointScaffold(
                endpoint=ep.index, primary=dts[0], composed=dts[1:],
                optional_features=feats,
                optional_attributes=[elem(r) for r in ep.attributes],
                optional_commands=[elem(r) for r in ep.commands],
                optional_events=[elem(r) for r in ep.events],
                optional_sides=sides, unknown_sides=list(ep.unknown_sides)))
        return out

    # ---- emit one feature/attribute/command/event call ----
    def _emit_call(self, symbol, receiver, var_base, n, knowledge, placeholder):
        """Signature-driven call when knowledge has ``symbol``; else the placeholder.

        ``placeholder`` is the fill-in arg (e.g. "/* config */") emitted when the
        signature is unknown -- ``None`` means the call takes no extra args. This
        is a required *argument*, not a comment; the generated code carries no
        explanatory comments.
        """
        sig = knowledge.symbol(symbol) if knowledge is not None else None
        if sig is None:
            if placeholder is None:
                return [f"    {symbol}({receiver});"]
            return [f"    {symbol}({receiver}, {placeholder});"]
        decls, args = build_call(sig, symbol, var_base, n)
        lines = [f"    {d}" for d in decls]
        lines.append(f"    {symbol}({receiver}" + "".join(f", {a}" for a in args) + ");")
        return lines

    # ---- render the esp-matter snippet (real signatures when knowledge is given) ----
    def render_snippet(self, endpoints: list[EndpointScaffold], knowledge=None) -> str:
        L: list[str] = [
            "    node::config_t node_config;",
            "    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);",
            '    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));',
            "",
        ]
        for ep in endpoints:
            ns, n = ep.primary.namespace, ep.endpoint
            L.append(f"    {ns}::config_t {ns}_config_{n};")
            L.append(f"    endpoint_t *endpoint_{n} = {ns}::create(node, &{ns}_config_{n}, ENDPOINT_FLAG_NONE, nullptr);")
            L.append(f'    ABORT_APP_ON_FAILURE(endpoint_{n} != nullptr, ESP_LOGE(TAG, "Failed to create {ep.primary.name} endpoint"));')
            for c in ep.composed:
                L.append(f"    {c.namespace}::config_t {c.namespace}_config_{n};")
                L.append(f'    ABORT_APP_ON_FAILURE({c.namespace}::add(endpoint_{n}, &{c.namespace}_config_{n}) == ESP_OK, ESP_LOGE(TAG, "Failed to add {c.name} device type"));')
            for cns, g in _cluster_groups(ep):
                L.append("")
                recv = f"{cns}_cluster_{n}"
                L.append(f"    cluster_t *{recv} = cluster::get(endpoint_{n}, {g['chip']}::Id);")
                for f in g["features"]:
                    L += self._emit_call(f"cluster::{cns}::feature::{f.feature_namespace}::add",
                                         recv, f"{cns}_{f.feature_namespace}", n, knowledge,
                                         placeholder="/* config */")
                for a in g["attributes"]:
                    L += self._emit_call(f"cluster::{cns}::attribute::create_{a.namespace}",
                                         recv, f"{cns}_{a.namespace}", n, knowledge,
                                         placeholder="/* value */")
                for c in g["commands"]:
                    L += self._emit_call(f"cluster::{cns}::command::create_{c.namespace}",
                                         recv, f"{cns}_{c.namespace}", n, knowledge,
                                         placeholder=None)
                for e in g["events"]:
                    L += self._emit_call(f"cluster::{cns}::event::create_{e.namespace}",
                                         recv, f"{cns}_{e.namespace}", n, knowledge,
                                         placeholder=None)
            for s in ep.optional_sides:
                L.append("")
                L.append(f"    cluster::{s.cluster_namespace}::config_t {s.cluster_namespace}_config_{n};")
                L.append(f"    cluster::{s.cluster_namespace}::create(endpoint_{n}, &{s.cluster_namespace}_config_{n}, {s.flags});")
            # unknown_sides (clusters not in the data model) can't be generated and
            # carry no comment; they remain in the recap for the UI/CLI note only.
            L.append("")
        while L and L[-1] == "":       # no trailing blank line(s)
            L.pop()
        return "\n".join(L) + "\n"

    def _recap(self, endpoints: list[EndpointScaffold]) -> list[dict]:
        items: list[dict] = []
        for ep in endpoints:
            def add(cluster, name, kind):
                items.append({"endpoint": ep.endpoint, "cluster": cluster, "name": name, "kind": kind})
            for f in ep.optional_features:
                add(f.cluster_name, f.feature_name, "feature")
            for a in ep.optional_attributes:
                add(a.cluster_name, a.name, "attribute")
            for c in ep.optional_commands:
                add(c.cluster_name, c.name, "command")
            for e in ep.optional_events:
                add(e.cluster_name, e.name, "event")
            for s in ep.optional_sides:
                add(s.cluster_name, s.side_text, "cluster")
        return items

    # ---- public target API ----
    def render(self, plan: DataModelPlan, knowledge=None) -> GeneratedOutput:
        endpoints = self.build_endpoints(plan)
        snippet = self.render_snippet(endpoints, knowledge)
        src = getattr(knowledge, "source_label", None) or "none (placeholders)"
        return GeneratedOutput(
            target=self.name, version=plan.spec_version, primary=snippet,
            files=[GeneratedFile(self.default_filename, snippet)],
            elements=self._recap(endpoints),
            exact=knowledge is not None, knowledge_source=src)
