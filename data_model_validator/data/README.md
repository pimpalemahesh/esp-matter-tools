# Element Requirements Data Directory

This directory should contain the element requirements JSON files for different CHIP SDK versions.

## Required Files

Place the following files in this directory for version support:

- `element_requirements_1.3.json` - Element requirements for version 1.3
- `element_requirements_1.4.json` - Element requirements for version 1.4
- `element_requirements_1.4.1.json` - Element requirements for version 1.4.1
- `element_requirements_1.4.2.json` - Element requirements for version 1.4.2
- `element_requirements_master.json` - Element requirements for master version

## File Format

Each file should contain a JSON array of device type requirements with the following structure:

```json
[
  {
    "id": "0x0100",
    "name": "on_off_light",
    "clusters": [
      {
        "id": "0x0006",
        "name": "on_off",
        "type": "server",
        "attributes": [...],
        "commands": [...],
        "features": [...]
      }
    ]
  }
]
```

## How to Generate

You can generate these files using the data_model processing scripts with your CHIP SDK installation:

```bash
python data_model/app.py --chip_path /path/to/connectedhomeip --chip_version_dir 1.4.1 --output_dir output
```

This will generate `output/element_requirements_1.4.1.json` which should be copied to this directory.

## Version Support

- When a version's element requirements file is present, it will appear as a supported option in the UI
- If a user selects a version without a corresponding file, they'll see a "not supported yet" message
- Add new files here to enable support for additional versions
