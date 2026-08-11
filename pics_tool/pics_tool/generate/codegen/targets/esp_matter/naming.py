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
