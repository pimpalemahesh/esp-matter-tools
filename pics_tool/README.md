# pics_tool

An **offline generator for Matter PICS** (Protocol Implementation Conformance
Statement) files. Given a spec version, an application device type, and a small
device profile, it produces per-endpoint PICS XML with the appropriate items
enabled — **no live device required**.

It is built on the [`esp-matter-datamodel`](./esp-matter-datamodel) package —
a PICS-neutral, versioned representation of the Matter data model. That package
is vendored inside this tool (`pics_tool/esp-matter-datamodel/`) for now but kept
self-contained, so it can be split back out into its own tool later; pics_tool
owns all PICS-specific logic.

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

The tool runs straight from the repo checkout — no pip install of the packages
themselves (`esp_matter_datamodel` is picked up from the bundled
`esp-matter-datamodel/` directory automatically). Two steps:

```bash
# 1. third-party dependencies
pip install -r requirements.txt

# 2. build the per-version data models ONCE (derived from connectedhomeip's
#    data_model/ and NOT tracked in git). Run this before the first pytest /
#    serve.py / gen-pics. It clones connectedhomeip (shallow, data_model only)
#    or reuses an existing checkout, then generates datamodel_<version>.json.
./build_tool.sh
#    …or point it at a checkout you already have:
MATTER_SDK_PATH=/path/to/connectedhomeip ./build_tool.sh
```

`build_tool.sh` is idempotent — once the JSONs exist it regenerates nothing and
needs no checkout. The **PICS templates** (`pics_tool/templates/<version>/`) are
committed in the repo; only the derived data-model JSONs are generated.

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

## Selection document (multiple endpoints + optional claims)

For products with **more than one application endpoint**, or to **enable optional
things** (features, cluster sides, MCORE items) from the CLI the same way the web
UI does, pass a canonical **selection** document with `--selection`. It is the
single source of truth both the CLI and (later) the UI drive, so identical input
gives identical output, deterministically.

```bash
python3 cli.py gen-pics --selection selection.yaml -o pics_out
python3 cli.py gen-scaffold --selection selection.yaml
```

```yaml
# selection.yaml
spec_version: "1.6"
role: commissionee
transport: [wifi_2g]
mcore_claims: ["MCORE.DD.NFC"]          # optional node-level (endpoint 0) atoms
endpoints:                              # application endpoints, EP1..EPN in order
  - device_types: ["Extended Color Light"]
    claims: ["OO.S.F02"]                # optional PICS codes enabled ON THIS endpoint
  - device_types: ["On/Off Light", "Occupancy Sensor"]   # composed device types on one EP
```

- Each endpoint has a **list** of device types (composed device types) and its own
  optional **claims**. A claim is a PICS code the product supports: a feature
  (`OO.S.F02`), a cluster side (`OO.C`), or an `MCORE.*` atom. Claims scope
  per-endpoint, so a claim on EP1 never leaks to the same cluster on EP2.
- The plain `--profile` / flag form is the single-endpoint shorthand (a top-level
  `device_type` == one application endpoint on EP1).

## Output

```
pics_out/
  endpoint0/   Base.xml + Root Node cluster PICS (Basic Info, ACL, CNET, ...)
  endpoint1/   application device-type cluster PICS (On/Off, Identify, ...)
  endpoint2/   ... one folder per application endpoint (selection document)
```

Each file is the maintained template with `<support>` set to `true` for the
enabled items.

## Generate the esp-matter data-model code

`gen-scaffold` takes the same profile inputs as `gen-pics` and prints the
esp-matter **data-model construction code** for that selection — the
`node::create` / `endpoint::<device_type>::create` block a developer would
otherwise hand-write in `app_main.cpp`. It is derived from the PICS, since the
device type / clusters / features were already chosen when the PICS was
generated. Paste it straight into `app_main()`.

```bash
python3 cli.py gen-scaffold \
    --spec-version 1.6 --device-type "Extended Color Light" \
    --transport wifi_2g --role commissionee
```

prints (comment-free, paste-ready):

```cpp
    node::config_t node_config;
    node_t *node = node::create(&node_config, app_attribute_update_cb, app_identification_cb);
    ABORT_APP_ON_FAILURE(node != nullptr, ESP_LOGE(TAG, "Failed to create Matter node"));

    extended_color_light::config_t extended_color_light_config_1;
    endpoint_t *endpoint_1 = extended_color_light::create(node, &extended_color_light_config_1, ENDPOINT_FLAG_NONE, nullptr);
    ABORT_APP_ON_FAILURE(endpoint_1 != nullptr, ESP_LOGE(TAG, "Failed to create Extended Color Light endpoint"));
```

With `--selection` it emits **one `endpoint::<type>::create` per application
endpoint**, adds composed device types with `endpoint::<type>::add(...)`, and
turns optional feature / attribute / command / event / cluster-side claims into
explicit `cluster::<x>::feature::<y>::add(...)` / `attribute::create_<z>(...)` /
`command::create_<z>(...)` / `cluster::<x>::create(..., CLUSTER_FLAG_*)` calls.

**Exact vs. placeholder arguments.** The exact call arguments (does a feature's
`add()` take a config? what type is an attribute's value?) come from a *capability
map* of the esp_matter component that the tool ships per version
(`codegen/targets/esp_matter/data/caps_<ver>.json`, parsed from the released
component). When a version has a bundled map (1.4, 1.4.2, 1.5, 1.5.1), the code is
**ready to compile** — config features declare their `config_t`, no-config
features take none, attributes get a type-correct default value. A version with no
released component (1.6, 1.4.1) uses the **nearest** lower version's map, so it is
still ready to compile (only an element genuinely new to that version falls back
to a `/* ... */` placeholder argument). The generated code carries **no comments**.
To get exact code for any version (including `main` / a fork), point at your own
component:

```bash
python3 cli.py gen-scaffold --spec-version 1.6 --device-type "Extended Color Light" \
    --esp-matter-path $ESP_MATTER_PATH        # parse the live component's data_model/
```

Drivers, callbacks, and attribute *values* stay hand-written (PICS declares which
elements exist, not their values; the endpoint's private-data arg is emitted as
`nullptr` -- pass your driver handle there).
Options:

- `-o/--output` — optional: also write the snippet to `<dir>/app_data_model.cpp`.
- `--pics-output` — where the intermediate PICS XML is written (default: `pics_out`).
- `--esp-matter-path` — generate exact code against a local esp_matter component
  instead of the bundled capability map.

No esp-matter checkout is needed to generate (the bundled capability map supplies
the signatures); the code depends on esp-matter only at compile time.
Multi-endpoint and composed device types are supported via `--selection`.

**Maintainer:** refresh a bundled capability map when esp_matter ships a version:
`python3 cli.py refresh-esp-matter-knowledge --version 1.5.1 --download`.

## CSA PICS Validator notes

The generated set validates with **0 errors** in the official CSA PICS tool.
Expect a handful of *warnings*, which are by design:

- **Unfilled PIXITs** (network SSIDs/credentials, fail-safe timings, product
  color/finish, ACE app-endpoint ids): these are test-bed/product values that
  cannot be generated. The export includes a `PIXIT_CHECKLIST.md` listing every
  applicable PIXIT — fill them in the CSA tool before running the Test Harness.
  PIXITs whose condition is false for the endpoint (e.g. `PIXIT.OO.*` in a
  client-only On/Off file, Thread PIXITs on a Wi-Fi device) are exported as
  `support=n/a`, so the validator treats them as not applicable.
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
./build_tool.sh      # generate the data models first (see Setup); tests skip without them
python3 -m pytest    # conftest.py wires up the in-repo packages
# regenerate golden snapshots after an intended output change:
python3 tools/update_golden.py
```
