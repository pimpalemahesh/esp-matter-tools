# esp-matter-datamodel

A **tool-neutral, versioned representation of the Matter data model as JSON**,
derived from the connectedhomeip specification XML files. It is the shared
foundation for esp-matter-tools: one spec-XML parser, one schema, one set of
generated JSON — so every tool that needs the data model reads the same source
of truth instead of re-parsing XML.

It contains **no PICS (or any other tool) concepts** — just the Matter data
model: clusters, device types, and their conformance.

## Why it exists

Consumers depend on the JSON **contract** (`schema/datamodel.schema.json`), not
on the parser. The XML→JSON producer (`ingest/`) is therefore replaceable: any
JSON that validates against the schema can be loaded, whoever produced it.

Unlike ad-hoc parsers, the JSON is **lossless where it matters**: it preserves
the full conformance expression tree (`mandatory if feature X`, `otherwise`
fallbacks, `and/or/not`, comparisons, device conditions) rather than flattening
it to a boolean, so downstream tools can evaluate conformance themselves.

## Install

```bash
pip install -e esp-matter-datamodel
```

## Usage

Build the JSON from a connectedhomeip checkout (maintainer step):

```bash
esp-matter-datamodel build-model \
    --data-model-dir ~/code/connectedhomeip/data_model --version 1.6
# writes esp_matter_datamodel/datamodels/datamodel_1.6.json (validated)
```

Validate any data-model JSON against the schema:

```bash
esp-matter-datamodel validate path/to/datamodel_1.6.json
```

Load it from Python (the API consumers use):

```python
from esp_matter_datamodel import loader
model = loader.load_version("1.6")          # packaged JSON, validated
model = loader.load("some/datamodel.json")  # or any schema-valid file
cluster = model.clusters["0x0006"]          # On/Off
```

## JSON shape (summary)

```jsonc
{
  "schema_version": "1.0.0",
  "spec_version": "1.6",
  "provenance": { "spec_sha": "...", "scraper_version": "...", "generated_from": "data_model/1.6" },
  "clusters": {
    "0x0006": {
      "id": "0x0006", "name": "On/Off", "pics": "OO", "revision": 6,
      "features":   { "0": { "bit": 0, "mask": 1, "code": "LT", "name": "Lighting", "conformance": {...} } },
      "attributes": { "0x4000": { "id": "0x4000", "name": "GlobalSceneControl",
                                  "conformance": { "type": "mandatory",
                                                   "condition": { "op": "feature", "code": "LT", "bit": 0 } } } },
      "accepted_commands": { ... }, "generated_commands": { ... }, "events": { ... }
    }
  },
  "device_types": {
    "0x0100": { "id": "0x0100", "name": "On/Off Light", "revision": 3,
                "server_clusters": { "0x0006": { "conformance": {...},
                                                 "feature_overrides": { "0": { "conformance": {"type":"mandatory"} } } } },
                "client_clusters": {} }
  },
  "base_device_type": { ... }   // clusters present on every endpoint (merged by consumers)
}
```

### Conformance node grammar

A conformance is `{"type": mandatory|optional|provisional|disallowed|deprecated,
"condition"?, "choice"?}` or `{"type": "otherwise", "items": [...]}`. A
`condition` is a boolean tree of `and`/`or`/`not` over leaves: `feature`,
`attribute`, `command`, `condition` (device conditions like `Wi-Fi`/`IP`),
`compare` (with `revision`/`literal` operands), and `unsupported` (preserved but
not evaluated). Derived clusters inherit their base cluster's elements.

The schema is versioned and **additive**: new sections (access, quality,
constraints, data types) can be added in later minor versions without breaking
existing consumers.

## Development

```bash
pip install -r requirements-test.txt
python3 -m pytest
```
