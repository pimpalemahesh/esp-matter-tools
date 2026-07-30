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
from fnmatch import fnmatch
from functools import lru_cache

from esp_matter_datamodel import boolexpr, loader

from .generate.cluster_engine import all_enabled_cluster_ids, generate_cluster_pics
from .generate.mcore_engine import compute_mcore_pics
from .generate.profile import DeviceProfile
from .generate.template_io import base_template_path, parse_pics_items

# Manual items that are *safe off* for a normal accessory: commissioner-side,
# bridge, PAF and diagnostics flags a role/bridge input would decide later.
# (Not "you decide" to-dos -- they just stay off.)
_WIRE = [
    "MCORE.DD.COMM_DISCOVERY", "MCORE.DD.CTRL_*", "MCORE.DD.*MANUAL_PC*",
    "MCORE.DD.SCAN_*", "MCORE.DD.QR_COMMISSIONING", "MCORE.ACL.Administrator",
    "MCORE.BRIDGE*", "MCORE.BRIDGECLIENT", "MCORE.DEVLIST.*", "MCORE.BDX.Async*",
    "MCORE.FS", "MCORE.SC.TCP", "*.EXTENDED_DISCOVERY", "MCORE.DD.DISCOVERY_PAF",
    "MCORE.COM.PAF", "MCORE.DD.CONCATENATED_QR_CODE",
]


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

    Returns (bucket_of, decided_dims): bucket_of[item] in
    {auto, imrole, manualwire, manualkeep}; decided_dims[item] = set of inputs.
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
        elif n in manual:
            bucket_of[n] = "manualwire" if any(fnmatch(n, p) for p in _WIRE) else "manualkeep"
        else:
            bucket_of[n] = "auto"
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


def list_device_types(version: str = "1.6") -> list[str]:
    """Sorted application/node device-type names for the picker."""
    return sorted({dt.name for dt in _model(version).device_types.values()})


_FEATURE_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.F(?P<bit>[0-9a-fA-F]{2})$")


@lru_cache(maxsize=4)
def _pics_to_cluster(version: str) -> dict[str, str]:
    """{PICS prefix: cluster id} for every cluster in the data model."""
    return {c.pics: cid for cid, c in _model(version).clusters.items() if c.pics}


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


def generate_payload(profile_dict: dict, enabled_features=None) -> dict:
    """Run the engines for a profile and return every question, plainly answered.

    Each item is a question a human answers: ``question`` (plain English),
    ``answer`` (yes/no the tool pre-filled), ``needs_you`` (the tool couldn't
    know -- your call). Technical fields (PICS code, conformance) travel along
    for an optional detail view, but the question leads.

    ``enabled_features`` (optional) is a list of feature PICS codes the user
    switched ON; they re-enter the engine as feature seeds, so everything those
    features make mandatory is answered "yes" consistently.
    """
    version = profile_dict.get("spec_version", "1.6")
    order = _mcore_meta(version)[0]
    bucket_of, _ = _classify(version)
    text = _item_text(version)
    model = _model(version)
    profile = DeviceProfile.from_dict(profile_dict)
    extra_seeds = _feature_seeds_from_codes(version, enabled_features or [])

    # Real pipeline: clusters first, then MCORE seeded by the enabled cluster set.
    endpoints = generate_cluster_pics(model, profile, extra_feature_seeds=extra_seeds)
    cluster_ids = all_enabled_cluster_ids(endpoints)
    mcore_on = compute_mcore_pics(profile, version, cluster_ids) & set(order)
    im_client = is_im_client(model, [profile.device_type, *profile.node_device_types])

    def state(n: str, bucket: str) -> str:
        if bucket == "auto":
            return "on" if n in mcore_on else "off"
        if bucket == "imrole":
            if n.startswith("MCORE.IDM.S"):
                return "on"                       # DUT hosts clusters -> IM server
            return "on" if im_client else "off"   # IM client only if derived
        if bucket == "manualwire":
            return "off"                          # safe default for an accessory
        if n.startswith("MCORE.DLOG."):
            # Diagnostic-log fields only exist if the node hosts the Diagnostic
            # Logs cluster; without it they are decisively OFF, not "your call".
            return "review" if "0x0032" in cluster_ids else "off"
        return "review"                           # manualkeep: real product fact

    def q_of(code: str) -> str:
        return text.get(code, ("", ""))[0] or code
    def conf_of(code: str) -> str:
        return text.get(code, ("", ""))[1] or "-"

    def row(code, tab, st):
        return {"tab": tab, "code": code, "question": q_of(code),
                "answer": "yes" if st == "on" else "no",
                "needs_you": st == "review", "conformance": conf_of(code)}

    # Three distinct sections, shown as separate tabs: the node-level Base.xml
    # (MCORE) questions, the Root Node cluster PICS on endpoint 0 (Basic Info,
    # ACL, CNET, ...), and each application endpoint's cluster PICS. All are
    # exportable -- a PICS package without any one of them is invalid.
    items = [row(n, "base", state(n, bucket_of[n])) for n in order]
    tabs = [{"id": "base", "label": "Base PICS (MCORE)"}]
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        tab = str(ep.endpoint)
        label = (f"Root Node (endpoint {ep.endpoint})" if ep.endpoint == 0
                 else f"{ep.device_type_name} (endpoint {ep.endpoint})")
        tabs.append({"id": tab, "label": label})
        for code in sorted(ep.pics):
            items.append(row(code, tab, "on"))

    counts = {"yes": 0, "no": 0, "needs_you": 0}
    for it in items:
        counts["yes" if it["answer"] == "yes" else "no"] += 1
        counts["needs_you"] += it["needs_you"]

    return {
        "spec_version": version,
        "device_type": profile.device_type,
        "im_role": "IM client + server" if im_client else "IM server only",
        "im_client": im_client,
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
    what you export). MCORE codes go to endpoint 0; every cluster code goes to
    the endpoint that actually hosts that cluster in the generated layout, so
    the Root Node cluster PICS (ACL, Basic Info, CNET, ...) land on endpoint 0
    and the application clusters on the app endpoint.
    """
    import os
    import tempfile

    from .generate.writer import write_pics

    version = profile_dict.get("spec_version", "1.6")
    profile = DeviceProfile.from_dict(profile_dict)
    extra_seeds = _feature_seeds_from_codes(version, enabled_codes)
    endpoints = generate_cluster_pics(_model(version), profile,
                                      extra_feature_seeds=extra_seeds)
    app_ep = next((e.endpoint for e in endpoints if e.endpoint != 0), 1)

    # Per-endpoint code sets from the generated layout: a code belongs to every
    # endpoint whose generated PICS contains it; a user-added code (not generated
    # anywhere) is routed by its cluster prefix, falling back to the app endpoint.
    prefix_ep = _endpoint_of_prefix(endpoints, version)
    generated = {ep.endpoint: ep.pics for ep in endpoints}
    by_ep: dict[int, set] = defaultdict(set)
    for code in enabled_codes:
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


def validate_selection(profile_dict: dict, enabled_codes) -> list[dict]:
    """Spec-consistency check of the user's final Yes set before export.

    Returns the list of codes that the spec makes MANDATORY given what the user
    claims (profile + enabled features + enabled items) but that are answered
    "no". Empty list == consistent. Each problem: {code, question, why}.
    """
    version = profile_dict.get("spec_version", "1.6")
    profile = DeviceProfile.from_dict(profile_dict)
    enabled = set(enabled_codes)
    text = _item_text(version)
    problems: list[dict] = []

    def add(code: str, why: str) -> None:
        problems.append({"code": code,
                         "question": text.get(code, ("", ""))[0] or code,
                         "why": why})

    # Cluster side: re-run the engine with the user's enabled features as seeds;
    # everything it yields is mandatory for the claimed device, so any of it
    # answered "no" is a conformance hole.
    extra_seeds = _feature_seeds_from_codes(version, enabled)
    endpoints = generate_cluster_pics(_model(version), profile,
                                      extra_feature_seeds=extra_seeds)
    for ep in sorted(endpoints, key=lambda e: e.endpoint):
        for code in sorted(ep.pics - enabled):
            add(code, f"mandatory on endpoint {ep.endpoint} for this device profile")

    # MCORE side: any Base.xml item whose cond evaluates to Mandatory against
    # the user's enabled set must itself be enabled.
    resolve = lambda atom: atom in enabled  # noqa: E731
    for item in parse_pics_items(base_template_path(version)):
        if item.number in enabled:
            continue
        for status_text, cond in item.statuses:
            if status_text != "M" or not cond:
                continue
            try:
                if boolexpr.evaluate(boolexpr.parse(cond), resolve):
                    add(item.number, f"required because: {cond}")
                    break
            except boolexpr.ExpressionSyntaxError:
                continue
    return problems


# --- JSON string wrappers (Pyodide-friendly: no proxy juggling in JS) --------

def generate_payload_json(profile_json: str, enabled_features_json: str = "[]") -> str:
    return json.dumps(generate_payload(json.loads(profile_json),
                                       json.loads(enabled_features_json)))


def list_device_types_json(version: str = "1.6") -> str:
    return json.dumps(list_device_types(version))


def export_pics_files_json(profile_json: str, enabled_json: str = "[]") -> str:
    return json.dumps(export_pics_files(json.loads(profile_json), json.loads(enabled_json)))


def validate_selection_json(profile_json: str, enabled_json: str = "[]") -> str:
    return json.dumps(validate_selection(json.loads(profile_json), json.loads(enabled_json)))
