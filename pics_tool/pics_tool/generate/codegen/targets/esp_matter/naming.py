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
"""esp-matter C++ naming convention.

The target emits C++ that must match the namespaces esp-matter's own code
generator produces: cluster/device namespaces (``extended_color_light``,
``on_off``) AND feature namespaces (``off_only``, ``color_temperature``, ``xy``).
Feature names are camelCase with no spaces, so a plain "replace non-alnum" is not
enough -- the transform must also split camelCase. This mirrors
``convert_to_snake_case`` in
``esp-matter/tools/data_model_gen/utils/helper.py``; keep it in sync.
"""

from __future__ import annotations

import re


def _normalize(name: str) -> str:
    # A single CamelWord ("OffOnly") is kept as-is for the camelCase splitter
    # below; anything with spaces/punctuation is collapsed to CamelCase first.
    if re.match(r"^[A-Z][a-zA-Z0-9]+$", name):
        return name
    words = [w.capitalize() for w in re.sub(r"[^a-zA-Z0-9]", " ", name).split()]
    return "".join(words).replace("DishWasher", "Dishwasher")


# Spec names whose esp-matter namespace does not follow the generic transform
# ("Wi-Fi" would split to wi_fi; the component uses wifi_network_diagnostics).
_NS_OVERRIDES = {
    "Wi-Fi Network Diagnostics": "wifi_network_diagnostics",
}


def to_namespace(name: str) -> str:
    """esp-matter snake_case namespace for a spec name.

    ``"On/Off" -> "on_off"``, ``"Extended Color Light" -> "extended_color_light"``,
    ``"OffOnly" -> "off_only"``, ``"ColorTemperature" -> "color_temperature"``.
    """
    if not name:
        return name
    if name in _NS_OVERRIDES:
        return _NS_OVERRIDES[name]
    name = _normalize(name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[\/_|\{\}\(\)\\-]", "_", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-zA-Z])([0-9])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


# Back-compat alias: the transform used to be the simpler "esp_name".
esp_name = to_namespace


# The chip (connectedhomeip) ``Clusters`` namespace title-cases every word,
# INCLUDING acronyms: "OTA ..."->"Ota...", "ICD ..."->"Icd...", "RVC ..."->"Rvc",
# "... AV ..."->"...Av...", "TLS ..."->"Tls...". A handful of names are genuinely
# irregular (acronym kept upper, or a different word order) and can't be derived;
# those are listed explicitly.
_CHIP_CLUSTER_OVERRIDES = {
    "Valid Proxies": "ProxyValid",
    "WebRTC Transport Provider": "WebRTCTransportProvider",
    "WebRTC Transport Requestor": "WebRTCTransportRequestor",
}


def chip_cluster_name(spec_name: str) -> str:
    """chip ``Clusters`` C++ identifier for a spec cluster name, for ``<name>::Id``.

    ``"Color Control" -> "ColorControl"``, ``"On/Off" -> "OnOff"``,
    ``"OTA Software Update Requestor" -> "OtaSoftwareUpdateRequestor"``. Used to
    emit ``cluster::get(endpoint, ColorControl::Id)`` -- the form esp-matter
    examples use (with ``using namespace chip::app::Clusters;``).
    """
    if spec_name in _CHIP_CLUSTER_OVERRIDES:
        return _CHIP_CLUSTER_OVERRIDES[spec_name]
    return "".join(t.capitalize() for t in re.split(r"[^A-Za-z0-9]+", spec_name) if t)


# esp-matter names a handful of feature/attribute/command namespaces
# irregularly -- differently enough that neither the generic snake_case
# transform nor an underscore-insensitive match (see resolve_element_ns) can
# reach them. Keyed by ``(cluster_namespace, kind, derived_namespace)``. Only
# used when the derived name is NOT exposed by the component AND the alias is,
# so a version that later adopts the derived spelling still resolves exactly.
#   - "auto" is a C++ keyword -> the component prefixes the cluster short name.
#   - air-quality levels use the feature CODE (MOD/VPOOR/XPOOR), not the name.
#   - "packet_counts" was "packets_counts" in the 1.4 / 1.4.2 components.
_ELEMENT_NS_ALIASES = {
    ("fan_control", "feature", "auto"): "fan_auto",
    ("air_quality", "feature", "moderate"): "mod",
    ("air_quality", "feature", "very_poor"): "vpoor",
    ("air_quality", "feature", "extremely_poor"): "xpoor",
    ("ethernet_network_diagnostics", "feature", "packet_counts"): "packets_counts",
    ("thread_network_diagnostics", "feature", "packet_counts"): "packets_counts",
}


# esp-matter cluster namespaces that diverge from the generic transform and
# can't be reached by an underscore-insensitive match. Keyed by the
# spec-derived namespace. Only ``switch`` today: it is a C++ keyword, so the
# component suffixes ``_cluster``. (Spelling divergences like Wi-Fi Network
# Management -> wifi_network_management are handled by the flat match below, so
# they need no entry here.)
_CLUSTER_NS_ALIASES = {
    "switch": "switch_cluster",
}


def resolve_cluster_ns(derived: str, available: set) -> str:
    """The cluster namespace the component ACTUALLY exposes for a spec cluster.

    Same reconciliation as :func:`resolve_element_ns`, one level up: exact,
    then underscore-insensitive (``wi_fi_network_management`` ->
    ``wifi_network_management``), then an explicit alias for a genuinely
    irregular name (``switch`` -> ``switch_cluster``). Returns ``derived``
    unchanged when the component has no such cluster -- the emitted call then
    stays a comment rather than a wrong namespace.
    """
    if not available or derived in available:
        return derived
    flat = derived.replace("_", "")
    for cand in available:
        if cand.replace("_", "") == flat:
            return cand
    alias = _CLUSTER_NS_ALIASES.get(derived)
    if alias and alias in available:
        return alias
    return derived


def resolve_element_ns(cns: str, kind: str, derived: str, available: set) -> str:
    """The namespace the component ACTUALLY exposes for this element.

    ``available`` is the set of namespaces the component provides for this
    cluster + kind (features / attributes / commands / events). We reconcile
    the spec-derived namespace against it so the emitted call matches a real
    esp-matter API rather than a plausible-but-wrong guess:

    1. exact match (the common case);
    2. underscore-insensitive match -- catches acronym/word-split spelling
       differences (``so_c_reporting`` vs ``soc_reporting``, ``wi_fi`` vs
       ``wifi``, ``week_day`` vs ``weekday``, ``time_snapshot`` vs
       ``time_snap_shot``), which are safe because the letters are identical;
    3. an explicit alias for the few genuinely irregular names.

    Returns the resolved namespace, or ``derived`` unchanged when nothing in
    the component matches (the caller then keeps it as an "add it manually"
    comment -- an element with no create/add API is never forced to a wrong one).
    """
    if derived in available:
        return derived
    flat = derived.replace("_", "")
    for cand in available:
        if cand.replace("_", "") == flat:
            return cand
    alias = _ELEMENT_NS_ALIASES.get((cns, kind, derived))
    if alias and alias in available:
        return alias
    return derived
