# Base.xml (MCORE) — Input Coverage Analysis

Spec version: **1.6** · Source: maintained `pics_tool/templates/1.6/Base.xml`
(root element `generalPICS`). This document quantifies how many MCORE questions
Base.xml contains, how few inputs are needed to decide the maximum number of
them automatically, and which remaining questions must be handled manually.

## 1. What Base.xml contains

| Metric | Count |
|---|---|
| Total `picsItem` (MCORE questions) | **132** |
| `pixitItem` (test values) | 0 |
| Unconditionally mandatory (`M`, no cond) | **0** |
| Conditional (have a `cond` → auto-derivable) | **12** |
| Pure-optional leaves (device-fact flags) | **120** |

By namespace group:

| Group | Items | What it governs |
|---|---|---|
| `MCORE.IDM` | 38 | Interaction-model client/server capabilities & data types |
| `MCORE.DD` | 34 | Device discovery / onboarding (QR, manual PC, NFC, flows, TXT keys) |
| `MCORE.SC` | 17 | Secure-channel / mDNS discovery keys, TCP, SED/ICD |
| `MCORE.BDX` | 10 | Bulk data transfer roles (OTA image transfer) |
| `MCORE.COM` | 8 | Transport/radio (Wi-Fi bands, Thread, Ethernet, BLE, PAF) |
| `MCORE.OTA` | 7 | OTA requestor/provider sub-capabilities |
| `MCORE.BRIDGE` / `DEVLIST` / `BRIDGECLIENT` | 9 | Bridge & bridged-device management |
| `MCORE.ROLE` | 3 | Commissionee / Commissioner / Controller |
| `MCORE.DLOG` | 2 | Diagnostic-log fields |
| `MCORE.DT_SW_COMP`, `G`, `ACL`, `FS` | 4 | Misc node capabilities |

**Key finding:** MCORE is almost entirely a *device profile*, not spec-forced —
0 items are unconditionally mandatory, so nothing is enabled without input.

## 2. The derivation backbone (12 conditional items)

Only 12 items carry a `cond`; they cascade from a small set of **seed atoms**.
Setting the seeds auto-decides these via the cond fixpoint:

| Derived item | Becomes mandatory when… |
|---|---|
| `COM.WIFI` | `COM.WIFI_2P4GHZ` or `COM.WIFI_5GHZ` |
| `COM.WIRELESS` | `COM.WIFI` or `COM.THR` |
| `COM.PAF` | `COM.WIFI` and `DD.DISCOVERY_PAF` |
| `DD.QR` | `DD.CONCATENATED_QR_CODE` |
| `DD.STANDARD_COMM_FLOW` | `DD.11_MANUAL_PC` |
| `DD.DISCOVERY_BLE` | `ROLE.COMMISSIONER` and `COM.BLE` |
| `DD.DISCOVERY_IP` | `ROLE.COMMISSIONER` |
| `OTA.VendorSpecific` | `ROLE.COMMISSIONEE` and not `OTA.Requestor` |
| `BRIDGE.BatInfo` / `.OtherControl` / `.AllowDeviceRename` | `BRIDGE` |
| `DD.CTRL_CONCATENATED_QR_CODE_2` | not `DD.CTRL_CONCATENATED_QR_CODE_1` |

Seed roots (12): the `COM.*` bands + `BLE`, `ROLE.COMMISSIONEE/COMMISSIONER`,
`DD.CONCATENATED_QR_CODE`, `DD.11_MANUAL_PC`, `DD.DISCOVERY_PAF`,
`OTA.Requestor`, `BRIDGE`.

## 3. Minimum inputs and what they decide

The current tool takes **5 input dimensions** that seed Base.xml:

| Input | Values | Base atoms it sets | Also auto-derives |
|---|---|---|---|
| `transport` | wifi_2g / wifi_5g / thread / ethernet | `COM.WIFI_2P4GHZ/5GHZ`, `COM.THR`, `COM.ETH` | `COM.WIFI`, `COM.WIRELESS` |
| `ble_commissioning` | bool | `COM.BLE` | `DD.DISCOVERY_BLE` (if commissioner) |
| `role` | commissionee / commissioner / controller | `ROLE.*` | `DD.DISCOVERY_IP/BLE`, `OTA.VendorSpecific`; **gates 53 leaves off** |
| `onboarding` | qr / manual_pairing_code / nfc | `DD.QR`, `DD.MANUAL_PC`, `DD.11_MANUAL_PC`, `DD.NFC` | `DD.STANDARD_COMM_FLOW` |
| `ota` | requestor / provider | `OTA.Requestor`, `OTA.Provider` | `OTA.VendorSpecific`; gates BDX/provider |

Plus the deferred flags `is_bridge` / `is_icd` (feature-area gates).

### Coverage for a reference profile (commissionee, wifi_2g)

> **Policy note:** the earlier "maximum options" default (blanket-enabling
> role-appropriate optional leaves) was **dropped as over-claiming**. Optional
> leaves now stay OFF unless a profile input seeds them or a cond derivation
> forces them; the genuinely product-specific ones surface in the web UI as
> "awaiting your answer" (review) items.

| Category | Items | Meaning |
|---|---:|---|
| Enabled (input seeds + cond fixpoint) | 12 | transport/role/onboarding atoms and their derivations |
| Review ("awaiting your answer") | 39 | product facts only the engineer can confirm |
| Off (role-contradictory, gated, or safe-off) | 81 | commissioner/controller/IDM-client/bridge/provider/PAF leaves |
| **Total** | **132** | |

**So the 5 inputs + role gating decide 93 of 132 items deterministically**, and
the remaining 39 are surfaced for explicit review instead of being silently
defaulted — that is where manual judgement belongs.

## 4. The optional leaves — safe vs. needs-manual

Of the optional leaves, ~23 are safe for a standard commissionable node (the web
UI pre-answers them via review defaults), and ~33 are genuinely device-specific.

### 4a. Safe to default-ON (≈23) — standard for any Matter node
Discovery/advertising keys and IM-server basics that essentially every
commissionable device supports:
- `DD.TXT_KEY_VP/DT/DN/RI/PH/PI` (6)
- `DD.COMMISSIONING_SUBTYPE_V/T` (2)
- `SC.VP_KEY/DT_KEY/DN_KEY/RI_KEY/PH_KEY/PI_KEY` (6)
- `SC.SII_OP/SAI_OP/SAT_OP/T_KEY/SII_COMM/SAI_COMM` discovery keys (6)
- `SC.VENDOR_SUBTYPE/DEVTYPE_SUBTYPE` (2)
- `IDM.S` (device is a server) (1)

### 4b. Device-specific → should be inputs or manual review (≈33)
These vary per product and blanket-enabling risks over-claiming:

| Items | Why it needs a decision | Recommended handling |
|---|---|---|
| `BDX.*` (10) | Only relevant if the device does OTA / bulk transfer | Derive from `ota` (requestor ⇒ Receiver/Driver/…) instead of default-ON |
| `OTA.HTTPS / RequestorConsent / Resume / Retry` (4) | OTA requestor sub-features | Gate on `ota=requestor` + ask |
| `DD.CONCATENATED_QR_CODE`, `DD.DISCOVERY_PAF` (2) | **Seed-like**: default-ON forces `DD.QR` / `COM.PAF` mandatory | **Promote to inputs** (onboarding detail / `wifi_paf`) |
| `DD.CUSTOM_COMM_FLOW / USER_INTENT_COMM_FLOW / NON_CONCURRENT_CONNECTION` (3) | Commissioning flow varies | Add `commissioning_flow` input |
| `DD.NTL / UI / PHYSICAL_TAMPERING / CHIP_DEV / EXTENDED_DISCOVERY / ESF_TC_COMMISSIONER` (6) | Product/UX capabilities | Manual review (per-product) |
| `SC.TCP`, `SC.EXTENDED_DISCOVERY` (2) | Transport/discovery capabilities | Add `tcp` / `extended_discovery` inputs |
| `DLOG.S.UTCTIMESTAMP / TIMESINCEBOOT` (2) | Only if Diagnostic Logs cluster present | **Done:** gated on DLOG cluster presence (off when absent, review when present) |
| `IDM.S.LargeData / PersistentSubscription` (2) | Optional server capabilities | Add server-capability inputs |
| `DT_SW_COMP`, `G.MULTIENDPOINT` (2) | Composition-dependent | Derive from endpoint composition |

## 5. Recommendation

- **Minimum viable inputs (today): 5** (`transport`, `ble_commissioning`,
  `role`, `onboarding`, `ota`) + `is_bridge`/`is_icd`. These deterministically
  decide **73/132** items and, with the per-role default profile, produce a
  complete Base.xml.
- **To raise determinism with ~6 more optional inputs** (`wifi_paf`,
  `commissioning_flow`, `tcp`, `extended_discovery`, `diagnostic_logs`,
  OTA sub-caps + BDX-from-ota), coverage rises to roughly **~110/132**, leaving
  only ~6–10 truly product-specific flags for manual review.
- **Always manual (≈6–10):** `DD.PHYSICAL_TAMPERING`, `DD.UI`, `DD.NTL`,
  `DD.CHIP_DEV`, `DD.ESF_TC_COMMISSIONER`, `IDM.S.LargeData`,
  `IDM.S.PersistentSubscription` — these depend on product design and should be
  confirmed by the engineer, not inferred.
- **Seed-like leaves are no longer blanket-defaulted (fixed):** any leaf that
  another item's cond depends on (`DD.CONCATENATED_QR_CODE`, `DD.DISCOVERY_PAF`,
  `DD.CTRL_CONCATENATED_QR_CODE_1`) is now excluded from the "maximum options"
  default and is only set when a profile input seeds it. This prevents
  over-claiming — e.g. `COM.PAF` (Wi-Fi PAF) is no longer forced on just because
  the device is Wi-Fi. To enable them, add explicit inputs (e.g. `wifi_paf`).

### Cross-cluster note (not in Base.xml)
Network credentials and similar are **PIXIT** items and live in the per-cluster
templates (e.g. `PIXIT.CNET.WIFI_1ST_ACCESSPOINT_SSID`), not Base.xml. Base.xml
has **0 PIXIT** items. PIXIT values are always manual/test-bed-specific.
