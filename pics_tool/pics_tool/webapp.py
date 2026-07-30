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

from .generate.cluster_engine import all_enabled_cluster_ids, generate_cluster_pics
from .generate.mcore_engine import (compute_mcore_pics, gated_area,
                                    load_role_profile, node_facts_from_clusters,
                                    role_denied)
from .generate.profile import DeviceProfile
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


@lru_cache(maxsize=4)
def _item_text(version: str):
    """{code: (question, conformance)} across Base.xml + every cluster template.

    The templates carry a human-readable ``<feature>`` question for each item
    ("Does the device implement the Identify Cluster as a server?"); that is what
    a person actually answers, so it -- not the PICS code -- leads the UI.
    """
    from .generate.template_io import list_templates

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
                f"{(s.text or '').strip()} if {(s.attrib.get('cond', '') or '').strip()}"
                if (s.attrib.get("cond", "") or "").strip() else (s.text or "").strip()
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
        "role": [dict(role=r) for r in ("commissionee", "commissioner", "controller")],
        "onboarding": [dict(onboarding=x) for x in ((), ("qr",), ("manual_pairing_code",), ("nfc",))],
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


_FEATURE_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.F(?P<bit>[0-9a-fA-F]{2})$")
# Gateway (cluster-side) items: "OO.C", "ACL.S" -- claiming one is a fact from
# which the spec derives the side's mandatory elements (gateway model, option b).
_GATEWAY_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.(?P<side>[SC])$")


@lru_cache(maxsize=4)
def _pics_to_cluster(version: str) -> dict[str, str]:
    """{PICS prefix: cluster id} for every cluster in the data model."""
    return {c.pics: cid for cid, c in _model(version).clusters.items() if c.pics}


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
    """Turn user-enabled feature PICS codes into engine feature seeds.

    ``OO.S.F01`` -> {"0x0006": {"DF"}}. Unknown prefixes/bits are ignored (they
    cannot seed anything the engine knows about).
    """
    model = _model(version)
    prefix_map = _pics_to_cluster(version)
    seeds: dict[str, set[str]] = {}
    for code in codes:
        m = _FEATURE_CODE_RE.match(code)
        if not m:
            continue
        cid = prefix_map.get(m.group("pics"))
        if cid is None:
            continue
        bit = int(m.group("bit"), 16)
        for f in model.clusters[cid].features.values():
            if f.bit == bit and f.code:
                seeds.setdefault(cid, set()).add(f.code)
    return seeds


def _gateway_claims(version: str, profile: DeviceProfile, claims) -> dict[str, set[str]]:
    """{gateway code: spec-mandated codes for that claimed side}.

    Claiming ``OO.C`` means the device IS an On/Off client; the spec then
    dictates the commands every such client must send. Pure derivation from a
    user-stated fact -- never a guess.
    """
    from .generate.cluster_engine import (active_conditions, claim_cluster_side,
                                          load_transport_map)

    model = _model(version)
    prefix_map = _pics_to_cluster(version)
    known = known_item_numbers(version)
    conditions = active_conditions(profile, load_transport_map())
    # claimed features feed the claimed side too, so "X.S + X.S.F03" yields
    # everything mandatory under (claimed side + claimed features) -- the
    # conformance evaluator resolves the full AND/OR/NOT expressions.
    feature_seeds = _feature_seeds_from_codes(version, claims or [])
    out: dict[str, set[str]] = {}
    for code in claims or []:
        m = _GATEWAY_RE.match(code)
        if not m:
            continue
        cid = prefix_map.get(m.group("pics"))
        if cid is not None:
            out[code] = claim_cluster_side(
                model, cid, m.group("side"), conditions,
                seed_feature_codes=feature_seeds.get(cid, set())) & known
    return out


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
    profile = DeviceProfile.from_dict(profile_dict)
    extra_seeds = _feature_seeds_from_codes(version, claims or [])
    gateway_claims = _gateway_claims(version, profile, claims)

    # Real pipeline: clusters first, then MCORE seeded by the enabled cluster set.
    # TWO runs on purpose: the baseline (profile only) defines "Selected by the
    # tool"; whatever the user's claims add on top stays in Manual selection --
    # pre-filled Yes where the spec mandates it, but it is THEIR selection.
    baseline = generate_cluster_pics(model, profile)
    endpoints = generate_cluster_pics(model, profile, extra_feature_seeds=extra_seeds)
    baseline_pics = {ep.endpoint: ep.pics for ep in baseline}
    cluster_ids = all_enabled_cluster_ids(endpoints)
    mcore_on = compute_mcore_pics(profile, version, cluster_ids) & set(order)
    derived_im = is_im_client(model, [profile.device_type, *profile.node_device_types])
    im_client = derived_im if profile.im_client is None else profile.im_client
    # Does the composition MANDATE sending commands (client Tx)? If so -- and
    # only then -- IDM.C.InvokeRequest is spec-derivable, not a guess.
    mandated_client_tx = any(re.search(r"\.C\.C[0-9a-fA-F]{2}\.Tx$", c)
                             for ep in baseline for c in ep.pics)
    role_profile = load_role_profile(profile.role)
    facts = node_facts_from_clusters(cluster_ids)

    # Node composition (OTA requestor/provider, bridge) is asked via
    # node_device_types. When the profile does not declare it (phase-1 web UI
    # does not ask), items decided ONLY by that input are unknowable -- and
    # "no information" is never a "No".
    node_declared = bool(profile.node_device_types)
    gate_active = {"bridge": facts.has_bridge,
                   "ota_requestor": facts.has_ota_requestor,
                   "ota_provider": facts.has_ota_provider,
                   "icd": profile.is_icd}
    # Namespaces that describe the node composition. With no declaration, NO
    # item in them may be tool-decided -- not even through a Base.xml cond
    # whose premise is the unknown itself (OTA.VendorSpecific is "M if
    # commissionee AND NOT OTA.Requestor": a derivation built on a guess).
    _NODE_NS = ("MCORE.OTA.", "MCORE.BDX.", "MCORE.BRIDGE", "MCORE.DEVLIST.")

    def state(n: str, bucket: str) -> str:
        if not node_declared and n.startswith(_NODE_NS):
            return "review"
        if bucket == "auto":
            if n in mcore_on:
                return "on"
            if not node_declared and set(decided_dims.get(n, ())) == {"device_types"}:
                return "review"  # only the undeclared node composition decides it
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
                return "on"                       # the claimed/derived role atom
            if n == "MCORE.IDM.C.InvokeRequest" and mandated_client_tx:
                return "on"  # mandated client Tx commands ARE Invoke requests
            # per-message-type / per-datatype client capabilities (write Bool,
            # batch commands, subscribe events, ...): only the vendor knows.
            return "review"
        if role_denied(n, role_profile):
            # Contradicted by the chosen role: the tool CAN decide this --
            # e.g. commissioner-side scanning/CTRL questions are a defendable
            # No for a commissionee.
            return "off"
        area = gated_area(n, role_profile)
        if area and not gate_active[area]:
            # The feature area is off. That is a decision only when the user
            # actually declared the governing input; otherwise it is unknown.
            declared = node_declared if area != "icd" else False
            return "off" if declared else "review"
        # manual: a real product fact no input can derive (TCP, PAF, tamper
        # resistance, DLOG fields, ...). Never presented as tool-decided.
        return "review"

    def q_of(code: str) -> str:
        return text.get(code, ("", ""))[0] or code
    def conf_of(code: str) -> str:
        return text.get(code, ("", ""))[1] or "-"

    def row(code, tab, st, group, cluster, parent=None):
        # "needs_you" == the item is in the manual group: the tool could not
        # derive it, so it is the user's call. This holds uniformly for Base
        # product-facts AND optional cluster elements (default No, claim if you
        # implement them) -- so the "need your input" count reflects every
        # undecided question, not just the node-level ones.
        # "parent" is the gateway/feature this item reveals under.
        return {"tab": tab, "code": code, "question": q_of(code),
                "answer": "yes" if st == "on" else "no", "group": group,
                "cluster": cluster, "parent": parent,
                "needs_you": group == "manual", "conformance": conf_of(code)}

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
    known = known_item_numbers(version)
    items = [row(n, "base", state(n, bucket_of[n]),
                 "manual" if state(n, bucket_of[n]) == "review" else "decided",
                 _mcore_area(n))
             for n in order]
    tabs = [{"id": "base", "label": "Base PICS (MCORE)"}]
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        tab = str(ep.endpoint)
        label = (f"Root Node (endpoint {ep.endpoint})" if ep.endpoint == 0
                 else f"{ep.device_type_name} (endpoint {ep.endpoint})")
        tabs.append({"id": tab, "label": label})
        # "Selected by the tool" = the claim-free baseline run. Everything the
        # user's claims add (feature codes, gateway sides + their spec-mandated
        # elements) is pre-filled Yes but stays in Manual selection.
        tool_here = baseline_pics.get(ep.endpoint, set()) & known
        claim_here = (ep.pics & known) - tool_here
        for gateway, claim_codes in gateway_claims.items():
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
                items.append(row(code, tab, st, "manual", cluster, parent))

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
    profile = DeviceProfile.from_dict(profile_dict)
    by_tab = enabled_codes if isinstance(enabled_codes, dict) else None
    flat = ([c for codes in by_tab.values() for c in codes] if by_tab
            else list(enabled_codes))
    extra_seeds = _feature_seeds_from_codes(version, flat)
    endpoints = generate_cluster_pics(_model(version), profile,
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
    profile = DeviceProfile.from_dict(profile_dict)
    by_tab = enabled_codes if isinstance(enabled_codes, dict) else None
    flat = set(c for codes in by_tab.values() for c in codes) if by_tab \
        else set(enabled_codes)
    text = _item_text(version)
    known = known_item_numbers(version)
    problems: list[dict] = []
    flagged: set[str] = set()

    def add(code: str, why: str, severity: str = "error") -> None:
        if code in flagged:
            return
        flagged.add(code)
        problems.append({"code": code,
                         "question": text.get(code, ("", ""))[0] or code,
                         "why": why, "severity": severity})

    # 1) Engine side: re-run with the user's claims; everything the engine
    #    yields is mandatory for the claimed device.
    extra_seeds = _feature_seeds_from_codes(version, flat)
    endpoints = generate_cluster_pics(_model(version), profile,
                                      extra_feature_seeds=extra_seeds)
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        for code in sorted((ep.pics & known) - flat):
            add(code, f"mandatory on endpoint {ep.endpoint} for this device profile")

    # 2) Gateway claims: a claimed X.S / X.C mandates its side's elements.
    for gateway, claim_codes in _gateway_claims(version, profile, flat).items():
        for code in sorted(claim_codes - flat):
            add(code, f"mandatory because you claimed {gateway}")

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
                        cond_text = " ; ".join(c for _, c in it.statuses if c) or "unconditional"
                        add(it.number, f"required because: {cond_text}")
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
                    add(it.number, "PROHIBITED by the spec for this configuration")
                elif eff is None:
                    quirk = _KNOWN_TEMPLATE_QUIRKS.get(it.number)
                    add(it.number,
                        quirk or "enabled, but no status condition applies to "
                                 "this configuration (the validator will note it)",
                        severity="warning")
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
