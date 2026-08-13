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

from ...ir import DataModelPlan
from ..base import CodeTarget, GeneratedFile, GeneratedOutput
from .knowledge import load_nearest
from .naming import chip_cluster_name, esp_name
from .synth import build_call


# --- esp-matter render model (also the back-compat ScaffoldResult shape) --------


@dataclass
class DeviceTypeInfo:
    name: str  # canonical spec name, e.g. "Extended Color Light"
    namespace: str  # esp-matter C++ namespace, e.g. "extended_color_light"
    id: str = ""  # canonical 0xXXXX id (unused by rendering)


@dataclass
class OptionalFeature:
    cluster_name: str
    cluster_namespace: str
    cluster_id: str
    cluster_chip: str  # chip Clusters identifier, e.g. "ColorControl" (for ::Id)
    feature_name: str
    feature_namespace: str


@dataclass
class OptionalElem:
    """An optional attribute / command / event (added via create_<name>)."""

    cluster_name: str
    cluster_namespace: str
    cluster_chip: str
    name: str  # element display name, e.g. "OnTransitionTime"
    namespace: str  # esp snake_case, e.g. "on_transition_time"


@dataclass
class OptionalSide:
    """A cluster added by SIDE (X.S / X.C) beyond the device-type baseline.

    ``endpoint::<type>::create()`` builds the device type's *server* clusters, so a
    claimed *client* side -- or a *server* cluster the device type doesn't mandate
    -- needs an explicit ``cluster::<ns>::create(endpoint, &config, flags)``.
    """

    cluster_name: str
    cluster_namespace: str
    server: bool = False  # needs CLUSTER_FLAG_SERVER
    client: bool = False  # needs CLUSTER_FLAG_CLIENT

    @property
    def flags(self) -> str:
        parts = (["CLUSTER_FLAG_SERVER"] if self.server else []) + (
            ["CLUSTER_FLAG_CLIENT"] if self.client else []
        )
        return " | ".join(parts)

    @property
    def side_text(self) -> str:
        parts = (["server"] if self.server else []) + (
            ["client"] if self.client else []
        )
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
    unknown_sides: list[str] = field(
        default_factory=list
    )  # X.S/X.C for clusters not in the model

    @property
    def device_types(self) -> list[str]:
        return [self.primary.name] + [c.name for c in self.composed]


@dataclass
class ScaffoldResult:
    """Back-compat result of the legacy ``generate_scaffold`` entry point."""

    snippet: str
    file: str | None = None
    endpoints: list[EndpointScaffold] = field(default_factory=list)
    exact: bool = False  # a knowledge source was consulted
    knowledge_source: str = "none"
    # selected elements with no matching esp_matter function in the knowledge used;
    # omitted from the code (kept compile-ready) and reported for manual handling.
    unresolved: list[dict] = field(default_factory=list)

    @property
    def device_type_name(self) -> str:
        return self.endpoints[0].primary.name if self.endpoints else ""

    @property
    def device_namespace(self) -> str:
        return self.endpoints[0].primary.namespace if self.endpoints else ""


# What esp-matter's node::create already builds on the ROOT endpoint (0), from
# root_node::add in the component (data_model/legacy/esp_matter_endpoint.cpp).
# This is TARGET knowledge: the spec engines never assume esp-matter behavior.
_ROOT_DEFAULT_NS = {
    "descriptor",
    "access_control",
    "basic_information",
    "general_commissioning",
    "network_commissioning",
    "general_diagnostics",
    "administrator_commissioning",
    "operational_credentials",
    "group_key_management",
}
# Root clusters node::create builds only under an sdkconfig option -- the app
# code must not create them again; the option is the switch.
_ROOT_KCONFIG_NS = {
    "wifi_network_diagnostics": "CONFIG_SUPPORT_WIFI_NETWORK_DIAGNOSTICS_CLUSTER (default y)",
    "thread_network_diagnostics": "CONFIG_SUPPORT_THREAD_NETWORK_DIAGNOSTICS_CLUSTER (default y)",
    "icd_management": "CONFIG_ENABLE_ICD_SERVER",
}


def root_side_disposition(ns: str) -> str | None:
    """'default' / 'kconfig' when node::create covers this root cluster, else None."""
    if ns in _ROOT_DEFAULT_NS:
        return "default"
    if ns in _ROOT_KCONFIG_NS:
        return "kconfig"
    return None


def _cluster_groups(ep: EndpointScaffold):
    """Group an endpoint's optional elements by cluster (order preserved), so each
    cluster is fetched once and all its features/attributes/commands/events added
    together -- the door_lock example pattern."""
    order: list[str] = []
    groups: dict[str, dict] = {}

    def bucket(elem, kind):
        ns = elem.cluster_namespace
        if ns not in groups:
            groups[ns] = {
                "chip": elem.cluster_chip,
                "name": elem.cluster_name,
                "features": [],
                "attributes": [],
                "commands": [],
                "events": [],
            }
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
            dts = [
                DeviceTypeInfo(name=nm, namespace=esp_name(nm))
                for nm in ep.device_types
            ]

            def elem(r):
                return OptionalElem(
                    r.cluster_name,
                    esp_name(r.cluster_name),
                    chip_cluster_name(r.cluster_name),
                    r.name,
                    esp_name(r.name),
                )

            feats = [
                OptionalFeature(
                    cluster_name=r.cluster_name,
                    cluster_namespace=esp_name(r.cluster_name),
                    cluster_id=r.cluster_id,
                    cluster_chip=chip_cluster_name(r.cluster_name),
                    feature_name=r.name,
                    feature_namespace=esp_name(r.name),
                )
                for r in ep.features
            ]
            sides = [
                OptionalSide(
                    cluster_name=s.cluster_name,
                    cluster_namespace=esp_name(s.cluster_name),
                    server=s.server,
                    client=s.client,
                )
                for s in ep.sides
            ]
            out.append(
                EndpointScaffold(
                    endpoint=ep.index,
                    primary=dts[0],
                    composed=dts[1:],
                    optional_features=feats,
                    optional_attributes=[elem(r) for r in ep.attributes],
                    optional_commands=[elem(r) for r in ep.commands],
                    optional_events=[elem(r) for r in ep.events],
                    optional_sides=sides,
                    unknown_sides=list(ep.unknown_sides),
                )
            )
        return out

    # ---- the optional calls for one cluster group (only verified ones) ----
    @staticmethod
    def _group_items(cns, g):
        """(kind, symbol, var_base, display_name, cluster_name) per element, in
        render order: features, attributes, commands, events."""
        items = [
            (
                "feature",
                f"cluster::{cns}::feature::{f.feature_namespace}::add",
                f"{cns}_{f.feature_namespace}",
                f.feature_name,
                f.cluster_name,
            )
            for f in g["features"]
        ]
        for a in g["attributes"]:
            items.append(
                (
                    "attribute",
                    f"cluster::{cns}::attribute::create_{a.namespace}",
                    f"{cns}_{a.namespace}",
                    a.name,
                    a.cluster_name,
                )
            )
        for c in g["commands"]:
            items.append(
                (
                    "command",
                    f"cluster::{cns}::command::create_{c.namespace}",
                    f"{cns}_{c.namespace}",
                    c.name,
                    c.cluster_name,
                )
            )
        for e in g["events"]:
            items.append(
                (
                    "event",
                    f"cluster::{cns}::event::create_{e.namespace}",
                    f"{cns}_{e.namespace}",
                    e.name,
                    e.cluster_name,
                )
            )
        return items

    # ---- render the esp-matter snippet. Every selected element is verified against
    #      the knowledge (component): a known API becomes a real call; an unknown one
    #      is kept in place as a comment naming the API to look up -- never dropped.
    #      Returns (snippet, unresolved). ----
    def render_snippet(self, endpoints: list[EndpointScaffold], knowledge=None):
        unresolved: list[dict] = []
        ver = (
            getattr(knowledge, "component_version", "") if knowledge is not None else ""
        )
        where = (
            f"esp_matter {ver}"
            if ver and ver != "component"
            else "the esp_matter component"
        )
        L: list[str] = [
            "    node::config_t node_config;",
            "    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);",  # noqa: E501
            '    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));',  # noqa: E501
            "",
        ]
        for ep in endpoints:
            ns, n = ep.primary.namespace, ep.endpoint
            if n == 0:
                # The root endpoint is created by node::create above; fetch it
                # to add the optional Root Node clusters selected in the PICS.
                L.append(
                    "    endpoint_t *endpoint_0 = endpoint::get(node, 0); /* root endpoint, created by node::create */"  # noqa: E501
                )
                L.append(
                    '    ABORT_APP_ON_FAILURE(endpoint_0 != nullptr, ESP_LOGE(TAG, "Failed to get the root endpoint"));'  # noqa: E501
                )
            else:
                L.append(f"    {ns}::config_t {ns}_config_{n};")
                L.append(
                    f"    endpoint_t *endpoint_{n} = {ns}::create(node, &{ns}_config_{n}, ENDPOINT_FLAG_NONE, nullptr);"  # noqa: E501
                )
                L.append(
                    f'    ABORT_APP_ON_FAILURE(endpoint_{n} != nullptr, ESP_LOGE(TAG, "Failed to create {ep.primary.name} endpoint"));'  # noqa: E501
                )
                for c in ep.composed:
                    L.append(f"    {c.namespace}::config_t {c.namespace}_config_{n};")
                    L.append(
                        f'    ABORT_APP_ON_FAILURE({c.namespace}::add(endpoint_{n}, &{c.namespace}_config_{n}) == ESP_OK, ESP_LOGE(TAG, "Failed to add {c.name} device type"));'  # noqa: E501
                    )
            # Whole-cluster sides FIRST. create() already returns the
            # cluster_t*, so when this snippet ALSO adds elements to a cluster
            # it creates, the pointer is captured here and the element calls
            # below skip the redundant cluster::get (get remains only for
            # clusters built elsewhere: the device type's or node::create's).
            groups = _cluster_groups(ep)
            # namespaces with at least one RESOLVABLE element call: only those
            # need the pointer (capturing for comment-only groups would leave
            # an unused variable behind).
            group_ns = {
                cns
                for cns, g in groups
                if knowledge is not None
                and any(
                    knowledge.symbol(sym) for _, sym, *_ in self._group_items(cns, g)
                )
            }
            created: dict[str, str] = {}  # cluster namespace -> captured var
            for s in ep.optional_sides:
                cns = s.cluster_namespace
                disp = root_side_disposition(cns) if n == 0 else None
                if disp == "default":
                    L.append(
                        f"    // {s.cluster_name}: already created on the root endpoint by node::create"  # noqa: E501
                    )
                    continue
                if disp == "kconfig":
                    L.append(
                        f"    // {s.cluster_name}: created by node::create when "
                        f"{_ROOT_KCONFIG_NS[cns]} is enabled in sdkconfig"
                    )
                    continue
                L.append("")
                L.append(f"    cluster::{cns}::config_t {cns}_config_{n};")
                call = f"cluster::{cns}::create(endpoint_{n}, &{cns}_config_{n}, {s.flags});"
                if cns in group_ns:  # elements follow: keep the pointer
                    created[cns] = f"{cns}_cluster_{n}"
                    L.append(f"    cluster_t *{created[cns]} = {call}")
                else:
                    L.append(f"    {call}")
            for cns, g in groups:
                recv = created.get(cns, f"{cns}_cluster_{n}")
                calls: list[str] = []
                notes: list[str] = []
                for kind, symbol, var_base, name, cluster_name in self._group_items(
                    cns, g
                ):
                    sig = knowledge.symbol(symbol) if knowledge is not None else None
                    if sig is None:  # API not in this component -> comment, don't drop
                        unresolved.append(
                            {
                                "endpoint": n,
                                "cluster": cluster_name,
                                "name": name,
                                "kind": kind,
                            }
                        )
                        # Reference the full qualified call, same style as the real
                        # calls above, so the reader recognizes it in context.
                        notes.append(
                            f"    // {symbol}() not found in {where} -- add it manually"
                        )
                        continue
                    decls, args = build_call(sig, symbol, var_base, n)
                    calls += [f"    {d}" for d in decls]
                    calls.append(
                        f"    {symbol}({recv}" + "".join(f", {a}" for a in args) + ");"
                    )
                if calls or notes:
                    L.append("")
                    if calls:
                        # fetch only when this snippet did not create it above
                        if cns not in created:
                            L.append(
                                f"    cluster_t *{recv} = cluster::get(endpoint_{n}, {g['chip']}::Id);"  # noqa: E501
                            )
                        L += calls
                    L += notes
            for u in ep.unknown_sides:
                unresolved.append(
                    {"endpoint": n, "cluster": u, "name": u, "kind": "cluster"}
                )
                L.append("")
                L.append(f"    // {u} not in the data model -- add it manually")
            L.append("")
        while L and L[-1] == "":  # no trailing blank line(s)
            L.pop()
        return "\n".join(L) + "\n", unresolved

    def _recap(self, endpoints: list[EndpointScaffold]) -> list[dict]:
        items: list[dict] = []
        for ep in endpoints:

            def add(cluster, name, kind):
                items.append(
                    {
                        "endpoint": ep.endpoint,
                        "cluster": cluster,
                        "name": name,
                        "kind": kind,
                    }
                )

            for f in ep.optional_features:
                add(f.cluster_name, f.feature_name, "feature")
            for a in ep.optional_attributes:
                add(a.cluster_name, a.name, "attribute")
            for c in ep.optional_commands:
                add(c.cluster_name, c.name, "command")
            for e in ep.optional_events:
                add(e.cluster_name, e.name, "event")
            for s in ep.optional_sides:
                # root clusters node::create covers (default or sdkconfig) are
                # explained as comments in the code, not "added" by it
                if ep.endpoint == 0 and root_side_disposition(s.cluster_namespace):
                    continue
                add(s.cluster_name, s.side_text, "cluster")
        return items

    # ---- public target API ----
    def render(self, plan: DataModelPlan, knowledge=None) -> GeneratedOutput:
        endpoints = self.build_endpoints(plan)
        snippet, unresolved = self.render_snippet(endpoints, knowledge)
        src = getattr(knowledge, "source_label", None) or "none"
        notes = [
            f"{u['cluster']} / {u['name']} ({u['kind']}): no matching esp_matter "
            f"function in {src} -- add manually"
            for u in unresolved
        ]
        return GeneratedOutput(
            target=self.name,
            version=plan.spec_version,
            primary=snippet,
            files=[GeneratedFile(self.default_filename, snippet)],
            elements=self._recap(endpoints),
            notes=notes,
            exact=knowledge is not None,
            knowledge_source=src,
            unresolved=unresolved,
        )
