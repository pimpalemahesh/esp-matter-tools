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
"""MCORE (Base.xml) engine: profile -> enabled node-level PICS codes.

MCORE is not in the data model; Base.xml carries each code's status (M/O) and a
``cond`` expression over other PICS codes. We (1) seed atoms from the profile
(transport atoms come from ``transport_map.yaml``, role atoms from the per-role
profile YAML), then (2) run a monotone fixpoint that enables only items whose
cond makes them MANDATORY. Optional leaves are never blanket-enabled: they are
product facts the engineer confirms (the earlier "maximum options" policy, D14,
was dropped as over-claiming). Boolean cond evaluation reuses the shared,
PICS-neutral boolexpr with a PICS-code resolver (D21).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from fnmatch import fnmatch
from importlib.resources import files

import yaml
from esp_matter_datamodel import boolexpr

from .profile import DeviceProfile
from .template_io import PicsItem, base_template_path, parse_pics_items

logger = logging.getLogger(__name__)

# Onboarding methods a commissionee provides. An 11-digit manual pairing code
# implies the Standard Commissioning Flow; a 21-digit code (VID/PID embedded,
# spec 5.1.4) implies a NON-standard flow, so it seeds only MANUAL_PC -- which
# non-standard flow (user-intent / custom) stays a manual question.
# (DD.11_MANUAL_PC / DD.21_MANUAL_PC are *commissioner*-side items and are
# intentionally not seeded here.)
_ONBOARDING_SEEDS = {
    "qr": ["MCORE.DD.QR"],
    "manual_pairing_code": ["MCORE.DD.MANUAL_PC"],
    "manual_pairing_code_11": ["MCORE.DD.MANUAL_PC"],
    "manual_pairing_code_21": ["MCORE.DD.MANUAL_PC"],
    "nfc": ["MCORE.DD.NFC"],
}
# The commissioning FLOW is its own input (profile.commissioning_flow): the
# *_COMM_FLOW items follow it, and the manual code's 11/21-digit form follows
# the flow too (spec 5.1.4) -- onboarding materials only seed what they are.
_FLOW_SEEDS = {
    "standard": ["MCORE.DD.STANDARD_COMM_FLOW"],
    "user_intent": ["MCORE.DD.USER_INTENT_COMM_FLOW"],
    "custom": ["MCORE.DD.CUSTOM_COMM_FLOW"],
}

# Cluster ids that reveal node-level facts (OTA / bridge / diagnostic logs).
# These are DERIVED from whether the corresponding cluster is present in the
# generated set, not asked.
_CLUSTER_OTA_REQUESTOR = "0x002a"
_CLUSTER_OTA_PROVIDER = "0x0029"
_CLUSTER_BRIDGED_BASIC_INFO = "0x0039"  # on bridged child endpoints
_CLUSTER_COMMISSIONER_CONTROL = "0x0751"  # on an Aggregator (bridge) node
_CLUSTER_DIAGNOSTIC_LOGS = "0x0032"  # a Root Node optional-cluster offering


def load_role_profile(role: str) -> dict:
    resource = files("pics_tool").joinpath(f"profiles/{role}.yaml")
    if not resource.is_file():
        raise ValueError(f"no MCORE profile for role {role!r}")
    return yaml.safe_load(resource.read_text(encoding="utf-8"))


# BDX (bulk data exchange) is used only by OTA (and Diagnostic Logs). Its roles
# are therefore derived from the presence of the OTA clusters, not blanket-enabled:
# an OTA requestor is the BDX receiver (downloads the image), a provider the sender.
# Requestor sub-roles calibrated to the hand-curated reference (Receiver +
# Initiator + SynchronousReceiver; NOT Driver/BlockQueryWithSkip). Provider side
# is inferred (no reference yet) and should be confirmed against the BDX test plan.
# All BDX items are optional in Base.xml, so an omission never causes an error.
_BDX_REQUESTOR = {
    "MCORE.BDX.Receiver",
    "MCORE.BDX.Initiator",
    "MCORE.BDX.SynchronousReceiver",
}
_BDX_PROVIDER = {
    "MCORE.BDX.Sender",
    "MCORE.BDX.Responder",
    "MCORE.BDX.SynchronousSender",
}


@dataclass
class NodeFacts:
    """Node-level facts derived from the enabled cluster set."""

    has_ota_requestor: bool = False
    has_ota_provider: bool = False
    has_bridge: bool = False
    has_diagnostic_logs: bool = False


def node_facts_from_clusters(cluster_ids: set[str]) -> NodeFacts:
    ids = {c.lower() for c in cluster_ids}
    return NodeFacts(
        has_ota_requestor=_CLUSTER_OTA_REQUESTOR in ids,
        has_ota_provider=_CLUSTER_OTA_PROVIDER in ids,
        has_bridge=(
            _CLUSTER_BRIDGED_BASIC_INFO in ids or _CLUSTER_COMMISSIONER_CONTROL in ids
        ),
        has_diagnostic_logs=_CLUSTER_DIAGNOSTIC_LOGS in ids,
    )


def bdx_from_facts(facts: NodeFacts) -> set[str]:
    out: set[str] = set()
    if facts.has_ota_requestor:
        out |= _BDX_REQUESTOR
    if facts.has_ota_provider:
        out |= _BDX_PROVIDER
    return out


def profile_seeds(
    profile: DeviceProfile, facts: NodeFacts, transport_map: dict | None = None
) -> set[str]:
    from .cluster_engine import load_transport_map

    transport_map = transport_map or load_transport_map()
    seeds: set[str] = set()
    # Every DUT is a commissionee -- it is commissioned onto a fabric. Role is
    # ADDITIVE: commissioner/controller are extra capabilities the per-role YAML
    # layers on top, but the commissionee atom is universal and seeded here so it
    # is true for every role (never a false "No" when role=commissioner/controller).
    seeds.add("MCORE.ROLE.COMMISSIONEE")
    # Transport atoms come from transport_map.yaml -- the single place a
    # transport's policy (conditions, cluster features, MCORE atoms) is authored.
    # Other role atoms are NOT seeded here: the per-role profile YAML seeds them.
    for t in profile.transport:
        seeds.update(
            transport_map.get("transports", {}).get(t, {}).get("mcore_atoms", [])
        )
    if profile.ble_commissioning:
        seeds.add("MCORE.COM.BLE")
    if profile.wifi_paf:
        # COM.PAF then derives via "M if COM.WIFI & DD.DISCOVERY_PAF"
        seeds.add("MCORE.DD.DISCOVERY_PAF")
    if profile.nfc_commissioning:
        seeds.add("MCORE.DD.NTL")
    if profile.vendor_specific_ota:
        seeds.add("MCORE.OTA.VendorSpecific")
    seeds.update(_FLOW_SEEDS.get(profile.commissioning_flow, []))
    if profile.tcp:
        seeds.add("MCORE.SC.TCP")
    if profile.extended_discovery:
        seeds.add("MCORE.DD.EXTENDED_DISCOVERY")
        seeds.add("MCORE.SC.EXTENDED_DISCOVERY")
    for o in profile.onboarding:
        seeds.update(_ONBOARDING_SEEDS.get(o, []))
    # OTA / bridge are DERIVED from the enabled cluster set, not asked.
    if facts.has_ota_requestor:
        seeds.add("MCORE.OTA.Requestor")
    if facts.has_ota_provider:
        seeds.add("MCORE.OTA.Provider")
    if facts.has_bridge:
        seeds.add("MCORE.BRIDGE")
    # The Base question is specifically "Is the device a SHORT Idle Time ICD?"
    # -- true for the SIT flavor only (an LIT device answers it separately,
    # e.g. when it also supports dynamic SIT/LIT switching).
    if profile.is_icd and profile.icd_mode != "lit":
        seeds.add("MCORE.SC.SIT_ICD")
    return seeds


def gated_area(number: str, role_profile: dict) -> str | None:
    """The feature area (bridge / ota_requestor / ...) gating an item, if any."""
    for area, patterns in role_profile.get("feature_area_gates", {}).items():
        if any(fnmatch(number, pat) for pat in patterns):
            return area
    return None


def role_denied(number: str, role_profile: dict) -> bool:
    """True when the role's deny list (role-contradictory items) matches."""
    return any(fnmatch(number, pat) for pat in role_profile.get("deny", []))


def _gated_off(
    number: str, profile: DeviceProfile, facts: NodeFacts, role_profile: dict
) -> bool:
    gates = role_profile.get("feature_area_gates", {})
    active = {
        "bridge": facts.has_bridge,
        "ota_requestor": facts.has_ota_requestor,
        "ota_provider": facts.has_ota_provider,
        "icd": profile.is_icd,
        "diagnostic_logs": facts.has_diagnostic_logs,
    }
    for area, patterns in gates.items():
        if not active.get(area, False):
            if any(fnmatch(number, pat) for pat in patterns):
                return True
    return False


def _denied(
    number: str, profile: DeviceProfile, facts: NodeFacts, role_profile: dict
) -> bool:
    if any(fnmatch(number, pat) for pat in role_profile.get("deny", [])):
        return True
    return _gated_off(number, profile, facts, role_profile)


def compute_mcore_pics(
    profile: DeviceProfile,
    version: str,
    cluster_ids: set[str] | None = None,
    extra_seeds: set[str] | None = None,
) -> set[str]:
    """``extra_seeds``: user-claimed Base atoms; the cond fixpoint then derives
    everything a claim makes mandatory (DD.CONCATENATED_QR_CODE -> DD.QR)."""
    items = parse_pics_items(base_template_path(version))
    role_profile = load_role_profile(profile.role)
    facts = node_facts_from_clusters(cluster_ids or set())
    return _compute(items, profile, facts, role_profile, extra_seeds)


def _compute(
    items: list[PicsItem],
    profile: DeviceProfile,
    facts: NodeFacts,
    role_profile: dict,
    extra_seeds: set[str] | None = None,
) -> set[str]:
    enabled: set[str] = set()
    enabled |= profile_seeds(profile, facts)
    enabled |= set(role_profile.get("seeds", []))
    enabled |= bdx_from_facts(facts)  # BDX roles derived from OTA clusters
    enabled |= set(extra_seeds or ())  # user-claimed Base atoms

    # Step 1: only unconditionally-mandatory items are enabled here. Optional leaf
    # capabilities are NOT blanket-enabled ("maximum options" is dropped): they are
    # product-specific and unsafe to assume, so they stay OFF unless a seed / cond
    # derivation / composition turns them on. The engineer enables the few their
    # device actually supports. (Base.xml has 0 unconditional-M today, so this is
    # usually a no-op; kept for correctness if the template changes.)
    for item in items:
        if _denied(item.number, profile, facts, role_profile):
            continue
        if item.unconditional_mandatory():
            enabled.add(item.number)

    # Step 2: monotone fixpoint enabling only items that become MANDATORY given the
    # current state. Optional-with-condition items (status "O") are NOT auto-enabled:
    # an "O if <cond>" is still a product choice, and a permissive form like
    # "O if NOT(X)" would otherwise switch on by default (e.g. the commissioner
    # CTRL_CONCATENATED_QR_CODE_2 UX flag). Those stay off unless explicitly seeded.
    resolve = lambda atom: atom in enabled  # noqa: E731
    changed = True
    while changed:
        changed = False
        for item in items:
            if item.number in enabled or _denied(
                item.number, profile, facts, role_profile
            ):
                continue
            for text, cond in item.statuses:
                if text != "M" or not cond:
                    continue
                try:
                    if boolexpr.evaluate(boolexpr.parse(cond), resolve):
                        enabled.add(item.number)
                        changed = True
                        break
                except boolexpr.ExpressionSyntaxError as exc:
                    logger.warning("bad cond on %s: %s", item.number, exc)
    return enabled
