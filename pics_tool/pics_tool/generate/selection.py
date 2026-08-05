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
"""The canonical selection document: the single source of truth for a product.

A ``Selection`` is a node profile plus a list of application endpoints (each with
one or more device types and its own optional-PICS ``claims``) plus node-level
``mcore_claims``. The web UI (humans) and the CLI (CI / LLMs) both drive the same
engines from this one document, so identical input yields identical PICS and
scaffold -- deterministically.

Example YAML::

    spec_version: "1.6"
    role: commissionee
    transport: [wifi_2g]
    mcore_claims: ["MCORE.DD.NFC"]
    endpoints:
      - device_types: ["Extended Color Light"]
        claims: ["OO.S.F01"]
      - device_types: ["On/Off Light", "Occupancy Sensor"]   # composed device types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .claims import feature_seeds_from_codes, mcore_atoms, side_claims
from .cluster_engine import (active_conditions, all_enabled_cluster_ids,
                             generate_cluster_pics, load_transport_map)
from .mcore_engine import compute_mcore_pics
from .profile import DeviceProfile, load_profile_data
from .template_io import known_item_numbers


class SelectionError(ValueError):
    """Raised for an invalid or unparseable selection document."""


@dataclass
class EndpointSpec:
    """One application endpoint: its device type(s) and its optional claims."""

    device_types: list[str]
    claims: list[str] = field(default_factory=list)


@dataclass
class Selection:
    profile: DeviceProfile                 # node-level facts (spec, role, transport, ...)
    endpoints: list[EndpointSpec]          # application endpoints, assigned EP1..EPN
    mcore_claims: list[str] = field(default_factory=list)

    @classmethod
    def from_profile(cls, profile: DeviceProfile) -> "Selection":
        """Single-endpoint selection from a plain profile (the CLI flag path)."""
        return cls(profile=profile, endpoints=[EndpointSpec([profile.device_type])])

    @classmethod
    def from_dict(cls, data: dict) -> "Selection":
        data = dict(data)
        data.pop("schema_version", None)
        # ``claims_by_tab`` is the web UI's per-endpoint claim transport, read
        # separately by webapp; it is not a node-profile field.
        data.pop("claims_by_tab", None)
        raw_endpoints = data.pop("endpoints", None)
        mcore_claims = list(data.pop("mcore_claims", []) or [])

        if raw_endpoints is not None:
            if not isinstance(raw_endpoints, list) or not raw_endpoints:
                raise SelectionError("'endpoints' must be a non-empty list")
            endpoints = [_parse_endpoint(e) for e in raw_endpoints]
        elif data.get("device_type"):
            # Back-compat shorthand: a single application endpoint on EP1.
            endpoints = [EndpointSpec([data["device_type"]])]
        else:
            raise SelectionError("selection needs either 'endpoints' or 'device_type'")

        # The node profile requires a device_type; use EP1's primary as the
        # representative. mcore/cluster node facts come from the union of all
        # endpoints' clusters, so this choice does not narrow them.
        profile_data = {k: v for k, v in data.items()}
        profile_data["device_type"] = endpoints[0].device_types[0]
        try:
            profile = DeviceProfile.from_dict(profile_data)
        except ValueError as e:
            raise SelectionError(str(e)) from e
        return cls(profile=profile, endpoints=endpoints, mcore_claims=mcore_claims)


def _parse_endpoint(entry) -> EndpointSpec:
    if isinstance(entry, str):
        return EndpointSpec([entry])
    if isinstance(entry, dict):
        dts = entry.get("device_types")
        if dts is None and entry.get("device_type"):
            dts = [entry["device_type"]]
        if isinstance(dts, str):
            dts = [dts]
        if not dts:
            raise SelectionError(f"endpoint entry needs 'device_types': {entry!r}")
        return EndpointSpec(list(dts), list(entry.get("claims", []) or []))
    raise SelectionError(f"invalid endpoint entry: {entry!r}")


def load_selection(path: str | Path) -> Selection:
    """Load a selection document (``.yaml``/``.yml``/``.json``)."""
    return Selection.from_dict(load_profile_data(path))


def build_endpoints_enabled(model, selection: Selection,
                            transport_map: dict | None = None) -> dict[int, set[str]]:
    """Run the engines for a selection -> {endpoint: enabled PICS codes}.

    The single seam both the CLI PICS export and the scaffold build on: multi
    endpoint layout, per-endpoint feature/side claims, and MCORE claims all
    resolved here through the shared engines.
    """
    profile = selection.profile
    version = profile.spec_version
    known = known_item_numbers(version)
    transport_map = transport_map or load_transport_map()
    conditions = active_conditions(profile, transport_map)

    app_endpoints = [ep.device_types for ep in selection.endpoints]
    per_ep_seeds: dict[int, dict[str, set[str]]] = {}
    per_ep_side: dict[int, set[str]] = {}
    for epid, ep in enumerate(selection.endpoints, start=1):
        if not ep.claims:
            continue
        per_ep_seeds[epid] = feature_seeds_from_codes(model, ep.claims)
        sides = side_claims(model, profile, ep.claims, conditions, known)
        if sides:
            per_ep_side[epid] = set().union(*sides.values())

    endpoints = generate_cluster_pics(
        model, profile, transport_map=transport_map,
        app_endpoints=app_endpoints, per_endpoint_feature_seeds=per_ep_seeds)

    cluster_ids = all_enabled_cluster_ids(endpoints)
    mcore = compute_mcore_pics(profile, version, cluster_ids,
                               extra_seeds=mcore_atoms(selection.mcore_claims))

    enabled = {ep.endpoint: set(ep.pics) & known for ep in endpoints}
    for epid, side in per_ep_side.items():
        enabled.setdefault(epid, set()).update(side)     # already intersected with known
    enabled.setdefault(0, set()).update(mcore)           # MCORE lives on endpoint 0
    return enabled
