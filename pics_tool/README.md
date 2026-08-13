# pics_tool

An **offline generator for Matter PICS** (Protocol Implementation Conformance
Statement) files. Given a spec version, the application device type(s), and a
small device profile, it produces per-endpoint PICS XML with the appropriate
items enabled — **no live device required** — plus the matching esp-matter
data-model construction code.

Three interfaces drive the same engine, so identical input yields identical
output everywhere:

| Interface | For | Entry point |
|---|---|---|
| **Web UI** | product owners / certification engineers | `./build_tool.sh --serve` |
| **CLI** | developers, CI | `python3 cli.py` |
| **MCP server** | LLMs / agents | `python3 mcp_server.py` |

It is built on the [`esp-matter-datamodel`](./esp-matter-datamodel) package — a
PICS-neutral, versioned representation of the Matter data model. That package is
vendored inside this tool (`esp-matter-datamodel/`) but kept self-contained;
pics_tool owns all PICS-specific logic.

## How it works

- **Cluster PICS** are derived from the data-model conformance: each device type
  is expanded into its mandatory clusters, and within each, a feature-mask
  fixpoint + the conformance evaluator decide which
  features/attributes/commands/events are mandatory for the chosen profile.
  Device types that mandate *client* clusters (e.g. Dimmer Switch, OTA
  Requestor) also get the client-side codes (`OO.C`, `OO.C.Cxx.Tx`, ...).
- **Optional capabilities are claims.** A claim is a PICS code the product
  supports — an optional feature (`OO.S.F02`), a cluster side (`DLOG.S`), or an
  `MCORE.*` atom. Claims re-enter the engine as seeds, so everything a claim
  makes mandatory is enabled consistently, and a claim can reveal further
  optional choices (progressive disclosure).
- **MCORE / node-level PICS** come from the maintained `Base.xml` template: the
  profile seeds atoms (transport, role, onboarding, OTA), then a fixpoint over
  the `cond` expressions enables everything those atoms make mandatory.
  Optional leaves are never blanket-enabled; the genuinely product-specific
  ones are surfaced as questions. Product facts the composition itself answers
  are derived, not asked — e.g. `MCORE.G.MULTIENDPOINT` (two endpoints with a
  Groups server) or the ICD answers (declared by claiming the ICD Management
  cluster on the Root Node; its `LITS` feature settles SIT vs LIT). Duplicate
  questions the DD and SC test plans both carry (DNS-SD TXT keys, commissioning
  subtypes) are asked once and exported to both files consistently.
- The **writer** annotates the maintained CSA templates in place (only
  `<support>` changes; comments/structure preserved) and writes one folder per
  endpoint (`endpoint0` = Root Node + Base/MCORE, `endpoint1..N` = the
  application endpoints).
- A **validator** checks the final selection against the spec's dependency
  rules before export; any item your answers make mandatory but that is
  switched off is flagged (with a one-click fix in the web UI).

## Setup

The tool runs straight from the repo checkout — no pip install of the packages
themselves (`esp_matter_datamodel` is picked up from the vendored
`esp-matter-datamodel/` directory automatically). The PICS templates and the
per-version data-model JSONs are committed, so this is the whole setup:

```bash
pip install -r requirements.txt
```

## Web UI

```bash
./build_tool.sh --serve        # build the Pyodide bundle, serve on :8000
```

Everything runs client-side in the browser (Pyodide) — no backend, no device
data leaves the page. The flow is a four-step wizard:

1. **Describe device** — spec version, application endpoints (one device type
   each, composable), transport, commissioning discovery, onboarding, OTA.
2. **Design data model** — one row per cluster per endpoint, ZAP-style:
   required clusters are pre-included, spec-optional clusters get an Include
   switch, and each cluster opens a dialog of labelled toggles for its
   optional features/attributes/commands. Everything derivable is answered
   automatically and shown read-only.
3. **Device questions** — the remaining node-wide product facts, condensed:
   parallel families (client attribute data types, DNS-SD TXT keys) fold into
   single multi-select questions.
4. **Export** — a review of your answers, the spec-check, a ZIP with one folder
   per endpoint ready for the CSA PICS tool, and the esp-matter data-model
   code to paste into `app_main.cpp`.

A **Simple/Advanced** switch on steps 2–3 toggles between the condensed view
and the complete raw PICS item list (every question, PICS codes, conformance).
Answers persist in the browser across reloads.

## CLI

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

**OTA, bridge, and ICD are derived, not asked.** List the device types the node
implements in `node_device_types` (e.g. `"OTA Requestor"`, `"OTA Provider"`,
`"Aggregator"`); their clusters drive the cluster PICS and the node-level
`MCORE.OTA.*` / `MCORE.BRIDGE.*` / BDX roles from a single source of truth.
Declaring the node an ICD works the same way: claim the ICD Management cluster
(`ICDM.S`) on the Root Node — with its `LongIdleTimeSupport` feature for a LIT
ICD, without it for SIT. An explicit `is_icd` / `icd_mode` profile input is
also accepted and wins over the claim.

### Selection document (multiple endpoints + optional claims)

For products with **more than one application endpoint**, or to **enable
optional capabilities** from the CLI the same way the web UI does, pass a
canonical **selection** document with `--selection`:

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

- Each endpoint has a **list** of device types (composed device types) and its
  own optional **claims**. Claims scope per-endpoint, so a claim on EP1 never
  leaks to the same cluster on EP2.
- The plain `--profile` / flag form is the single-endpoint shorthand (a
  top-level `device_type` == one application endpoint on EP1).

### Output

```
pics_out/
  endpoint0/   Base.xml + Root Node cluster PICS (Basic Info, ACL, CNET, ...)
  endpoint1/   application device-type cluster PICS (On/Off, Identify, ...)
  endpoint2/   ... one folder per application endpoint (selection document)
```

Each file is the maintained template with `<support>` set to `true` for the
enabled items.

## Generate the esp-matter data-model code

`gen-scaffold` takes the same inputs as `gen-pics` and prints the esp-matter
**data-model construction code** for that selection — the `node::create` /
`endpoint::<device_type>::create` block a developer would otherwise hand-write
in `app_main.cpp`:

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

**Exact vs. placeholder arguments.** The exact call arguments come from a
*capability map* of the esp_matter component that the tool ships per version
(`codegen/targets/esp_matter/data/caps_<ver>.json`, parsed from the released
component). When a version has a bundled map (1.4, 1.4.2, 1.5, 1.5.1), the code
is **ready to compile**. A version with no released component (1.6, 1.4.1) uses
the **nearest** lower version's map (only an element genuinely new to that
version falls back to a `/* ... */` placeholder argument). To get exact code
for any version, point at your own component:

```bash
python3 cli.py gen-scaffold --spec-version 1.6 --device-type "Extended Color Light" \
    --esp-matter-path $ESP_MATTER_PATH        # parse the live component's data_model/
```

Drivers, callbacks, and attribute *values* stay hand-written (PICS declares
which elements exist, not their values; the endpoint's private-data arg is
emitted as `nullptr` — pass your driver handle there). Options:

- `-o/--output` — optional: also write the snippet to `<dir>/app_data_model.cpp`.
- `--pics-output` — where the intermediate PICS XML is written (default: `pics_out`).
- `--esp-matter-path` — generate exact code against a local esp_matter component
  instead of the bundled capability map.

**Maintainer:** refresh a bundled capability map when esp_matter ships a
version: `python3 cli.py refresh-esp-matter-knowledge --version 1.5.1 --download`.

## MCP server (for LLMs / agents)

```bash
pip install -r requirements-mcp.txt
python3 mcp_server.py                  # stdio transport
```

Two tools, mirroring the web UI's flow:

1. **`generate_baseline(selection)`** — the device description in, the complete
   mandatory result out: PICS XML files + esp-matter code + the list of open
   optional choices (grouped endpoint → cluster, each with its PICS code, a
   human label, and a priority). Independent and complete — for a
   mandatory-only package this one call is the whole job. Discovery is built
   in: calling with missing/unknown inputs returns the valid spec versions or
   device-type names instead of erroring.
2. **`apply_selections(selection, selected)`** — after the *human* has answered
   the optional choices, feed their YES codes back
   (`{"1": ["CC.S.F00"], "base": ["MCORE.DD.TXT_KEY_VP"]}`); returns the final
   PICS + code with every claim and its spec consequences applied. Unknown
   codes are skipped and reported (`ignored_unknown_codes`), and the response
   notes when claims revealed new choices worth another round.

The tool docstrings instruct the model to put primary choices (optional
clusters and features) to the human rather than deciding product facts itself.

Example client registration (Claude Desktop / Claude Code):

```json
{ "mcpServers": { "esp-matter-pics": {
    "command": "python3", "args": ["/path/to/pics_tool/mcp_server.py"] } } }
```

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
- `esp-matter-datamodel/.../datamodels/datamodel_<version>.json` — the
  per-version data models (committed; regenerate from a connectedhomeip
  checkout with the esp-matter-datamodel CLI when a new spec version lands).

## Development

```bash
pip install -r requirements.txt pytest
python3 -m pytest              # conftest.py wires up the in-repo packages
./build_tool.sh                # rebuild the web bundle after engine/UI changes
# regenerate golden snapshots after an intended output change:
python3 tools/update_golden.py
```
