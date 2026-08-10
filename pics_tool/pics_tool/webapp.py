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
"""Web glue: a device profile -> a fully explained, per-item PICS list.

This is the single entry point the browser (Pyodide) and the local dev server
call. It runs the real cluster + MCORE engines, then annotates every item with
*why* it is set the way it is:

* ``bucket``      -- how the item is decided (input / IM-role / manual).
* ``decided_by``  -- which input(s) or derivation drove it.
* ``state``       -- ``on`` / ``off`` (the engine decided) or ``review`` (a real
                     product fact only the engineer can set).

The IM client/server role is DERIVED from the device type's mandatory client
clusters (a switch/controller is an IM client; a light/sensor is server-only) --
never from the device-type name string. See :func:`is_im_client`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import lru_cache

from esp_matter_datamodel import boolexpr, loader

from .generate import claims
from .generate.cluster_engine import (active_conditions, all_enabled_cluster_ids,
                                      generate_cluster_pics, load_transport_map)
from .generate.mcore_engine import (compute_mcore_pics, gated_area,
                                    load_role_profile, node_facts_from_clusters,
                                    role_denied)
from .generate.profile import DeviceProfile
from .generate.selection import Selection
from .generate.template_io import (base_template_path, known_item_numbers,
                                   parse_pics_items)

@lru_cache(maxsize=4)
def _model(version: str):
    # validate=False keeps jsonschema (and its native deps) out of Pyodide; the
    # shipped data model is already known-valid.
    return loader.load_version(version, validate=False)


@lru_cache(maxsize=4)
def _mcore_meta(version: str):
    """(ordered item list, feature/question text, conformance text) from Base.xml."""
    root = ET.parse(str(base_template_path(version))).getroot()
    order: list[str] = []
    feat: dict[str, str] = {}
    conds: dict[str, str] = {}
    for pi in root.iter("picsItem"):
        n = (pi.findtext("itemNumber") or "").strip()
        if not n:
            continue
        order.append(n)
        feat[n] = " ".join((pi.findtext("feature") or "").split())
        conds[n] = " ; ".join(
            f"{(s.text or '').strip()} if {(s.attrib.get('cond', '') or '').strip()}"
            if (s.attrib.get("cond", "") or "").strip() else (s.text or "").strip()
            for s in pi.findall("status"))
    return order, feat, conds


# Spelled-out conformance statuses for the detail view: a bare "O" in a
# monospace font reads as a zero.
_STATUS_WORDS = {"M": "Mandatory", "O": "Optional", "X": "Prohibited",
                 "P": "Provisional", "D": "Deprecated"}


@lru_cache(maxsize=4)
def _item_text(version: str):
    """{code: (question, conformance)} across Base.xml + every cluster template.

    The templates carry a human-readable ``<feature>`` question for each item
    ("Does the device implement the Identify Cluster as a server?"); that is what
    a person actually answers, so it -- not the PICS code -- leads the UI.
    """
    from .generate.template_io import list_templates

    def word(s):
        txt = (s.text or "").strip()
        return _STATUS_WORDS.get(txt, txt)

    out: dict[str, tuple[str, str]] = {}
    for path in list_templates(version):
        root = ET.parse(str(path)).getroot()
        for pi in root.iter("picsItem"):
            code = (pi.findtext("itemNumber") or "").strip()
            if not code:
                continue
            question = " ".join((pi.findtext("feature") or "").split())
            question = question.replace("_?", "?").replace(" _", "").strip()
            conf = " ; ".join(
                f"{word(s)} if {(s.attrib.get('cond', '') or '').strip()}"
                if (s.attrib.get("cond", "") or "").strip() else word(s)
                for s in pi.findall("status"))
            out[code] = (question, conf)
    return out


def _probe(version: str, **kw) -> set[str]:
    """Run the MCORE engine on a neutral device type, varying one input."""
    d = {"spec_version": version, "device_type": "On/Off Light",
         "transport": list(kw.get("transports", ("wifi_2g",))),
         "role": kw.get("role", "commissionee"),
         "onboarding": list(kw.get("onboarding", ("qr", "manual_pairing_code")))}
    if "ble" in kw:
        d["ble_commissioning"] = kw["ble"]
    if "paf" in kw:
        d["wifi_paf"] = kw["paf"]
    if "ntl" in kw:
        d["nfc_commissioning"] = kw["ntl"]
    if "flow" in kw:
        d["commissioning_flow"] = kw["flow"]
    if "tcp" in kw:
        d["tcp"] = kw["tcp"]
    if "extdisc" in kw:
        d["extended_discovery"] = kw["extdisc"]
    items = set(_mcore_meta(version)[0])
    return compute_mcore_pics(DeviceProfile.from_dict(d), version,
                              set(kw.get("clusters", frozenset()))) & items


@lru_cache(maxsize=4)
def _classify(version: str):
    """Classify each MCORE item into a bucket + the inputs that decide it.

    Returns (bucket_of, decided_dims): bucket_of[item] in {auto, imrole,
    manual}; decided_dims[item] = set of inputs. An item is only "decided"
    (auto/imrole) when some profile input or spec rule can actually derive it;
    everything unreachable is manual -- absence of information is NOT a "No".
    """
    order = _mcore_meta(version)[0]
    items = set(order)
    dims = {
        "transport": [dict(transports=(t,)) for t in ("wifi_2g", "wifi_5g", "thread", "ethernet")],
        "ble_commissioning": [dict(ble=True), dict(ble=False)],
        "wifi_paf": [dict(paf=True), dict(paf=False)],
        "nfc_commissioning": [dict(ntl=True), dict(ntl=False)],
        "commissioning_flow": [dict(flow=f) for f in ("standard", "user_intent", "custom")],
        "tcp": [dict(tcp=True), dict(tcp=False)],
        "extended_discovery": [dict(extdisc=True), dict(extdisc=False)],
        "role": [dict(role=r) for r in ("commissionee", "commissioner", "controller")],
        "onboarding": [dict(onboarding=x) for x in
                       ((), ("qr",), ("manual_pairing_code",),
                        ("manual_pairing_code_21",), ("nfc",))],
        "device_types": [dict(clusters=c) for c in (frozenset(), frozenset({"0x002a"}),
                         frozenset({"0x0029"}), frozenset({"0x0039", "0x0751"}))],
    }
    decided: dict[str, set] = defaultdict(set)
    reach: set[str] = set()
    for dim, variants in dims.items():
        outs = [_probe(version, **v) for v in variants]
        for s in outs:
            reach |= s
        for it in set().union(*outs) - set.intersection(*map(set, outs)):
            decided[it].add(dim)
    for r in ("commissionee", "commissioner", "controller"):
        for cl in (frozenset(), frozenset({"0x002a"}), frozenset({"0x0029"})):
            reach |= _probe(version, role=r, clusters=cl)
    manual = items - reach

    bucket_of: dict[str, str] = {}
    for n in order:
        if n.startswith("MCORE.IDM.C") or n.startswith("MCORE.IDM.S"):
            bucket_of[n] = "imrole"
        else:
            bucket_of[n] = "manual" if n in manual else "auto"
    return bucket_of, {k: sorted(v) for k, v in decided.items()}


def _find_device_type(model, name: str):
    for dt in model.device_types.values():
        if dt.name.lower() == name.lower():
            return dt
    return None


def is_im_client(model, device_type_names) -> bool:
    """True if any given device type declares a MANDATORY client cluster.

    This -- not the device-type name string -- is the reliable IM-role signal.
    "Generic Switch" is server-only despite its name; "Dimmer Switch" is a
    client because it mandates On/Off + Level Control clients.
    """
    for name in device_type_names:
        dt = _find_device_type(model, name)
        if not dt:
            continue
        for cluster in (getattr(dt, "client_clusters", {}) or {}).values():
            conf = getattr(cluster, "conformance", None)
            if getattr(conf, "type", None) == "mandatory":
                return True
    return False


def list_versions() -> list[str]:
    """Matter spec versions this build can generate PICS for.

    A version is offered only when BOTH its PICS templates and its data-model
    JSON are present, so new versions appear automatically once their data is
    added -- no UI change needed.
    """
    from importlib.resources import files as _files

    tmpl = {p.name for p in _files("pics_tool").joinpath("templates").iterdir()
            if p.is_dir()}
    models = set()
    for p in _files("esp_matter_datamodel").joinpath("datamodels").iterdir():
        m = re.match(r"datamodel_(.+)\.json$", p.name)
        if m:
            models.add(m.group(1))
    return sorted(tmpl & models)


def list_device_types(version: str = "1.6") -> list[str]:
    """Sorted application/node device-type names for the picker."""
    return sorted({dt.name for dt in _model(version).device_types.values()})


# Claim regexes/split live in the shared claims layer so the CLI derives optional
# selections identically. Gateway (cluster-side) items: "OO.C", "ACL.S".
_FEATURE_CODE_RE = claims.FEATURE_CODE_RE
_GATEWAY_RE = claims.GATEWAY_RE


@lru_cache(maxsize=4)
def _pics_to_cluster(version: str) -> dict[str, str]:
    """{PICS prefix: cluster id} for every cluster in the data model."""
    return claims.pics_to_cluster(_model(version))


@lru_cache(maxsize=4)
def _template_codes(version: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """((template file name, (itemNumber, ...)), ...) for every template."""
    return tuple((tname, tuple(code for code, _ in entries))
                 for tname, entries in _template_entries(version))


@lru_cache(maxsize=4)
def _template_entries(version: str) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """((template name, ((itemNumber, joined cond text), ...)), ...)."""
    from .generate.template_io import list_templates

    out = []
    for p in list_templates(version):
        entries = tuple((it.number, " ".join(c for _, c in it.statuses if c))
                        for it in parse_pics_items(p))
        out.append((p.name, entries))
    return tuple(out)


_FEATURE_TOKEN_RE = re.compile(r"^F[0-9a-fA-F]{2}$")
_FEATREF_RE = re.compile(r"\b([A-Z0-9_]+\.S\.F[0-9a-fA-F]{2})\b")


def _parent_of(code: str, cond: str) -> str | None:
    """The item this one is revealed under (gateway model, nested).

    * client sub-items hang under the ``X.C`` gateway;
    * server sub-items whose template cond references a same-cluster feature
      hang under that feature (``OO.S.A4001`` under ``OO.S.F00``);
    * gateways, feature rows and pure optional items have no parent.
    """
    parts = code.split(".")
    if len(parts) < 3:
        return None  # a gateway (X.S / X.C) or an odd top-level item
    prefix, side = parts[0], parts[1]
    if side == "C":
        return f"{prefix}.C"
    if side == "S" and _FEATURE_TOKEN_RE.fullmatch(parts[2]) and len(parts) == 3:
        return None  # a feature row is itself a mini-gateway
    for m in _FEATREF_RE.finditer(cond or ""):
        ref = m.group(1)
        if not ref.startswith(f"{prefix}.S.F") or ref == code:
            continue
        # A NEGATED reference ("M if NOT (OO.S.F02)") means the item applies
        # when the feature is OFF -- nesting it under the feature would reveal
        # it backwards, so a negated ref never makes a parent.
        lead = (cond or "")[max(0, m.start() - 8):m.start()]
        if "NOT" in lead.upper() or "!" in lead:
            continue
        return ref
    return None


def _cluster_label(template_name: str) -> str:
    """'On-Off Cluster Test Plan.xml' -> 'On-Off Cluster'."""
    name = template_name.rsplit(".", 1)[0]
    return name[:-len(" Test Plan")] if name.endswith(" Test Plan") else name


# Friendly display names for the KNOWN MCORE namespaces. This is presentation
# only -- group membership and counts always come from the loaded version's
# Base.xml itself (each item's own code decides its group). A namespace not in
# this map (e.g. one a future spec version introduces) automatically becomes
# its own group under its raw token name; it is never lumped into "General".
_MCORE_AREAS = {
    "COM": "Radio & Transport", "DD": "Discovery & Onboarding",
    "SC": "Secure Channel & mDNS", "IDM": "Interaction Model",
    "BDX": "Bulk Data Exchange", "OTA": "OTA Software Update",
    "BRIDGE": "Bridge", "BRIDGECLIENT": "Bridge", "DEVLIST": "Bridge",
    "ROLE": "Device Role", "DLOG": "Diagnostic Logs", "ACL": "Access Control",
    "G": "Groups", "FS": "Fabric Synchronization", "DT_SW_COMP": "General",
}


def _mcore_area(code: str) -> str:
    parts = code.split(".")
    if len(parts) < 2:
        return "General"
    return _MCORE_AREAS.get(parts[1], parts[1])


def _feature_seeds_from_codes(version: str, codes) -> dict[str, set[str]]:
    """Optional feature codes -> engine feature seeds (shared claims layer)."""
    return claims.feature_seeds_from_codes(_model(version), codes or [])


def _gateway_claims(version: str, profile: DeviceProfile, claim_codes) -> dict[str, set[str]]:
    """{gateway code: spec-mandated codes for that claimed side} (shared layer)."""
    from .generate.cluster_engine import active_conditions, load_transport_map

    conditions = active_conditions(profile, load_transport_map())
    return claims.side_claims(_model(version), profile, claim_codes or [],
                              conditions, known_item_numbers(version))


def _selection_of(profile_dict: dict, claim_codes=None) -> Selection:
    """A Selection from the UI/CLI payload.

    ``profile_dict`` may carry the multi-endpoint ``endpoints`` list (new UI) or
    the single ``device_type`` shorthand (old UI). A legacy flat ``claim_codes``
    list is folded onto endpoint 1 + node-level MCORE for back-compat.
    """
    selection = Selection.from_dict(profile_dict)
    if claim_codes:
        selection.endpoints[0].claims = list(selection.endpoints[0].claims) + [
            c for c in claim_codes if not c.startswith("MCORE.")]
        selection.mcore_claims = list(selection.mcore_claims) + [
            c for c in claim_codes if c.startswith("MCORE.")]
    return selection


def _payload_inputs(profile_dict: dict, legacy_claims=None):
    """Everything generate_payload needs, with claims scoped per ENDPOINT id.

    Claims may arrive three ways, all unified here into ``{endpoint_id: [codes]}``
    (0 = Root Node / EP0, 1..N = application endpoints) + a node-level MCORE set:
    - the new UI sends ``profile_dict["claims_by_tab"]`` = {"base":[...], "0":[...], "1":[...]};
    - the CLI/Selection puts claims inside ``endpoints[i].claims`` + ``mcore_claims``;
    - a legacy flat ``claims`` arg folds onto EP1 + MCORE.
    """
    selection = Selection.from_dict(profile_dict)
    version = selection.profile.spec_version
    model = _model(version)
    conditions = active_conditions(selection.profile, load_transport_map())
    known = known_item_numbers(version)

    by_ep: dict[int, list] = {}
    mcore: list = list(selection.mcore_claims)
    for epid, ep in enumerate(selection.endpoints, start=1):
        if ep.claims:
            by_ep.setdefault(epid, []).extend(ep.claims)
    cbt = profile_dict.get("claims_by_tab")
    if isinstance(cbt, dict):
        for t, codes in cbt.items():
            if t == "base":
                mcore += [c for c in codes if c.startswith("MCORE.")]
            elif str(t).isdigit():
                by_ep.setdefault(int(t), []).extend(codes)
    if legacy_claims:
        by_ep.setdefault(1, []).extend([c for c in legacy_claims if not c.startswith("MCORE.")])
        mcore += [c for c in legacy_claims if c.startswith("MCORE.")]

    app_endpoints = [ep.device_types for ep in selection.endpoints]
    per_ep_seeds = {epid: claims.feature_seeds_from_codes(model, codes)
                    for epid, codes in by_ep.items()}
    per_ep_side = {epid: claims.side_claims(model, selection.profile, codes, conditions, known)
                   for epid, codes in by_ep.items()}
    mcore_atoms = {c for c in mcore if c.startswith("MCORE.")}
    all_claims = [c for codes in by_ep.values() for c in codes]
    return selection, app_endpoints, per_ep_seeds, per_ep_side, mcore_atoms, all_claims


_CODE_TOKEN = re.compile(r"[A-Z0-9_]+\.[SC](?:\.[A-Za-z0-9]+)*|MCORE\.[A-Za-z0-9_.]+")


def _pretty(name: str) -> str:
    """Split a camelCase element name for reading: 'OccupiedHeatingSetpoint' -> 'Occupied Heating Setpoint'."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name or "").strip()


def _short_name(code: str, model, prefix_map: dict):
    """Human name for a cluster PICS code, e.g. 'OO.S.F00' -> 'Lighting'.

    Returns None for codes we can't resolve (unknown cluster, MCORE, etc.) so
    callers can fall back to the code itself.
    """
    if not code or code.startswith(("MCORE.", "PIXIT.")):
        return None
    parts = code.split(".")
    if len(parts) < 2:
        return None
    cl = model.clusters.get(prefix_map.get(parts[0]))
    if cl is None:
        return None
    role = "server" if parts[1] == "S" else "client" if parts[1] == "C" else parts[1]
    if len(parts) == 2:
        return f"{cl.name} ({role})"
    tag, val = parts[2][0], parts[2][1:]
    if tag == "F":
        f = cl.features.get(int(val, 16)) if val else None
        return _pretty(f.name) if f else None
    lookup = {"A": cl.attributes, "C": {**cl.accepted_commands, **cl.generated_commands},
              "E": cl.events}.get(tag)
    if lookup is not None:
        el = lookup.get("0x" + val.lower()) or lookup.get(val.lower())
        return _pretty(el.name) if el else None
    return None


def _humanize_cond(cond: str, model, prefix_map: dict) -> str:
    """Replace PICS codes in a conformance expression with human names."""
    out = _CODE_TOKEN.sub(lambda m: _short_name(m.group(0), model, prefix_map) or m.group(0), cond)
    for op, word in (("AND", "and"), ("OR", "or"), ("NOT", "not")):
        out = re.sub(rf"\b{op}\b", word, out)
    return " ".join(out.split()).strip()


def _why(code: str, group: str, conf: str, model, prefix_map: dict) -> str:
    """A plain-language reason for a CLUSTER item -- ONLY when it adds information.

    Returns "" for the generic cases (plain optional, or unconditionally
    mandatory): those just restate the Optional/Mandatory group the row already
    sits under, so repeating them on every row is noise. A reason is returned
    only when the item is mandatory *because of a feature/condition* the user
    enabled (e.g. "Required when Color Control (server) and XY"), which is the
    part a reader can't infer from the grouping. (MCORE items get their own
    input-tied reason via mcore_why.)
    """
    if code.startswith("MCORE.") or group == "manual":
        return ""
    if " if " in conf:
        cond = conf.split(" if ", 1)[1].split(" ; ")[0]
        human = _humanize_cond(cond, model, prefix_map)
        # a bare cluster-role condition ("X.S") == "this cluster is present":
        # not informative beyond the Mandatory grouping, so no reason shown.
        parts = code.split(".")
        cl = model.clusters.get(prefix_map.get(parts[0])) if len(parts) > 1 else None
        if cl and human == f"{cl.name} ({'server' if parts[1] == 'S' else 'client'})":
            return ""
        return f"Required when {human}."
    return ""  # unconditionally mandatory: redundant with the Mandatory grouping


def generate_payload(profile_dict: dict, claims=None) -> dict:
    """Run the engines for a profile and return every question, plainly answered.

    Each item is a question a human answers: ``question`` (plain English),
    ``answer`` (yes/no the tool pre-filled), ``needs_you`` (the tool couldn't
    know -- your call). Technical fields (PICS code, conformance) travel along
    for an optional detail view, but the question leads.

    ``claims`` (optional) are PICS codes the user switched ON that carry
    spec consequences: feature codes re-enter the engine as seeds, and gateway
    codes (``X.S``/``X.C``) pull in the claimed side's mandatory elements.
    """
    version = profile_dict.get("spec_version", "1.6")
    order = _mcore_meta(version)[0]
    bucket_of, decided_dims = _classify(version)
    text = _item_text(version)
    model = _model(version)
    prefix_map = _pics_to_cluster(version)
    # Per-endpoint claims: a feature/side claimed on EP1 never leaks to EP2.
    selection, app_endpoints, per_ep_seeds, per_ep_side, mcore_claim_atoms, all_claim_codes = \
        _payload_inputs(profile_dict, claims)
    profile = selection.profile

    # Real pipeline: clusters first, then MCORE seeded by the enabled cluster set.
    # TWO runs on purpose: the baseline (profile only) defines "Answered by the
    # tool"; whatever the user's claims add on top stays in Optional Items --
    # pre-filled Yes where the spec mandates it, but it is THEIR selection.
    baseline = generate_cluster_pics(model, profile, app_endpoints=app_endpoints)
    endpoints = generate_cluster_pics(model, profile, app_endpoints=app_endpoints,
                                      per_endpoint_feature_seeds=per_ep_seeds)
    baseline_pics = {ep.endpoint: ep.pics for ep in baseline}
    cluster_ids = all_enabled_cluster_ids(endpoints)
    mcore_on = compute_mcore_pics(profile, version, cluster_ids) & set(order)
    # User-claimed Base atoms re-enter the cond fixpoint, exactly like feature
    # and gateway claims: claiming DD.CONCATENATED_QR_CODE makes DD.QR
    # mandatory AT GENERATION TIME, not only in the export validator. The delta
    # over the claim-free run stays in Optional Items (it is the user's claim).
    mcore_claimed: set = set()
    if mcore_claim_atoms:
        mcore_full = compute_mcore_pics(profile, version, cluster_ids,
                                        extra_seeds=mcore_claim_atoms) & set(order)
        mcore_claimed = mcore_full - mcore_on
    # IM role considers every application endpoint's device types (a switch on any
    # endpoint makes the node an IM client).
    all_app_dts = [dt for ep in selection.endpoints for dt in ep.device_types]
    derived_im_types = is_im_client(model, [*all_app_dts, *profile.node_device_types])
    all_side_codes = [c for side in per_ep_side.values()
                      for codes in side.values() for c in codes]
    # A claimed client gateway (X.C = Yes) IS client behavior: the IM role must
    # follow the claim, or the export would send commands while declaring
    # "IM server only" -- an inconsistent PICS.
    claimed_client = any(_GATEWAY_RE.match(c) and c.endswith(".C")
                         for c in all_claim_codes)
    derived_im = derived_im_types or claimed_client
    im_client = derived_im if profile.im_client is None else profile.im_client
    # Client role driven purely by the user's claims -> its IDM consequences
    # belong in Manual selection (pre-filled Yes), not "Selected by the tool".
    im_from_claims = (im_client and not derived_im_types
                      and profile.im_client is None)
    # Does the device send commands (client Tx)? Mandated by the device type,
    # or a spec consequence of a claimed client side -- either way,
    # IDM.C.InvokeRequest is derivable, not a guess.
    has_client_tx = (any(re.search(r"\.C\.C[0-9a-fA-F]{2}\.Tx$", c)
                         for ep in baseline for c in ep.pics)
                     or any(re.search(r"\.C\.C[0-9a-fA-F]{2}\.Tx$", c)
                            for c in all_side_codes))
    role_profile = load_role_profile(profile.role)
    facts = node_facts_from_clusters(cluster_ids)

    # OTA is now an explicit input (requestor / provider / vendor-specific),
    # so the whole OTA/BDX area is input-decided -- including Base.xml's own
    # derivation that a commissionee WITHOUT an OTA Requestor must support
    # vendor-specific OTA. Bridge remains unasked in phase 1: unless the
    # composition declares an Aggregator, its items are unknowable -- and
    # "no information" is never a "No".
    bridge_declared = any("aggregator" in n.lower()
                          for n in profile.node_device_types)
    gate_active = {"bridge": facts.has_bridge,
                   "ota_requestor": facts.has_ota_requestor,
                   "ota_provider": facts.has_ota_provider,
                   "icd": profile.is_icd}
    gate_declared = {"bridge": bridge_declared, "ota_requestor": True,
                     "ota_provider": True, "icd": False}
    _BRIDGE_NS = ("MCORE.BRIDGE", "MCORE.DEVLIST.")

    def state(n: str, bucket: str) -> str:
        if not bridge_declared and n.startswith(_BRIDGE_NS):
            return "review"
        if bucket == "auto":
            if n in mcore_on:
                return "on"
            if n in mcore_claimed:
                return "claimed"
            if n.startswith("MCORE.BDX."):
                # BDX has consumers beyond OTA (e.g. Diagnostic Logs transfers
                # over BDX, where the DUT can even be the Sender). The OTA
                # input derives BDX roles it NEEDS; it cannot rule the rest
                # out -- those stay Optional Items, never a decided No.
                return "review"
            return "off"
        if bucket == "imrole":
            if n == "MCORE.IDM.S":
                return "on"                       # DUT hosts clusters -> IM server
            if n.startswith("MCORE.IDM.S."):
                # LargeData / PersistentSubscription: product facts (the
                # hand-curated reference answers them differently) -> manual.
                return "review"
            if not im_client:
                return "off"                      # input-backed: IM role control
            if n == "MCORE.IDM.C":
                # "claimed": Yes, but in Manual selection -- the role follows
                # the user's client-cluster claim, not the device type.
                return "claimed" if im_from_claims else "on"
            if n == "MCORE.IDM.C.InvokeRequest" and has_client_tx:
                return "claimed" if im_from_claims else "on"
            # per-message-type / per-datatype client capabilities (write Bool,
            # batch commands, subscribe events, ...): only the vendor knows.
            return "review"
        if n in mcore_claimed:
            return "claimed"
        if role_denied(n, role_profile):
            # Contradicted by the chosen role: the tool CAN decide this --
            # e.g. commissioner-side scanning/CTRL questions are a defendable
            # No for a commissionee.
            return "off"
        area = gated_area(n, role_profile)
        if area and not gate_active[area]:
            # The feature area is off. That is a decision only when the user
            # actually declared the governing input; otherwise it is unknown.
            return "off" if gate_declared[area] else "review"
        # manual: a real product fact no input can derive (TCP, PAF, tamper
        # resistance, DLOG fields, ...). Never presented as tool-decided.
        return "review"

    def q_of(code: str) -> str:
        return text.get(code, ("", ""))[0] or code
    def conf_of(code: str) -> str:
        return text.get(code, ("", ""))[1] or "-"

    def row(code, tab, st, group, cluster, parent=None, why=None, needs_you=None):
        # "needs_you" == a live decision the user must make NOW. By default it is
        # the manual group (Base product-facts the tool cannot derive). Cluster
        # items pass it explicitly: a genuine optional choice that is applicable
        # right now (see the endpoint loop). "Mandatory if <feature>" elements are
        # auto-resolved by the engine (Yes when the gate is on, else not
        # applicable), so they are NOT questions even though they sit in the same
        # manual section for the UI to nest and display.
        # "parent" is the gateway/feature this item reveals under.
        # "why" is a caller-supplied plain-language reason (MCORE items pass one);
        # cluster items fall back to the conformance-derived _why().
        return {"tab": tab, "code": code, "question": q_of(code),
                "answer": "yes" if st in ("on", "claimed") else "no",
                "group": group, "cluster": cluster, "parent": parent,
                "needs_you": (group == "manual") if needs_you is None else needs_you,
                "conformance": conf_of(code),
                "why": why if why is not None else _why(code, group, conf_of(code), model, prefix_map)}

    # Three distinct sections, shown as separate tabs: the node-level Base.xml
    # (MCORE) questions, the Root Node cluster PICS on endpoint 0 (Basic Info,
    # ACL, CNET, ...), and each application endpoint's cluster PICS. All are
    # exportable -- a PICS package without any one of them is invalid.
    # Within every tab, items split into two groups:
    #   decided -- the engine derived the answer (mandatory conformance / seeds
    #              / role policy), shown with a defendable Yes or No;
    #   manual  -- everything else in the SAME template files (optional cluster
    #              elements, undecidable Base product facts): every single
    #              template item is visible, default No, for the user to claim.
    # Only codes that exist in the templates are claimable: data-model codes
    # with no template item (e.g. OTAR.S.* -- the OTA test plan runs off
    # MCORE.OTA/BDX instead) have no question and cannot be exported.
    # Plain-language reason for a node-level (MCORE) item, tied to the input
    # that actually drives it (decided_dims), so "why is this Yes/No?" is
    # answerable without knowing PICS internals.
    _DIM_LABEL = {"transport": "network transport", "role": "device role",
                  "onboarding": "onboarding", "ble_commissioning": "BLE commissioning",
                  "wifi_paf": "Wi-Fi PAF commissioning", "nfc_commissioning": "NFC commissioning",
                  "device_types": "device type"}
    _ROLE_PHRASE = {"commissionee": "an End Device", "commissioner": "a Commissioner",
                    "controller": "a Controller"}

    def _dims_phrase(n: str) -> str:
        labels = [_DIM_LABEL.get(d, d) for d in decided_dims.get(n, [])]
        if not labels:
            return ""
        if len(labels) == 1:
            return f"your {labels[0]} selection"
        return "your " + ", ".join(labels[:-1]) + f" and {labels[-1]} selections"

    def mcore_why(n: str, st: str) -> str:
        if st == "claimed":
            return "Yes — you turned this on."
        if st == "review":
            return "Only you can answer this — it's a product-specific detail about your device."
        dims = _dims_phrase(n)
        if st == "on":
            return f"Yes — determined by {dims}." if dims else "Mandatory for every Matter device."
        # decided No
        if role_denied(n, role_profile):
            return f"No — not applicable for {_ROLE_PHRASE.get(profile.role, profile.role)}."
        area = gated_area(n, role_profile)
        if area and not gate_active.get(area):
            return f"No — the {area.replace('_', ' ')} feature is not enabled."
        return f"No — determined by {dims}." if dims else "No — not required for this device."

    known = known_item_numbers(version)
    # Base items with a reveal parent: LargeData rides on Matter-over-TCP.
    _BASE_PARENTS = {"MCORE.IDM.S.LargeData": "MCORE.SC.TCP"}
    items = []
    for n in order:
        st = state(n, bucket_of[n])
        group = "manual" if st in ("review", "claimed") else "decided"
        items.append(row(n, "base", st, group, _mcore_area(n),
                         parent=_BASE_PARENTS.get(n), why=mcore_why(n, st)))
    tabs = [{"id": "base", "label": "Base PICS", "caption": "Node-Wide"}]
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        tab = str(ep.endpoint)
        if ep.endpoint == 0:
            tabs.append({"id": tab, "label": "Root Node",
                         "caption": "Endpoint 0 clusters"})
        else:
            tabs.append({"id": tab, "label": ep.device_type_name,
                         "caption": f"Endpoint {ep.endpoint} clusters"})
        # "Selected by the tool" = the claim-free baseline run. Everything the
        # user's claims add (feature codes, gateway sides + their spec-mandated
        # elements) is pre-filled Yes but stays in Manual selection.
        tool_here = baseline_pics.get(ep.endpoint, set()) & known
        claim_here = (ep.pics & known) - tool_here
        for gateway, claim_codes in per_ep_side.get(ep.endpoint, {}).items():
            for _, codes in _template_codes(version):
                if gateway in codes and tool_here.intersection(codes):
                    claim_here |= claim_codes - tool_here
                    break
        # Emit per template so every item carries its cluster. Manual-section
        # ordering inside a cluster: pure optional server items first, then
        # each server feature immediately followed by ITS dependent items
        # (they reveal right below the feature when it is switched on), then
        # the client gateway with its items. A code present in several
        # templates (ACL.S is in both the ACL and the ACE plan) belongs to the
        # first that lists it.
        # Everything already Yes for this endpoint (baseline + the user's claims,
        # incl. feature-seeded mandatory dependents): used to decide which gated
        # optional items are *applicable* (a live question) right now.
        enabled_here = tool_here | claim_here
        seen: set[str] = set()
        for tname, entries in _template_entries(version):
            t_codes = [c for c, _ in entries]
            if not tool_here.intersection(t_codes):
                continue  # template not exported for this endpoint
            cluster = _cluster_label(tname)
            pure: list[tuple[str, str, str | None]] = []
            feats: list[str] = []
            featdeps: dict[str, list[tuple[str, str, str]]] = {}
            client_rows: list[tuple[str, str, str | None]] = []
            for code, cond in entries:
                if code in seen or code.startswith("MCORE."):
                    continue
                seen.add(code)
                if code in tool_here:
                    items.append(row(code, tab, "on", "decided", cluster))
                    continue
                # Spec only: anything the spec does not mandate (including
                # client roles -- optional for any device) is a vendor choice:
                # a manual question, never a tool-decided No.
                st = "on" if code in claim_here else "off"
                parent = _parent_of(code, cond)
                parts = code.split(".")
                if len(parts) > 1 and parts[1] == "C":
                    if len(parts) == 2:
                        client_rows.insert(0, (code, st, None))   # gateway first
                    else:
                        client_rows.append((code, st, parent))
                elif len(parts) == 3 and _FEATURE_TOKEN_RE.fullmatch(parts[2]):
                    feats.append(code)
                    # the feature row leads its own block; dependents follow it
                    featdeps.setdefault(code, []).insert(0, (code, st, None))
                elif parent:
                    featdeps.setdefault(parent, []).append((code, st, parent))
                else:
                    pure.append((code, st, None))
            ordered = list(pure)
            for feat in feats:
                ordered.extend(featdeps.pop(feat))
            # dependents of DECIDED features (feature already Yes by conformance)
            for dep_rows in featdeps.values():
                ordered.extend(dep_rows)
            ordered.extend(client_rows)
            for code, st, parent in ordered:
                # A live question only if the element has a genuine OPTIONAL clause
                # AND it is applicable now (top-level, or its gating parent is
                # enabled). A purely "Mandatory if <feature>" element is derived by
                # the engine -- Yes once its gate is on, otherwise not applicable --
                # so it is never asked. (Compound conformance like "Mandatory if
                # CC.S AND CC.S.F01 ; Optional if CC.S" still counts as optional --
                # the substring test keeps it a question.)
                live = ("optional" in conf_of(code).lower()
                        and (parent is None or parent in enabled_here))
                items.append(row(code, tab, st, "manual", cluster, parent,
                                 needs_you=live))

    counts = {"yes": 0, "no": 0, "needs_you": 0}
    for it in items:
        counts["yes" if it["answer"] == "yes" else "no"] += 1
        counts["needs_you"] += it["needs_you"]

    return {
        "spec_version": version,
        "device_type": profile.device_type,
        "im_role": "IM client + server" if im_client else "IM server only",
        "im_client": im_client,
        "im_client_derived": derived_im,
        "im_client_overridden": profile.im_client is not None and profile.im_client != derived_im,
        # Echo the exact profile that produced this payload so export/validation
        # always work on the same snapshot the user is looking at.
        "profile": profile_dict,
        "tabs": tabs,
        "counts": counts,
        "total": len(items),
        "items": items,
    }


def _endpoint_of_prefix(endpoints, version: str) -> dict[str, int]:
    """{PICS cluster prefix: endpoint id} from the generated endpoint layout."""
    model = _model(version)
    cluster_pics = {cid: c.pics for cid, c in model.clusters.items() if c.pics}
    mapping: dict[str, int] = {}
    # Later endpoints win on a duplicate prefix so a cluster present on both EP0
    # and the app endpoint (e.g. Identify) keeps its app-endpoint copy; EP0's
    # copy is still exported because codes are routed per-prefix per-endpoint below.
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        for cid in ep.cluster_ids | ep.client_cluster_ids:
            prefix = cluster_pics.get(cid)
            if prefix:
                mapping.setdefault(prefix, ep.endpoint)
    return mapping


def export_pics_files(profile_dict: dict, enabled_codes) -> dict:
    """Return {relative_path: xml_text} for the filled per-endpoint PICS.

    ``enabled_codes`` is exactly the set the UI shows as "yes" (what you see is
    what you export). Preferred form: {tab: [codes]} as the UI displays them,
    so every claim lands in the SAME endpoint file the user answered it on
    (a Descriptor item claimed on EP1 goes to endpoint1's file even though EP0
    also hosts Descriptor). A flat list is still accepted (CLI/back-compat) and
    routed by generated layout + cluster prefix.
    """
    import os
    import tempfile

    from .generate.writer import write_pics

    version = profile_dict.get("spec_version", "1.6")
    selection = _selection_of(profile_dict)
    profile = selection.profile
    app_endpoints = [ep.device_types for ep in selection.endpoints]
    by_tab = enabled_codes if isinstance(enabled_codes, dict) else None
    flat = ([c for codes in by_tab.values() for c in codes] if by_tab
            else list(enabled_codes))
    extra_seeds = _feature_seeds_from_codes(version, flat)
    endpoints = generate_cluster_pics(_model(version), profile,
                                      app_endpoints=app_endpoints,
                                      extra_feature_seeds=extra_seeds)
    app_ep = next((e.endpoint for e in endpoints if e.endpoint != 0), 1)

    by_ep: dict[int, set] = defaultdict(set)
    if by_tab is not None:
        # Faithful routing: the tab the user answered on IS the endpoint.
        for t, codes in by_tab.items():
            epid = 0 if t == "base" else (int(t) if str(t).isdigit() else app_ep)
            for code in codes:
                by_ep[0 if code.startswith("MCORE.") else epid].add(code)
    else:
        # Per-endpoint code sets from the generated layout: a code belongs to
        # every endpoint whose generated PICS contains it; a user-added code is
        # routed by its cluster prefix, falling back to the app endpoint.
        prefix_ep = _endpoint_of_prefix(endpoints, version)
        generated = {ep.endpoint: ep.pics for ep in endpoints}
        for code in flat:
            if code.startswith("MCORE."):
                by_ep[0].add(code)
                continue
            hit = False
            for epid, pics in generated.items():
                if code in pics:
                    by_ep[epid].add(code)
                    hit = True
            if not hit:
                by_ep[prefix_ep.get(code.split(".", 1)[0], app_ep)].add(code)

    out = tempfile.mkdtemp(prefix="pics_out_")
    write_pics(version, dict(by_ep), out)
    files: dict[str, str] = {}
    for base, _, names in os.walk(out):
        for name in sorted(names):
            path = os.path.join(base, name)
            files[os.path.relpath(path, out)] = open(path, encoding="utf-8").read()
    return files


def generate_scaffold_files(profile_dict: dict, claims_by_tab=None) -> dict:
    """The esp-matter data-model construction code for this selection.

    Drives the SAME engine as the CLI's ``gen-scaffold`` (``generate_scaffold``),
    so identical input yields identical code in the browser and on the command
    line. Optional feature/side claims the user switched ON in the UI arrive as
    ``claims_by_tab`` -- the endpoint-tab map from ``generate_payload`` ("1",
    "2", ... = application endpoints; "base"/MCORE don't affect endpoint
    construction) -- and are folded onto the matching endpoint so they surface as
    precise enable-guidance in the snippet.

    Returns ``{snippet, file, endpoints:[{endpoint, device_types, features,
    sides}]}`` -- the code, the suggested file name, and a small recap of the
    optional bits it called out (for the UI note).
    """
    from .generate.scaffold import generate_scaffold

    model = _model(profile_dict.get("spec_version", "1.6"))
    selection = Selection.from_dict(profile_dict)
    if isinstance(claims_by_tab, dict):
        for tab_id, codes in claims_by_tab.items():
            if not str(tab_id).isdigit():
                continue                       # "base"/MCORE: node-level, not an endpoint
            idx = int(tab_id) - 1              # tabs are 1-based (EP1..EPN)
            if 0 <= idx < len(selection.endpoints):
                ep = selection.endpoints[idx]
                ep.claims = list(ep.claims) + [
                    c for c in codes if not c.startswith("MCORE.")]
    result = generate_scaffold(selection, model)

    # elements omitted from the code (no esp_matter signature) -> exclude from the
    # "added" recap so the chips reflect only what the code actually emits.
    _omitted = {(u["endpoint"], u["cluster"], u["name"], u["kind"]) for u in result.unresolved}

    def _optional_items(e):
        """Structured recap of the optional bits the code ADDS (resolved only)."""
        raw = [{"cluster": f.cluster_name, "name": f.feature_name, "kind": "feature"}
               for f in e.optional_features]
        raw += [{"cluster": a.cluster_name, "name": a.name, "kind": "attribute"}
                for a in e.optional_attributes]
        raw += [{"cluster": c.cluster_name, "name": c.name, "kind": "command"}
                for c in e.optional_commands]
        raw += [{"cluster": v.cluster_name, "name": v.name, "kind": "event"}
                for v in e.optional_events]
        raw += [{"cluster": s.cluster_name, "name": s.side_text, "kind": "cluster"}
                for s in e.optional_sides]
        return [it for it in raw
                if (e.endpoint, it["cluster"], it["name"], it["kind"]) not in _omitted]

    return {
        "snippet": result.snippet,
        "file": "app_data_model.cpp",
        "exact": result.exact,                    # a knowledge source was consulted
        "knowledge_source": result.knowledge_source,
        # selected optional elements with no matching esp_matter function: omitted
        # from the code (kept compile-ready), listed here to add manually.
        "unresolved": result.unresolved,
        "endpoints": [
            {"endpoint": e.endpoint, "device_types": e.device_types,
             "label": " + ".join(e.device_types),   # device type(s) on this endpoint
             # structured recap the UI renders as chips, grouped per endpoint
             "optional": _optional_items(e),
             # flat string forms kept for the CLI / back-compat
             "features": [f"{f.cluster_name} / {f.feature_name}"
                          for f in e.optional_features],
             "attributes": [f"{a.cluster_name} / {a.name}" for a in e.optional_attributes],
             "commands": [f"{c.cluster_name} / {c.name}" for c in e.optional_commands],
             "events": [f"{v.cluster_name} / {v.name}" for v in e.optional_events],
             "sides": [f"{s.cluster_name} ({s.side_text})" for s in e.optional_sides]
                      + list(e.unknown_sides)}
            for e in result.endpoints],
    }


# Items we deliberately claim/leave despite a known CSA template gap. They
# surface as WARNINGS with an explanation, never as blocking errors.
_KNOWN_TEMPLATE_QUIRKS = {
    "MCORE.DD.STANDARD_COMM_FLOW":
        "claimed deliberately: the template only defines 'M if 11_MANUAL_PC' "
        "(commissioner-side) with no plain O status; DD test selection keys "
        "off this item. The CSA validator shows the same notice.",
}


def _effective_status(statuses, resolve):
    """First status whose cond holds (no cond = always). None if none apply."""
    for status_text, cond in statuses:
        if not cond:
            return status_text
        try:
            if boolexpr.evaluate(boolexpr.parse(cond), resolve):
                return status_text
        except boolexpr.ExpressionSyntaxError:
            continue
    return None


def validate_selection(profile_dict: dict, enabled_codes) -> list[dict]:
    """Full spec-consistency validation of the final Yes set before export.

    Mirrors the CSA PICS validator's dependency rules over everything that
    will be exported, with a cascade closure so one round of fixes yields a
    stable set. Each problem: {code, question, why, severity} where severity
    is "error" (spec violation) or "warning" (expected/benign notice).

    ``enabled_codes`` is preferably {tab: [codes]} (per-endpoint scoping, as
    the UI shows them); a flat list is accepted and validated in one scope.
    """
    version = profile_dict.get("spec_version", "1.6")
    selection = _selection_of(profile_dict)
    profile = selection.profile
    app_endpoints = [ep.device_types for ep in selection.endpoints]
    by_tab = enabled_codes if isinstance(enabled_codes, dict) else None
    flat = set(c for codes in by_tab.values() for c in codes) if by_tab \
        else set(enabled_codes)
    text = _item_text(version)
    known = known_item_numbers(version)
    model = _model(version)
    prefix_map = _pics_to_cluster(version)
    problems: list[dict] = []
    flagged: set[str] = set()

    def add(code: str, why: str, severity: str = "error", tab: str = None) -> None:
        if code in flagged:
            return
        flagged.add(code)
        cl = model.clusters.get(prefix_map.get(code.split(".")[0])) if "." in code else None
        problems.append({"code": code,
                         "question": text.get(code, ("", ""))[0] or code,
                         # plain-language label + cluster for the dialog; the raw
                         # code/expression stay available under "technical details".
                         "name": _short_name(code, model, prefix_map)
                                 or text.get(code, ("", ""))[0] or code,
                         "cluster": cl.name if cl else ("Node-wide" if code.startswith("MCORE.") else ""),
                         "why": why, "severity": severity,
                         # which endpoint tab to enable it on (the UI's auto-fix
                         # needs this: the same code lives on several endpoints).
                         "tab": tab or ("base" if code.startswith("MCORE.") else None)})

    # 1) Engine side: re-run with the user's claims; everything the engine
    #    yields is mandatory for the claimed device.
    extra_seeds = _feature_seeds_from_codes(version, flat)
    endpoints = generate_cluster_pics(_model(version), profile,
                                      app_endpoints=app_endpoints,
                                      extra_feature_seeds=extra_seeds)
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        for code in sorted((ep.pics & known) - flat):
            add(code, f"mandatory on endpoint {ep.endpoint} for this device profile",
                tab=str(ep.endpoint))

    # 2) Gateway claims: a claimed X.S / X.C mandates its side's elements.
    for gateway, claim_codes in _gateway_claims(version, profile, flat).items():
        gname = _short_name(gateway, model, prefix_map) or gateway
        for code in sorted(claim_codes - flat):
            add(code, f"Required because you enabled {gname}.")

    # 2b) IM-role consistency: a device that claims any client cluster side or
    # sends client commands IS an IM client -- MCORE.IDM.C (and InvokeRequest,
    # when commands are sent) must be claimed with it.
    client_evidence = sorted(c for c in flat
                             if not c.startswith("MCORE.")
                             and (c.split(".")[1:2] == ["C"]))
    if client_evidence:
        if "MCORE.IDM.C" not in flat:
            add("MCORE.IDM.C",
                f"the device initiates IM requests (you claimed {client_evidence[0]})")
        if (any(re.search(r"\.C\.C[0-9a-fA-F]{2}\.Tx$", c) for c in client_evidence)
                and "MCORE.IDM.C.InvokeRequest" not in flat):
            add("MCORE.IDM.C.InvokeRequest",
                "the device sends client commands (Tx), which are Invoke requests")

    # 3) Template sweep (what the CSA validator checks): per exported scope,
    #    evaluate every item's effective status. Runs to a fixpoint so newly
    #    mandatory items cascade (enabling A may make B mandatory).
    from .generate.template_io import list_templates

    parsed = {p.name: parse_pics_items(p) for p in list_templates(version)}

    if by_tab:
        base_set = set(by_tab.get("base", []))
        scopes = []
        for t, codes in by_tab.items():
            if t == "base":
                continue
            scopes.append((t, set(codes) | base_set))
        if not any(t == "0" for t, _ in scopes) and base_set:
            scopes.append(("0", set(base_set)))
    else:
        scopes = [("all", set(flat))]

    for scope_name, scope_enabled in scopes:
        scope_templates = [name for name, items in parsed.items()
                           if any(it.number in scope_enabled for it in items)]
        working = set(scope_enabled)
        changed = True
        while changed:
            changed = False
            resolve = lambda a: a in working  # noqa: E731
            for name in scope_templates:
                for it in parsed[name]:
                    if it.number in working:
                        continue
                    if _effective_status(it.statuses, resolve) == "M":
                        cond_text = " ; ".join(c for _, c in it.statuses if c)
                        why = ("Required when " + _humanize_cond(cond_text, model, prefix_map) + "."
                               if cond_text else "Required by the spec for this configuration.")
                        add(it.number, why, tab=scope_name)
                        working.add(it.number)
                        changed = True
        # prohibited / inapplicable checks on what the user actually enabled
        resolve = lambda a: a in working  # noqa: E731
        for name in scope_templates:
            for it in parsed[name]:
                if it.number not in scope_enabled:
                    continue
                eff = _effective_status(it.statuses, resolve)
                if eff == "X":
                    add(it.number, "PROHIBITED by the spec for this configuration",
                        tab=scope_name)
                elif eff is None:
                    quirk = _KNOWN_TEMPLATE_QUIRKS.get(it.number)
                    add(it.number,
                        quirk or "enabled, but no status condition applies to "
                                 "this configuration (the validator will note it)",
                        severity="warning", tab=scope_name)
    return problems


# --- JSON string wrappers (Pyodide-friendly: no proxy juggling in JS) --------

def generate_payload_json(profile_json: str, claims_json: str = "[]") -> str:
    return json.dumps(generate_payload(json.loads(profile_json),
                                       json.loads(claims_json)))


def list_device_types_json(version: str = "1.6") -> str:
    return json.dumps(list_device_types(version))


def list_versions_json() -> str:
    return json.dumps(list_versions())


def export_pics_files_json(profile_json: str, enabled_json: str = "[]") -> str:
    return json.dumps(export_pics_files(json.loads(profile_json), json.loads(enabled_json)))


def validate_selection_json(profile_json: str, enabled_json: str = "[]") -> str:
    return json.dumps(validate_selection(json.loads(profile_json), json.loads(enabled_json)))


def generate_scaffold_json(profile_json: str, claims_json: str = "{}") -> str:
    return json.dumps(generate_scaffold_files(json.loads(profile_json),
                                              json.loads(claims_json)))
