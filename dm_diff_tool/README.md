# Matter Data Model Diff Checker

A browser-based diff tool for comparing [Matter](https://csa-iot.org/all-solutions/matter/) specification data models across versions. It parses the official XML cluster and device-type definitions and produces a structured, searchable diff.

## What It Does

This tool lets you pick any two Matter spec versions and instantly see what changed:

- **Added / Removed / Modified clusters** — with full detail down to individual attributes, commands, events, features, data types, and their fields.
- **Added / Removed / Modified device types** — including cluster requirements, condition requirements, features, and commands.
- **Revision tracking** — highlights clusters or device types whose content changed but whose revision number was *not* bumped ("No Revision Update" warnings).
- **Deep search** — type any term (an attribute name, a command, an event, a feature flag, an enum value) and the tool filters the diff to show only matching elements, even inside nested structures.
- **Export** — download the computed diff as a JSON file for offline analysis or integration with other tooling.

## Screenshots

| Dark Mode | Light Mode |
|-----------|-----------|
| ![Dark mode](static/diff_checker.png) | ![Light mode](static/diff_checker_light.png) |

## Running Locally

Serve the directory with any static HTTP server:

```bash
cd dm_diff_tool
python3 -m http.server 8000
```

Then open `http://localhost:8000` in your browser.

## Adding or Updating a Matter Version

Neither the raw XML files nor the built zips are committed — the deploy CI builds everything from [connectedhomeip](https://github.com/project-chip/connectedhomeip) on every push to `main`.

To build locally for development:

```bash
export MATTER_SDK_PATH=/path/to/connectedhomeip
python3 build_zips.py
```

This reads `$MATTER_SDK_PATH/data_model/{version}/clusters/` and `$MATTER_SDK_PATH/data_model/{version}/device_types/`, produces one zip per version under `data_model/zips/`, and regenerates `data_manifest.json`. Neither output needs to be committed.

## Supported Versions

| 1.0 | 1.1 | 1.2 | 1.3 | 1.4 | 1.4.1 | 1.4.2 | 1.5 | 1.5.1 | 1.6 |
