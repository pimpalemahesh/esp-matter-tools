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
"""Split a user's optional-PICS *claims* into engine inputs.

A "claim" is a PICS code the user switched ON that carries spec consequences:
an optional feature (``OO.S.F01``), a cluster side (``OO.C`` / ``ACL.S``), or a
node-level MCORE atom (``MCORE.DD.NFC``). Turning those flat strings into the
three shapes the engines consume is the ONLY difference between what the web UI
can do and what the CLI can do -- so it lives here, taking a ``DataModel``, and
both consumers call it. Same claims + same model => same result, deterministically.
"""

from __future__ import annotations

import re

from esp_matter_datamodel.model.elements import DataModel

from .cluster_engine import claim_cluster_side
from .profile import DeviceProfile

# ``OO.S.F01`` -- an optional server feature bit (2 hex digits).
FEATURE_CODE_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.S\.F(?P<bit>[0-9a-fA-F]{2})$")
# ``OO.C`` / ``ACL.S`` -- a cluster role/side ("gateway") code.
GATEWAY_RE = re.compile(r"^(?P<pics>[A-Z0-9_]+)\.(?P<side>[SC])$")


def pics_to_cluster(model: DataModel) -> dict[str, str]:
    """{PICS prefix: cluster id} for every cluster in the data model."""
    return {c.pics: cid for cid, c in model.clusters.items() if c.pics}


def feature_seeds_from_codes(model: DataModel, codes) -> dict[str, set[str]]:
    """Turn optional feature PICS codes into engine feature seeds.

    ``OO.S.F01`` -> {"0x0006": {"DF"}}. Unknown prefixes/bits are ignored (they
    cannot seed anything the engine knows about).
    """
    prefix_map = pics_to_cluster(model)
    seeds: dict[str, set[str]] = {}
    for code in codes or []:
        m = FEATURE_CODE_RE.match(code)
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


def side_claims(
    model: DataModel, profile: DeviceProfile, codes, conditions, known: set[str]
) -> dict[str, set[str]]:
    """{gateway code: spec-mandated codes for that claimed side}.

    Claiming ``OO.C`` means the device IS an On/Off client; the spec then dictates
    the commands every such client must send. Pure derivation from a user-stated
    fact -- never a guess. Claimed features feed the claimed side too, so
    ``X.S + X.S.F03`` yields everything mandatory under (side AND features).
    """
    prefix_map = pics_to_cluster(model)
    feature_seeds = feature_seeds_from_codes(model, codes or [])
    out: dict[str, set[str]] = {}
    for code in codes or []:
        m = GATEWAY_RE.match(code)
        if not m:
            continue
        cid = prefix_map.get(m.group("pics"))
        if cid is not None:
            out[code] = (
                claim_cluster_side(
                    model,
                    cid,
                    m.group("side"),
                    conditions,
                    seed_feature_codes=feature_seeds.get(cid, set()),
                )
                & known
            )
    return out


# The DD and SC test plans each carry an item for the SAME DNS-SD fact: the
# optional TXT keys and commissioning subtypes of Commissionable Node
# Discovery. One user decision answers BOTH codes -- claiming either side
# claims the pair, so every consumer (web UI, MCP, CLI) exports the two test
# plans consistently.
MCORE_MIRRORS = {
    "MCORE.DD.TXT_KEY_VP": "MCORE.SC.VP_KEY",
    "MCORE.DD.TXT_KEY_DT": "MCORE.SC.DT_KEY",
    "MCORE.DD.TXT_KEY_DN": "MCORE.SC.DN_KEY",
    "MCORE.DD.TXT_KEY_RI": "MCORE.SC.RI_KEY",
    "MCORE.DD.TXT_KEY_PH": "MCORE.SC.PH_KEY",
    "MCORE.DD.TXT_KEY_PI": "MCORE.SC.PI_KEY",
    "MCORE.DD.COMMISSIONING_SUBTYPE_V": "MCORE.SC.VENDOR_SUBTYPE",
    "MCORE.DD.COMMISSIONING_SUBTYPE_T": "MCORE.SC.DEVTYPE_SUBTYPE",
}
_MIRROR_BACK = {v: k for k, v in MCORE_MIRRORS.items()}


def expand_mirrors(codes) -> set[str]:
    """``codes`` plus the mirror twin of every mirrored member (both directions)."""
    out = set(codes or [])
    for c in list(out):
        twin = MCORE_MIRRORS.get(c) or _MIRROR_BACK.get(c)
        if twin:
            out.add(twin)
    return out


def mcore_atoms(codes) -> set[str]:
    """The node-level Base/MCORE atoms among ``codes`` (re-enter the cond
    fixpoint), with mirrored DNS-SD twins expanded."""
    return expand_mirrors(c for c in (codes or []) if c.startswith("MCORE."))


# ICD Management (cluster 0x0046, PICS prefix ICDM): on the Root Node the spec
# lists it "Mandatory if (SIT | LIT)", so claiming the cluster IS declaring
# "this node is an ICD" -- no separate input needed. Its LongIdleTimeSupport
# feature (bit 2) settles the flavor: claimed -> LIT, otherwise SIT (an ICD
# without LITS operates as a Short Idle Time ICD by definition).
_ICDM_GATEWAY = "ICDM.S"
_ICDM_LITS = "ICDM.S.F02"


def icd_from_claims(codes) -> tuple[bool, str | None]:
    """(is_icd, icd_mode) declared by an ICD Management claim, if any.

    Returns ``(False, None)`` when ``codes`` carry no ICDM server claim; the
    caller merges this with any explicit ``is_icd`` profile input (an explicit
    input wins -- the claim only ever ADDS the ICD declaration).
    """
    codes = set(codes or [])
    if _ICDM_GATEWAY not in codes:
        return False, None
    return True, ("lit" if _ICDM_LITS in codes else "sit")
