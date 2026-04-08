# MatterDMDiff

A browser-based diff tool for comparing [Matter](https://csa-iot.org/all-solutions/matter/) specification data models across versions. It parses the official XML cluster and device-type definitions and produces a structured, searchable diff.

## What It Does

MatterDMDiff lets you pick any two Matter spec versions and instantly see what changed:

- **Added / Removed / Modified clusters** — with full detail down to individual attributes, commands, events, features, data types, and their fields.
- **Added / Removed / Modified device types** — including cluster requirements, condition requirements, features, and commands.
- **Revision tracking** — highlights clusters or device types whose content changed but whose revision number was *not* bumped ("No Revision Update" warnings).
- **Deep search** — type any term (an attribute name, a command, an event, a feature flag, an enum value) and the tool filters the diff to show only matching elements, even inside nested structures.
- **Export** — download the computed diff as a JSON file for offline analysis or integration with other tooling.

## Running Locally

Serve the directory with any static HTTP server:

```bash
cd MatterDMDiff
python3 -m http.server 8000
```

Then open `http://localhost:8000` in your browser.

## Deploying to S3

Upload the entire `MatterDMDiff/` directory to an S3 bucket with public read access. Ensure the bucket has CORS configured to allow `GET` requests from the bucket's own origin. The tool will auto-discover versions via the S3 `ListObjectsV2` API.

If the S3 bucket does not support listing (e.g., behind CloudFront without list permissions), generate a manifest before uploading:

```bash
python3 -c "
import os, json, re
manifest = {}
for ver in sorted(os.listdir('data_model')):
    if not os.path.isdir(f'data_model/{ver}') or not re.match(r'^\d+(\.\d+)*$', ver):
        continue
    entry = {'clusters': [], 'device_types': []}
    for cat in ['clusters', 'device_types']:
        p = f'data_model/{ver}/{cat}'
        if os.path.isdir(p):
            entry[cat] = sorted(f for f in os.listdir(p) if f.endswith('.xml'))
    manifest[ver] = entry
sorted_m = dict(sorted(manifest.items(), key=lambda x: [int(n) for n in x[0].split('.')]))
with open('data_manifest.json', 'w') as f:
    json.dump(sorted_m, f, indent=2)
print('Generated data_manifest.json')
"
```

## Data Model Versions

The `data_model/` directory contains the official Matter specification XMLs organized by version:

| Version | Clusters | Device Types |
|---------|----------|-------------|
| 1.0     | Core     | Core        |
| 1.1     | +Updates | +Updates    |
| 1.2     | +Updates | +Updates    |
| 1.3     | +Updates | +Updates    |
| 1.4     | +Updates | +Updates    |
| 1.4.1   | Patch    | Patch       |
| 1.4.2   | Patch    | Patch       |
| 1.5     | +Updates | +Updates    |
| 1.5.1   | Patch    | Patch       |
| 1.6     | +Updates | +Updates    |

## Project Structure

```
MatterDMDiff/
  index.html        # Single-file SPA (HTML + CSS + JavaScript)
  diff_engine.py    # Python diff engine (runs in-browser via Pyodide)
  tests/
    test_diff_engine.py   # Unit tests for the diff engine
  data_model/
    1.0/ ... 1.6/   # Matter spec XML files per version
      clusters/     # Cluster definition XMLs
      device_types/ # Device type definition XMLs
```

## Technology Stack

- **Frontend**: Vanilla HTML / CSS / JavaScript (no build step, no framework)
- **Diff Engine**: Python 3 running in-browser via [Pyodide](https://pyodide.org/) (WebAssembly)
- **Data**: Official Matter specification XML files from the CSA

## License

Copyright 2026 Espressif Systems
