# Matter Data Model Diff Checker

A browser-based diff tool for comparing [Matter](https://csa-iot.org/all-solutions/matter/) specification data models across versions. It parses the official XML cluster and device-type definitions and produces a structured, searchable diff.

## What It Does

This tool lets you pick any two Matter spec versions and instantly see what changed:

- **Added / Removed / Modified clusters** — with full detail down to individual attributes, commands, events, features, data types, and their fields.
- **Added / Removed / Modified device types** — including cluster requirements, condition requirements, features, and commands.
- **Revision tracking** — highlights clusters or device types whose content changed but whose revision number was *not* bumped ("No Revision Update" warnings).
- **Deep search** — type any term (an attribute name, a command, an event, a feature flag, an enum value) and the tool filters the diff to show only matching elements, even inside nested structures.
- **Export** — download the computed diff as a JSON file for offline analysis or integration with other tooling.

## Running Locally

Serve the directory with any static HTTP server:

```bash
cd dm_diff_tool
python3 -m http.server 8000
```

Then open `http://localhost:8000` in your browser. If you add or remove spec versions, regenerate the manifest first: `python3 generate_manifest.py`.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for GitHub Pages and S3 deployment instructions.

## Data Model Versions

The `data_model/` directory is copied verbatim from the [`connectedhomeip` master branch](https://github.com/project-chip/connectedhomeip/tree/master/data_model). It needs to be kept in sync — whenever CSA publishes a new spec revision and the upstream directory updates, refresh the local copy and run `python3 generate_manifest.py` to regenerate the manifest.

Versions currently included:

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

