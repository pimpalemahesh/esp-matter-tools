# pics_tool

An **offline generator for Matter PICS** (Protocol Implementation Conformance
Statement) files. Given a spec version, an application device type, and a small
device profile, it produces per-endpoint PICS XML with the appropriate items
enabled — **no live device required**.

It is a consumer of the shared [`esp-matter-datamodel`](../esp-matter-datamodel)
standard; it owns all PICS-specific logic while that package stays PICS-neutral.

## How it works

- **Cluster PICS** are derived from the data-model conformance: the device type
  is expanded into its mandatory clusters, and within each, a feature-mask
  fixpoint + the conformance evaluator decide which
  features/attributes/commands/events are mandatory for the chosen profile.
  Device types that mandate *client* clusters (e.g. Dimmer Switch, OTA
  Requestor) also get the client-side codes (`OO.C`, `OO.C.Cxx.Tx`, ...).
  Optional features a user switches on (web UI) re-enter the engine as seeds,
  so everything they make mandatory is enabled consistently.
- **MCORE / node-level PICS** come from the maintained `Base.xml` template: the
  profile seeds a few atoms (transport, role, onboarding, OTA), then a fixpoint
  over the `cond` expressions enables everything those atoms make mandatory.
  Optional leaves are never blanket-enabled; the genuinely product-specific
  ones are flagged for explicit review in the web UI.
- The **writer** annotates the maintained CSA templates in place (only
  `<support>` changes; comments/structure preserved) and writes one folder per
  endpoint (`endpoint0` = Root Node + Base/MCORE, `endpoint1` = the app device
  type).
- The **web UI** additionally validates the final selection before export: any
  item the spec makes mandatory given your answers but that is switched off is
  flagged (with a one-click fix). Answers persist in the browser across reloads.

## Setup

Nothing is pip-installed — like `dm_diff_tool`, the tool runs straight from the
repo checkout (`esp_matter_datamodel` is picked up from the sibling
`esp-matter-datamodel/` directory automatically). Only the third-party
dependencies are needed:

```bash
pip install -r requirements.txt
```

## Usage

From the `pics_tool` directory, with a profile file:

```bash
python3 cli.py gen-pics --profile device-profile.yaml -o pics_out
```

Or entirely via flags (overrides win over the profile file):

```bash
python3 cli.py gen-pics \
    --spec-version 1.6 --device-type "On/Off Light" \
    --transport wifi_2g --role commissionee -o pics_out
```

Example `device-profile.yaml`:

```yaml
spec_version: "1.6"
device_type: "On/Off Light"           # the application device type (endpoint 1)
transport: [wifi_2g]                  # any of: wifi_2g, wifi_5g, thread, ethernet
ble_commissioning: true               # default: true unless ethernet-only
role: commissionee                    # commissionee | commissioner | controller
onboarding: [qr, manual_pairing_code]
node_device_types: []                 # extra node-level device types, e.g. ["OTA Requestor"]
```

**OTA and bridge are derived, not asked.** Instead of `ota`/`is_bridge` flags,
list the device types the node implements in `node_device_types` (e.g.
`"OTA Requestor"`, `"OTA Provider"`, `"Aggregator"`). Their clusters then drive
both the cluster PICS and the node-level `MCORE.OTA.*` / `MCORE.BRIDGE.*` (and the
BDX roles) from a single source of truth. ICD/SIT-LIT is deferred (feature-dependent).

## Output

```
pics_out/
  endpoint0/   Base.xml + Root Node cluster PICS (Basic Info, ACL, CNET, ...)
  endpoint1/   application device-type cluster PICS (On/Off, Identify, ...)
```

Each file is the maintained template with `<support>` set to `true` for the
enabled items.

## CSA PICS Validator notes

The generated set validates with **0 errors** in the official CSA PICS tool.
Expect a handful of *warnings*, which are by design:

- **Unfilled PIXITs** (network SSIDs/credentials, fail-safe timings, product
  color/finish, ACE app-endpoint ids): these are test-bed/product values that
  cannot be generated. The export includes a `PIXIT_CHECKLIST.md` listing every
  applicable PIXIT — fill them in the CSA tool before running the Test Harness.
- **`MCORE.DD.STANDARD_COMM_FLOW`** on a commissionee: Base.xml only defines
  "M if `MCORE.DD.11_MANUAL_PC`" (a commissioner-side item) with no plain `O`
  status, so claiming the standard flow on a commissionee trips a "selected but
  not applicable" warning. It is claimed deliberately — DD test selection keys
  off it.
- **"Dependency item could not be found … evaluated as false: `X.C`"** (e.g.
  `CC.C`): the exported file does contain the `X.C` item (`support=false`) in
  the same file as the conditions referencing it — the validator just fails to
  index unclaimed client-role items. Benign whenever the client role really is
  unsupported: "evaluated as false" equals its actual value, so every dependent
  condition resolves correctly. Only if you claim `X.C = Yes` should you
  double-check its client items in the CSA tool after upload.

## Configuration data

- `pics_tool/transport_map.yaml` — transport → data-model conditions + seeded
  cluster features (e.g. Network Commissioning WI/TH/ET).
- `pics_tool/profiles/<role>.yaml` — per-role MCORE default capability set
  (seeds, deny list, feature-area gates).
- `pics_tool/templates/<version>/` — the maintained CSA PICS templates.

## Development

```bash
pip install -r requirements.txt pytest
python3 -m pytest    # no install needed; conftest.py wires up the in-repo packages
# regenerate golden snapshots after an intended output change:
python3 tools/update_golden.py
```
