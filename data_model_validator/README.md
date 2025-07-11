# Device Datamodel Parser & Validator

A comprehensive tool for parsing Matter/Zigbee device wildcard logs and validating compliance against CHIP SDK specifications.

## 🔍 What This Tool Does

This tool helps you:
- **Parse** device wildcard log files (.txt) into structured data
- **Validate** device compliance against Matter specifications
- **Analyze** device clusters, attributes, commands, and features
- **Generate** detailed compliance reports
- **Compare** devices against different CHIP SDK versions (1.3, 1.4, 1.4.1, 1.4.2, master)

## ✨ Key Features

### 📄 **Detailed Reports**
- Downloadable JSON reports
- Visual compliance summaries
- Per-endpoint breakdown
- Missing elements highlighting

### 🚀 **Two Usage Options**
- **Web Interface**: Interactive browser-based tool
- **CLI Script**: Terminal-based for automation/CI

## 📋 Installation & Setup

### Prerequisites
```bash
# Python 3.7+ required
python --version

# Install dependencies
pip install -r requirements.txt
```

## 🎯 Usage Options

### Option 1: Web Interface (Recommended)
```bash
# 1. Start the web server
python run.py

# 2. Open browser to:
http://localhost:5000

# 3. Upload .txt file, select version, validate compliance
```

### Option 2: CLI Script
```bash
# Run compliance check directly
python datamodel_parser.py your_file.txt --chip-version 1.4.1

# Options:
python datamodel_parser.py file.txt --chip-version 1.4.2 --verbose
python datamodel_parser.py file.txt --quiet  # minimal output
python datamodel_parser.py --test            # run tests

# Results saved to: output/parsed_data.json, output/validation_results.json
```

## 🎯 How to Use

### Step 1: Prepare Your Data
1. **Wildcard Log File**: Have your device's `.txt` wildcard log file ready
2. **Get Wildcards**: Use chip-tool to read wildcards from device
```bash
./chip-tool any read-by-id 0xFFFFFFFF 0xFFFFFFFF <node-id> 0xFFFF
```

### Step 2: Choose Your Method

#### Web Interface
1. **Upload**: Drag & drop or choose your `.txt` file
2. **Select Version**: Choose CHIP version (1.3, 1.4, 1.4.1, 1.4.2, master)
3. **Validate**: Click "Validate Compliance"
4. **Review**: See detailed results and download reports

#### CLI Script
1. **Run**: `python datamodel_parser.py your_file.txt --chip-version 1.4.1`
2. **Review**: See terminal output and check `output/` directory for JSON files

## 📁 File Structure

```
Data Model Validator/
├── 📄 run.py                    # Web server launcher
├── 📄 datamodel_parser.py       # CLI script
├── 📄 requirements.txt          # Dependencies
├── 📂 core/                     # Core parsing & validation logic
├── 📂 data/                     # Element requirements files
│   ├── 📄 element_requirements_1.3.json
│   ├── 📄 element_requirements_1.4.json
│   ├── 📄 element_requirements_1.4.1.json
│   ├── 📄 element_requirements_1.4.2.json
│   └── 📄 element_requirements_master.json
├── 📂 templates/                # Web interface templates
├── 📂 static/                   # CSS/JS for web interface
└── 📂 output/                   # Generated JSON files (CLI)
```

## 🚨 Troubleshooting

### Common Issues
- **"No module named 'flask'"** → Run `pip install -r requirements.txt`
- **"No [TOO] entries found"** → Wrong file format, need wildcard log with [TOO] entries
- **"Version X.X not supported"** → Missing `data/element_requirements_X.X.json` file

### Understanding Results
- **Compliant**: Device meets all requirements
- **Non-Compliant**: Missing required clusters/attributes/commands/features
- **Events**: Skipped (not in wildcard logs) - warnings only

## 🎯 Quick Start Examples

### Web Tool
```bash
pip install -r requirements.txt
python run.py
# Open http://localhost:5000
```

### CLI Tool
```bash
pip install -r requirements.txt
python datamodel_parser.py device_log.txt --chip-version 1.4.1
# Check output/ directory for results
```

### Run Tests
```bash
python datamodel_parser.py --test
``` 